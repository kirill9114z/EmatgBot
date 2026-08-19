"""Сканер рынка Bybit (бессрочные фьючерсы USDT) для чатов CHAT_G / CHAT_H.

В отличие от чатов A-F, здесь мы не ждём алертов из telegram-каналов, а сами
раз в MINTIME секунд опрашиваем рынок:

    1. берём все бессрочные USDT-фьючерсы и отсеиваем по суточному обороту;
    2. по оставшимся тянем свечи и прогоняем через фильтры каждого чата
       (фильтры чатов независимы друг от друга);
    3. прошедшие пары кладём в общую out_queue — дедупликацию и отправку
       делает существующий sender_worker.

Все фильтры считаются по ТЕКУЩЕЙ незакрытой свече (ohlcv[-1]);
предыдущая закрытая свеча — ohlcv[-2].
"""
import asyncio
import logging
import os
import re
import time

import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta_classic as ta

from wae_fast import compute_wae_map
from wae_filter import check_sequence

logger = logging.getLogger("market_scanner")

# Сколько свечей тянем на пару: с запасом для RSI(14), для кружков
# PERIOD_CANDLES и для WAE (ему нужно минимум 101, dead_zone считается на 100).
OHLCV_LIMIT = 200

# Одновременных запросов к бирже.
#
# Замеры на живом Bybit (60 запросов fetch_ohlcv):
#     concurrency=20   57 req/s   средний ответ  270 мс
#     concurrency=50   35 req/s   средний ответ  777 мс
#     concurrency=100  20 req/s   средний ответ 1092 мс
# Дальше 20 биржа начинает придерживать ответы, и рост параллельности делает
# только хуже. Поэтому 20 — не осторожность, а измеренный оптимум.
FETCH_CONCURRENCY = int(os.getenv('SCAN_CONCURRENCY', 20))

# Свой ограничитель темпа вместо ccxt-шного.
#
# enableRateLimit=True у ccxt для bybit даёт всего ~10 req/s (тот же замер:
# 9.7 против 57 req/s без него) — он сериализует запросы через одну очередь.
# Публичные эндпоинты Bybit v5 разрешают 600 запросов за 5 секунд на IP,
# то есть 120 req/s, так что 40 req/s — это троекратный запас по лимиту и
# при этом вчетверо быстрее штатного троттлера.
REQUESTS_PER_SECOND = float(os.getenv('SCAN_REQ_PER_SEC', 40))

# Раз в столько циклов перечитываем список рынков (появляются/уходят монеты).
MARKETS_RELOAD_EVERY = 60

RSI_LENGTH = 14

# Регистр важен только для M: 'M' — месяц, 'm' — минута. Остальные буквы
# принимаем в любом регистре ('15D' из ТЗ и '15d' — одно и то же).
_PERIOD_RE = re.compile(r'^\s*(\d+)\s*([mMhHdDwW])\s*$')


def parse_period_info(raw):
    """'15D' -> (15, '1d'). Возвращает (кол-во периодов, таймфрейм) или None.

    Регистр важен только для 'M' (месяц) против 'm' (минута).
    """
    match = _PERIOD_RE.match(str(raw or ''))
    if not match:
        logger.warning("PERIOD_INFO='%s' не распознан, строка периода не будет показана", raw)
        return None
    count, unit = int(match.group(1)), match.group(2)
    if count < 1:
        return None
    timeframe = '1M' if unit == 'M' else f"1{unit.lower()}"
    return count, timeframe


def body_pct(candle):
    """Размер тела свечи в процентах, БЕЗ фитилей: (close - open) / open * 100."""
    open_, close = float(candle[1]), float(candle[4])
    if open_ == 0:
        return None
    return (close - open_) / open_ * 100


def candle_colour(candle):
    """Цвет тела свечи. Свеча без движения считается зелёной."""
    return 'green' if float(candle[4]) >= float(candle[1]) else 'red'


def body_size_ratio(prev_body, curr_body):
    """CHAT_X_CANDLE_SIZE: размер тела текущей свечи в % от тела предыдущей.

    Пример из ТЗ: предыдущая свеча +3,28%, текущая -1,79%
        -> 1,79 / 3,28 * 100 = 54,57%
    именно это число заказчик привёл словами ("размер тела у текущей = 54,57%
    от предыдущей"). Стоящее рядом "80%" — это значение порога из строки
    настройки выше, а не результат формулы.

    ЕСЛИ ЗАКАЗЧИК УТОЧНИТ ФОРМУЛУ — МЕНЯТЬ ТОЛЬКО ЗДЕСЬ.
    """
    if not prev_body:
        return None
    return abs(curr_body) / abs(prev_body) * 100


