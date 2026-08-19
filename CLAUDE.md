# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Signal Aggregator Bot: listens to Telegram channels via Telethon, parses trading-signal messages
(pair + % change), runs the signals through configurable filters against live Bybit market data
(via ccxt), and forwards passing signals as formatted messages to a set of output Telegram chats
via aiogram. Everything runs as a single asyncio process — no web server, no database (state is a
flat JSON file).

## Running it

```bash
pip install ccxt aiogram telethon python-dotenv pandas pandas_ta_classic
python main.py
```

There is no `requirements.txt` — the README documents `pip install -r requirements.txt` but the
file doesn't exist in the repo; install the packages above manually (or create the file if asked).
No test suite, linter, or build step exists in this repo.

### Required files not present in the repo

Two files are imported/loaded at runtime but are not tracked in git — either create them locally
or ask the user for them before assuming `main.py` can run:

- **`utils.py`** — imported by `main.py` (`logger`), `filters.py` (`retry_sleep`, `now_ts`), and
  `sender.py` (`now_ts`). `retry_sleep` is used as a decorator (`@retry_sleep(tries=3)`) around
  the ccxt fetch calls in `filters.py`, so it needs to wrap an async function and retry with a
  sleep on failure. `now_ts` returns a Unix timestamp (used for dedup bookkeeping in `storage.py`
  comparisons). `logger` is a stdlib `logging.Logger`.
- **`config.json`** — loaded by `main.py:load_config()`. Must contain
  `{"aiogram": {"bot_token": "..."}, "telethon": {"api_id": ..., "api_hash": ...}}`.

`storage.json` (the `JSONStorage` state file) and the Telethon `session` file are both created
automatically at first run and are not meant to be hand-edited.

**Note:** `.env` is currently committed to this repo. Treat any values in it as already-exposed
secrets, not as a template.

## Configuration model

Two separate, overlapping config systems feed the pipeline — don't conflate them:

- **`config.json`** (see above) — bot token and Telethon API credentials only.
- **`.env` + `config.py:load_config2()`** — everything else: per-chat filter thresholds, volume
  minimums, dedup windows, timeframes, RSI settings, and pivot levels. `load_config2()` returns a
  nested dict (`config["global"]`, `config["chats"][chat_name]`) rebuilt from env vars on every
  call, with **chat IDs and chat names (`CHAT_A`...`CHAT_F`) hardcoded in `config.py`** rather than
  read from env.
- Pivot levels (`R1`-`R5`, `S1`-`S5`) for `CHAT_E`/`CHAT_F` are parsed directly out of the `.env`
  *file text* by `parse_pivot_config_from_env()` (regex over raw lines, not `os.getenv`) — editing
  these requires editing `.env` itself, not just process env vars.

Each configured chat has an `is_ab` mode that selects which filter/format code path it runs
through end-to-end (see below). Adding a new output chat means adding an entry to the `chats` dict
in `config.py` with one of the three `is_ab` shapes, plus a matching branch already exists in
`main.py:filter_worker` and `sender.py:Sender`.

## Pipeline architecture

Three asyncio queues/stages, wired up in `main.py:main()`:

