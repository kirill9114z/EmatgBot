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

### The three `is_ab` filter/format modes

This is the key branching axis through `filter_worker`, `passes_all_filters`, and `Sender` — the
same signal is filtered and formatted completely differently depending on the chat's mode:

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