def compute_rsi(closes, length=RSI_LENGTH):
    """RSI по ценам закрытия, включая текущую незакрытую свечу."""
    if len(closes) < length + 1:
        return None
    try:
        rsi = ta.rsi(pd.Series(closes, dtype='float64'), length=length)
    except Exception as e:
        logger.debug("RSI failed: %s", e)
        return None
    if rsi is None or rsi.empty or pd.isna(rsi.iloc[-1]):
        return None
    return float(rsi.iloc[-1])


def passes_scanner_filters(chat_cfg, ohlcv):
    """Прогоняет одну пару через фильтры одного чата.

    Возвращает данные для сообщения (dict), если пара прошла ВСЕ включённые
    фильтры, иначе None. Фильтры со значением None в конфиге считаются
    выключенными (в .env это 'off').
    """
    if not ohlcv or len(ohlcv) < 2:
        return None

    current, previous = ohlcv[-1], ohlcv[-2]
    curr_body = body_pct(current)
    prev_body = body_pct(previous)
    if curr_body is None or prev_body is None:
        return None

    # 1. Цвет тела текущей свечи (обязательный фильтр).
    colour = candle_colour(current)
    if colour != chat_cfg['CANDLE_COLOUR']:
        return None

    # 2. Цвет тела предыдущей закрытой свечи.
    if chat_cfg['PREVIOS_CANDLE'] and candle_colour(previous) != chat_cfg['PREVIOS_CANDLE']:
        return None

    # 3. Движение тела текущей свечи: по зелёной — вверх от CHANGE и более,
    #    по красной — вниз от CHANGE и более.
    change_cfg = chat_cfg['CHANGE']
    if change_cfg is not None:
        if colour == 'green' and curr_body < change_cfg:
            return None
        if colour == 'red' and curr_body > -change_cfg:
            return None

    # 4. Размер тела текущей свечи относительно предыдущей.
    ratio = body_size_ratio(prev_body, curr_body)
    if chat_cfg['CANDLE_SIZE'] is not None:
        if ratio is None or ratio < chat_cfg['CANDLE_SIZE']:
            return None

    # 5. RSI на том же таймфрейме, что и свечи (от указанного значения и более).
    rsi = None
    if chat_cfg['RSI'] is not None:
        rsi = compute_rsi([c[4] for c in ohlcv])
        if rsi is None or rsi < chat_cfg['RSI']:
            return None

    # Кружки: последние N свечей, последняя — текущая.
    circles = [candle_colour(c) for c in ohlcv[-chat_cfg['PERIOD_CANDLES']:]]

    return {
        'colour': colour,
        'body_pct': curr_body,
        'ratio': ratio,
        'rsi': rsi,
        'circles': circles,
        'timeframe': chat_cfg['CANDLE_TIMEFRAME'],
        'period_info': chat_cfg['PERIOD_INFO'],
    }


class RateLimiter:
    """Не чаще N запросов в секунду, считая по моменту СТАРТА запроса.

    Ccxt-шный троттлер отключён (см. REQUESTS_PER_SECOND), поэтому темп держим
    здесь. Реализация намеренно простая: очередь запросов и так ограничена
    семафором, а точность в пределах миллисекунд тут не нужна.
    """

    def __init__(self, per_second):
        self.interval = 1.0 / per_second if per_second and per_second > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def wait(self):
        if not self.interval:
            return
        async with self._lock:
            now = time.monotonic()
            sleep_for = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self.interval
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)