1. **`start_telethon`** (`telethon_listener.py`) — one Telethon client listening on configured
   channels, pushes every raw message as a dict (`text`, `sender_id`, `date`, `channel`, `side` =
   the source chat's username) onto `raw_queue`. Auto-reconnects on error with a 60s backoff.
2. **`filter_worker`** (`main.py`, 3 concurrent instances) — pulls from `raw_queue`,
   `signal_parser.parse_raw_message` extracts `(pair, side, pct_change)` from the raw text, then
   for *every configured chat* runs the appropriate filter path from `filters.py`
   (`passes_all_filters`) against a shared `ccxt.bybit` instance. Passing signals become a payload
   dict pushed onto `out_queue` along with the target `chat_id`.
3. **`sender_worker`** (`main.py`, single instance) — pulls from `out_queue`, calls
   `Sender.send_signal` (`sender.py`), which dedups against `storage.json` (skip if the same pair
   was already sent to that chat within `send_again` seconds) and sends via aiogram.

### Second, independent source: the Bybit market scanner

`market_scanner.py:scanner_loop` runs as a fourth background task alongside the Telegram
pipeline. It does **not** consume `raw_queue` — it polls the Bybit perpetual-futures market
itself every `SCAN_MINTIME` seconds, filters coins, and pushes finished payloads straight onto
`out_queue`, so it reuses the existing `sender_worker`, `Sender`, and `storage.json` dedup.

- Chats `SCAN_A` / `SCAN_B` (= "CHAT A" / "CHAT B" in the customer's newer TZ). Config lives in
  `config.py:load_scanner_config()` / `load_scanner_chat()`, env prefix `SCAN_A_*` / `SCAN_B_*`,
  globals `SCAN_VOLUME` / `SCAN_MINTIME` / `SCAN_DUPLICATE`.
  These were called `CHAT_G` / `CHAT_H` until the WAE chats were ported; the letters G/H/I were
  handed back to WAE, where they had been from the start, so the customer's old settings copy
  over unchanged. `CHAT_A_RSI` is a different chat entirely — don't confuse `SCAN_A` with `CHAT_A`.
- Per-chat filters, each independently disable-able with `off` in `.env`: `RSI`,
  `CANDLE_COLOUR` (required), `PREVIOS_CANDLE`, `CANDLE_SIZE`, `CHANGE`. All of them are
  evaluated on the **current, unclosed candle** (`ohlcv[-1]`); `ohlcv[-2]` is the previous closed
  one. Candle bodies are measured **without wicks**: `(close - open) / open * 100`.
- `Sender` dispatches on `is_ab == "scanner"` → `format_scanner_message`. Because `"scanner"` is a
  truthy string, that check must stay **before** `elif is_ab:` in `send_signal`.
- Request budget: tickers come from a single `fetch_tickers(category=linear)` call, OHLCV is
  fetched once per *timeframe* and shared across chats, and the `PERIOD_INFO` candles are fetched
  only for pairs that already passed. Keep it that way — a naive per-chat/per-symbol fetch is
  hundreds of extra requests per minute.
- `body_size_ratio()` is the single point of truth for the `CANDLE_SIZE` formula; the TZ contains
  a contradiction (its example computes 54.57% but the text also says 80%), so that function
  carries the reasoning and is the only place to change if the customer clarifies.

### WAE chats (`CHAT_G` / `CHAT_H` / `CHAT_I`) — chats 7/8/9

Waddah Attar Explosion V2. These run **inside the same `scan_once` pass** as the candle scanner
chats — same market snapshot, same downloaded OHLCV, same connection pool. Do not split them into
a second loop; that doubles exchange traffic for no benefit.

- **`wae_filter.py` is a byte-for-byte port from the customer's older build and must not be
  edited.** It is the reference implementation: `wae_v2` (indicator) and `check_sequence` (the
  actual pass/fail rule). `check_sequence` is what the scanner calls, unchanged.
- **`wae_fast.py`** holds the same maths vectorised: `wae_v2_fast` (single pair) and
  `compute_wae_map` (whole market as one matrix, ~10x faster than the reference). Equivalence is
  not assumed — `verify_wae.py` checks it against `wae_filter` on live Bybit data and compares
  `check_sequence` decisions, not just numbers. Run it after touching either module.
- In the old build these chats filtered signals arriving from Telegram channels
  (`is_ab == "FOUR"` inside `filter_worker`). They were converted to market scanning, so the
  filter logic is identical but the data source is not: the first line of the message shows the
  current candle's body instead of the percentage parsed from a channel message.
- Config: `config.py:load_wae_config()` / `load_wae_chat()` / `load_wae_sequence()` /
  `load_wae_change()`. **Every env key matches the customer's old build** (`CHAT_G_TIMEFRAME_GLOBAL`,
  `ALLTIME_G`, `Time_G_1`, `COLOUR_G`, `POWER_G`, `CHANGE_G`, `CHANGE_G_TIMEFRAIM`, `CHANGE_G_IS`)
  so settings copy over verbatim — this is why the candle scanner had to give the letters back.
  The one new key is `CHAT_G_CHAT_ID`: the old build hardcoded chat ids in `config.py`.
  Volume, dedup window and default timeframe come from the **shared** globals `MIN_VOLUME_`,
  `SEND_DUPLICATE_PAIR_SECONDS`, `TIMEFRAME_GLOBAL` — that is a customer requirement.
- `CHANGE_*` is a port of the old `Last_DAY` block and is both a filter and the message's last
  line. Its quirks are preserved: the timeframe is always daily and only the number is read from
  `CHANGE_G_TIMEFRAIM` (`15d` → 15 daily candles); when `CHANGE_G_IS=0` the change is still shown
  (over 1 day) but not filtered on, and the label keeps whatever `CHANGE_G_TIMEFRAIM` says.
- `load_wae_sequence` reproduces the original `load_config_WAE`, including `alltime -= 1` and the
  reversal, so `ALLTIME_G=2` yields a two-bar sequence. Sequence order is oldest bar first.
- Known quirk inherited from the original: for a sequence of length *n*, `check_sequence` indexes
  bars `-n … -1`, so the newest bar checked is the **current unclosed** one, despite the comment
  claiming `-2`. Reproduced deliberately — changing it changes which signals fire.

### Scanner request budget and throughput

Measured against live Bybit, not guessed — re-measure before changing any of it:

- ccxt's own `enableRateLimit` yields only ~10 req/s because it serialises requests. It is turned
  **off** on purpose; pacing is done by `market_scanner.RateLimiter` at `SCAN_REQ_PER_SEC`
  (default 40). Bybit v5 public endpoints allow 600 requests / 5 s per IP, so 40/s leaves 3x
  headroom. This alone took a cycle from 19.6 s to 5.7 s.
- `FETCH_CONCURRENCY` (default 20, env `SCAN_CONCURRENCY`) is a measured optimum, not caution:
  20 → 57 req/s, 50 → 35 req/s, 100 → 20 req/s. Raising it makes things slower.
- All timeframes are fetched in a **single** `asyncio.gather` (`fetch_candles_by_tf`), not one
  gather per timeframe, so the pool never drains between timeframes.
- WAE is computed once per *timeframe* and shared by every chat on it; `compute_wae_map` batches
  the whole market into one matrix per candle-count group.
- `PERIOD_INFO` change is taken from already-downloaded candles when that timeframe was fetched
  anyway (`period_change_from_candles`), and only falls back to a request otherwise.

### The `is_ab` filter/format modes

This is the key branching axis through `filter_worker`, `passes_all_filters`, and `Sender` — the
same signal is filtered and formatted completely differently depending on the chat's mode.
`"scanner"` and `"wae"` are truthy strings, so in `Sender.send_signal` both must stay **before**
the `elif is_ab:` branch:

- **`is_ab == True`** ("AB" chats, e.g. `CHAT_A`/`CHAT_B`): volume threshold + EMA deviation filter
  (optionally gated by RSI), then a global daily-change threshold check via `fetch_ohlcv`. Uses
  `Sender.format_message`.
- **`is_ab == "Three"`** (e.g. `CHAT_E`/`CHAT_F`): pivot-point filter — checks price deviation
  against calculated support/resistance levels (`filters.py:pivot_allchack`/`check_level`/
  `calculate_pivot_points`) per the chat's `FILTR_S/R` config. Dedup and formatting are keyed by
  pivot level + timeframe (`Sender.format_text_pivot`, `storage.get_last_sent_pivot`).
- **`is_ab == False`** (e.g. `CHAT_C`/`CHAT_D`): volume-SMA + candle-color pattern filter
  (`one_sma_filter`) checked across a sequence of historical candles (`ALLTIME`/`Time_lst`),
  requiring candle colors to match an expected sequence, then an EMA deviation filter on top. Uses
  `Sender.format_text2_group34`.

When touching filter or formatting logic, check which `is_ab` branch you're in across all three
files (`main.py`, `filters.py`, `sender.py`) — they're parallel implementations, not shared code.

### Bybit symbol fallback pattern

Pairs are built as `"BASE/QUOTE:USDT"` (ccxt's linear-swap syntax) but Bybit doesn't list every
symbol as a swap. The recurring pattern throughout `filters.py`/`main.py` is: try the `:USDT`
swap symbol first, and if the exchange calls fail (`vol == False`, i.e. "bybit does not have
market symbol"), retry with the plain spot symbol (`pair.split(':')[0]`). Preserve this fallback
when adding new exchange calls.