async def _fetch_ohlcv(exchange, sem, symbol, timeframe, limit, limiter=None):
    """Свечи по одной паре. Ошибка одной пары не должна валить весь скан."""
    async with sem:
        if limiter is not None:
            await limiter.wait()
        try:
            return await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            # Упереться в лимит биржи — это не «пара без данных», это повод
            # снизить SCAN_REQ_PER_SEC, поэтому такое видно и без DEBUG.
            if isinstance(e, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
                logger.warning("Биржа ограничила темп (%s). Снизьте SCAN_REQ_PER_SEC.", e)
            else:
                logger.debug("OHLCV %s %s: %s", symbol, timeframe, e)
            return None


async def _fetch_ohlcv_map(exchange, sem, symbols, timeframe, limit, limiter=None):
    """{symbol: ohlcv} для списка пар на одном таймфрейме."""
    rows = await asyncio.gather(
        *[_fetch_ohlcv(exchange, sem, s, timeframe, limit, limiter) for s in symbols]
    )
    return {s: r for s, r in zip(symbols, rows) if r}


async def fetch_candles_by_tf(exchange, sem, tf_symbols, limit, limiter=None):
    """{таймфрейм: {пара: свечи}} за один общий заход.

    Важно, что все таймфреймы качаются ОДНИМ gather, а не циклом по одному.
    При последовательной загрузке в конце каждого таймфрейма пул соединений
    простаивает, ожидая последние медленные ответы, и это повторяется столько
    раз, сколько таймфреймов. Здесь очередь запросов общая и семафор остаётся
    загруженным до самого конца.
    """
    jobs = [
        (timeframe, symbol)
        for timeframe, symbols in tf_symbols.items()
        for symbol in sorted(symbols)
    ]
    rows = await asyncio.gather(
        *[_fetch_ohlcv(exchange, sem, symbol, timeframe, limit, limiter)
          for timeframe, symbol in jobs]
    )
    result = {timeframe: {} for timeframe in tf_symbols}
    for (timeframe, symbol), ohlcv in zip(jobs, rows):
        if ohlcv:
            result[timeframe][symbol] = ohlcv
    return result


def _ticker_volume(ticker):
    """Суточный оборот в USDT из тикера ccxt."""
    volume = ticker.get('quoteVolume')
    if volume is None:
        volume = (ticker.get('info') or {}).get('turnover24h')
    try:
        return float(volume) if volume is not None else None
    except (TypeError, ValueError):
        return None


async def fetch_market_snapshot(exchange):
    """(список бессрочных USDT-фьючерсов, тикеры по ним) одним запросом.

    Вынесено из select_symbols, чтобы разные группы чатов с разными порогами
    оборота фильтровались по ОДНОМУ снимку рынка, а не тянули тикеры каждая.
    """
    universe = [
        symbol for symbol, market in exchange.markets.items()
        if market.get('swap')
        and market.get('linear')
        and market.get('settle') == 'USDT'
        and market.get('active', True)
    ]
    if not universe:
        return [], {}

    # Один запрос на всю категорию вместо запроса на каждую пару.
    try:
        tickers = await exchange.fetch_tickers(params={'category': 'linear'})
    except Exception as e:
        logger.warning("fetch_tickers(category=linear) не сработал (%s), пробуем по списку", e)
        tickers = await exchange.fetch_tickers(universe)
    return universe, tickers


def symbols_above_volume(universe, tickers, min_volume):
    """Пары из снимка рынка с суточным оборотом от min_volume."""
    selected = []
    for symbol in universe:
        ticker = tickers.get(symbol)
        if not ticker:
            continue
        volume = _ticker_volume(ticker)
        if volume is not None and volume >= min_volume:
            selected.append(symbol)
    return selected


async def select_symbols(exchange, min_volume):
    """Бессрочные USDT-фьючерсы с суточным оборотом от min_volume."""
    universe, tickers = await fetch_market_snapshot(exchange)
    if not universe:
        return []
    return symbols_above_volume(universe, tickers, min_volume)


async def fetch_period_change(exchange, sem, symbol, period_info, limiter=None):
    """Изменение цены за информационный период, например за 15D."""
    parsed = parse_period_info(period_info)
    if not parsed:
        return None
    count, timeframe = parsed
    ohlcv = await _fetch_ohlcv(exchange, sem, symbol, timeframe, count + 1, limiter)
    if not ohlcv or len(ohlcv) < 2:
        return None
    first_close, last_close = float(ohlcv[0][4]), float(ohlcv[-1][4])
    if first_close == 0:
        return None
    return (last_close - first_close) / first_close * 100


def sequence_colours(sequence):
    """['SELL', 'SELL'] из [{'SELL': '10'}, {'SELL': 45}] — для кружков."""
    return [next(iter(item)) for item in sequence or []]


def passes_wae_filters(chat_cfg, wae, ohlcv):
    """Прогоняет посчитанный WAE одной пары через настройки одного чата.

    Сам критерий — wae_filter.check_sequence из старой версии, без изменений:
    у каждого бара последовательности должен совпасть цвет и отрыв гистограммы
    от explosion line должен быть не ниже порога этого бара.
    """
    sequence = chat_cfg['SEQUENCE']
    if not sequence:
        return None

    ok, details = check_sequence(wae, sequence)
    if not ok:
        return None

    body = body_pct(ohlcv[-1]) if ohlcv else None
    return {
        'signal': details.get('wae_signal'),
        'body_pct': body,
        'colours': sequence_colours(sequence),
        'deviation_pct': details.get('deviation_pct'),
        'explosion_line': details.get('explosion_line'),
        'timeframe': chat_cfg['TIMEFRAME'],
        'period_info': chat_cfg['PERIOD_INFO'],
    }


def period_change_from_candles(candles_by_tf, symbol, period_info):
    """Изменение за информационный период по УЖЕ скачанным свечам.

    Возвращает (значение, посчитано_ли). Если нужного таймфрейма среди
    скачанных нет или свечей не хватает — (None, False), и вызывающий код
    доберёт данные отдельным запросом.
    """
    parsed = parse_period_info(period_info)
    if not parsed:
        return None, True  # период не распознан — досылать нечего
    count, timeframe = parsed
    ohlcv = candles_by_tf.get(timeframe, {}).get(symbol)
    if not ohlcv or len(ohlcv) < count + 1:
        return None, False
    first_close = float(ohlcv[-(count + 1)][4])
    last_close = float(ohlcv[-1][4])
    if first_close == 0:
        return None, True
    return (last_close - first_close) / first_close * 100, True


async def scan_once(exchange, chats, scan_cfg, out_queue, wae_chats=None, wae_cfg=None):
    """Один полный проход по рынку. Возвращает число отправленных сигналов.

    Свечные чаты (CHAT_G/H) и WAE-чаты обслуживаются в одном проходе намеренно:
    у них общий снимок рынка, общие скачанные свечи и общий пул соединений.
    Разделение на два независимых цикла удвоило бы трафик к бирже.
    """
    chats = chats or {}
    wae_chats = wae_chats or {}

    universe, tickers = await fetch_market_snapshot(exchange)
    if not universe:
        logger.warning("Сканер: список рынков пуст")
        return 0

    # Один снимок тикеров — два независимых порога оборота.
    symbols = symbols_above_volume(universe, tickers, scan_cfg['VOLUME']) if chats else []
    wae_symbols = symbols_above_volume(universe, tickers, wae_cfg['VOLUME']) if wae_chats else []
    if not symbols and not wae_symbols:
        logger.warning("Сканер: ни одна пара не прошла фильтр по обороту")
        return 0
    logger.info("Сканер: по обороту прошли %s пар (свечные чаты) / %s пар (WAE)",
                len(symbols), len(wae_symbols))

    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    limiter = RateLimiter(REQUESTS_PER_SECOND)

    # Свечи тянем по одному разу на таймфрейм и переиспользуем для всех чатов
    # обеих групп: если WAE_G и CHAT_G сидят на одном таймфрейме, запросы к
    # бирже не удваиваются. Внутри таймфрейма берём объединение нужных пар.
    tf_symbols = {}
    for cfg in chats.values():
        tf_symbols.setdefault(cfg['CANDLE_TIMEFRAME'], set()).update(symbols)
    for cfg in wae_chats.values():
        tf_symbols.setdefault(cfg['TIMEFRAME'], set()).update(wae_symbols)

    started = time.monotonic()
    candles_by_tf = await fetch_candles_by_tf(exchange, sem, tf_symbols, OHLCV_LIMIT, limiter)
    fetched = sum(len(v) for v in candles_by_tf.values())
    logger.info("Сканер: скачано %s серий свечей на %s таймфреймах за %.1fс",
                fetched, len(tf_symbols), time.monotonic() - started)

    # WAE считаем один раз на таймфрейм и переиспользуем всеми чатами этого
    # таймфрейма: три чата на 1d — это один расчёт по рынку, а не три.
    wae_by_tf = {}
    for timeframe in {cfg['TIMEFRAME'] for cfg in wae_chats.values()}:
        candles = candles_by_tf.get(timeframe, {})
        subset = {s: candles[s] for s in wae_symbols if s in candles}
        started = time.monotonic()
        wae_by_tf[timeframe] = compute_wae_map(subset)
        logger.info("Сканер: WAE %s посчитан по %s парам за %.2fс",
                    timeframe, len(wae_by_tf[timeframe]), time.monotonic() - started)

    # Информационный период тянем только для прошедших пар и кэшируем на цикл.
    period_cache = {}
    queued = 0

    async def resolve_period_change(symbol, period_info):
        """Изменение за период: сначала из скачанного, иначе отдельным запросом."""
        cache_key = (symbol, period_info)
        if cache_key in period_cache:
            return period_cache[cache_key]
        value, done = period_change_from_candles(candles_by_tf, symbol, period_info)
        if not done:
            value = await fetch_period_change(exchange, sem, symbol, period_info, limiter)
        period_cache[cache_key] = value
        return value

    for chat_name, chat_cfg in chats.items():
        candles = candles_by_tf.get(chat_cfg['CANDLE_TIMEFRAME'], {})
        passed = 0
        for symbol in symbols:
            ohlcv = candles.get(symbol)
            if not ohlcv:
                continue
            try:
                payload = passes_scanner_filters(chat_cfg, ohlcv)
            except Exception as e:
                logger.debug("Фильтры %s для %s: %s", chat_name, symbol, e)
                continue
            if not payload:
                continue

            payload['period_change'] = await resolve_period_change(
                symbol, chat_cfg['PERIOD_INFO']
            )

            await out_queue.put({
                "chat_cfg": chat_cfg['chat_id'],
                "pair": symbol,
                "payload": payload,
                "send_again": scan_cfg['DUPLICATE'],
                "is_ab": "scanner",
            })
            passed += 1
        queued += passed
        logger.info("Сканер: %s — прошли фильтры %s пар", chat_name, passed)

    for chat_name, chat_cfg in wae_chats.items():
        candles = candles_by_tf.get(chat_cfg['TIMEFRAME'], {})
        wae_map = wae_by_tf.get(chat_cfg['TIMEFRAME'], {})
        passed = 0
        for symbol, wae in wae_map.items():
            try:
                payload = passes_wae_filters(chat_cfg, wae, candles.get(symbol))
            except Exception as e:
                logger.debug("WAE %s для %s: %s", chat_name, symbol, e)
                continue
            if not payload:
                continue

            payload['period_change'] = await resolve_period_change(
                symbol, chat_cfg['PERIOD_INFO']
            )

            await out_queue.put({
                "chat_cfg": chat_cfg['chat_id'],
                "pair": symbol,
                "payload": payload,
                "send_again": wae_cfg['DUPLICATE'],
                "is_ab": "wae",
            })
            passed += 1
        queued += passed
        logger.info("Сканер: %s — прошли фильтр WAE %s пар", chat_name, passed)

    return queued


async def scanner_loop(out_queue, scan_cfg, wae_cfg=None):
    """Бесконечный цикл сканирования. Сам переживает падения биржи/сети."""
    chats = {name: cfg for name, cfg in scan_cfg['chats'].items() if cfg['chat_id']}
    wae_chats = {
        name: cfg for name, cfg in (wae_cfg or {}).get('chats', {}).items()
        if cfg['chat_id'] and cfg['SEQUENCE']
    }
    if not chats and not wae_chats:
        logger.warning("Сканер: не задан ни один CHAT_*_CHAT_ID / WAE_*_CHAT_ID, "
                       "сканер не запущен")
        return

    mintime = max(5, int(scan_cfg['MINTIME']))
    logger.info("Сканер запущен: свечные чаты %s, WAE-чаты %s, интервал %sс",
                list(chats) or '—', list(wae_chats) or '—', mintime)

    while True:
        exchange = ccxt.bybit({
            # Троттлер ccxt выключен намеренно: он сериализует запросы и даёт
            # ~10 req/s. Темп держит наш RateLimiter (REQUESTS_PER_SECOND),
            # который в 4 раза быстрее и всё равно втрое ниже лимита Bybit.
            'enableRateLimit': False,
            'options': {'defaultType': 'swap'},
        })
        cycle = 0
        try:
            while True:
                started = time.monotonic()
                try:
                    await exchange.load_markets(reload=(cycle % MARKETS_RELOAD_EVERY == 0))
                    queued = await scan_once(exchange, chats, scan_cfg, out_queue,
                                             wae_chats=wae_chats, wae_cfg=wae_cfg)
                    logger.info("Сканер: цикл #%s завершён за %.1fс, сигналов в очередь: %s",
                                cycle, time.monotonic() - started, queued)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception("Сканер: ошибка в цикле сканирования: %s", e)
                cycle += 1
                await asyncio.sleep(max(1.0, mintime - (time.monotonic() - started)))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Сканер: критическая ошибка, перезапуск через 60с: %s", e)
            await asyncio.sleep(60)
        finally:
            try:
                await exchange.close()
            except Exception:
                pass
