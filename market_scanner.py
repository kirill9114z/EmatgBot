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
import re
import time

import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta_classic as ta

logger = logging.getLogger("market_scanner")

# Сколько свечей тянем на пару: с запасом для RSI(14) и для кружков PERIOD_CANDLES.
OHLCV_LIMIT = 200
# Одновременных запросов к бирже. Выше — быстрее, но рискуем словить rate limit.
FETCH_CONCURRENCY = 20
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


async def _fetch_ohlcv(exchange, sem, symbol, timeframe, limit):
    """Свечи по одной паре. Ошибка одной пары не должна валить весь скан."""
    async with sem:
        try:
            return await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            logger.debug("OHLCV %s %s: %s", symbol, timeframe, e)
            return None


async def _fetch_ohlcv_map(exchange, sem, symbols, timeframe, limit):
    """{symbol: ohlcv} для списка пар на одном таймфрейме."""
    rows = await asyncio.gather(
        *[_fetch_ohlcv(exchange, sem, s, timeframe, limit) for s in symbols]
    )
    return {s: r for s, r in zip(symbols, rows) if r}


def _ticker_volume(ticker):
    """Суточный оборот в USDT из тикера ccxt."""
    volume = ticker.get('quoteVolume')
    if volume is None:
        volume = (ticker.get('info') or {}).get('turnover24h')
    try:
        return float(volume) if volume is not None else None
    except (TypeError, ValueError):
        return None


async def select_symbols(exchange, min_volume):
    """Бессрочные USDT-фьючерсы с суточным оборотом от min_volume."""
    universe = [
        symbol for symbol, market in exchange.markets.items()
        if market.get('swap')
        and market.get('linear')
        and market.get('settle') == 'USDT'
        and market.get('active', True)
    ]
    if not universe:
        return []

    # Один запрос на всю категорию вместо запроса на каждую пару.
    try:
        tickers = await exchange.fetch_tickers(params={'category': 'linear'})
    except Exception as e:
        logger.warning("fetch_tickers(category=linear) не сработал (%s), пробуем по списку", e)
        tickers = await exchange.fetch_tickers(universe)

    selected = []
    for symbol in universe:
        ticker = tickers.get(symbol)
        if not ticker:
            continue
        volume = _ticker_volume(ticker)
        if volume is not None and volume >= min_volume:
            selected.append(symbol)
    return selected


async def fetch_period_change(exchange, sem, symbol, period_info):
    """Изменение цены за информационный период, например за 15D."""
    parsed = parse_period_info(period_info)
    if not parsed:
        return None
    count, timeframe = parsed
    ohlcv = await _fetch_ohlcv(exchange, sem, symbol, timeframe, count + 1)
    if not ohlcv or len(ohlcv) < 2:
        return None
    first_close, last_close = float(ohlcv[0][4]), float(ohlcv[-1][4])
    if first_close == 0:
        return None
    return (last_close - first_close) / first_close * 100


async def scan_once(exchange, chats, scan_cfg, out_queue):
    """Один полный проход по рынку. Возвращает число отправленных сигналов."""
    symbols = await select_symbols(exchange, scan_cfg['VOLUME'])
    if not symbols:
        logger.warning("Сканер: ни одна пара не прошла фильтр по обороту")
        return 0
    logger.info("Сканер: %s пар прошли фильтр по обороту", len(symbols))

    sem = asyncio.Semaphore(FETCH_CONCURRENCY)

    # Свечи тянем по одному разу на таймфрейм и переиспользуем для всех чатов:
    # если у CHAT_G и CHAT_H одинаковый таймфрейм — это вдвое меньше запросов.
    candles_by_tf = {}
    for timeframe in {cfg['CANDLE_TIMEFRAME'] for cfg in chats.values()}:
        candles_by_tf[timeframe] = await _fetch_ohlcv_map(
            exchange, sem, symbols, timeframe, OHLCV_LIMIT
        )

    # Информационный период тянем только для прошедших пар и кэшируем на цикл.
    period_cache = {}
    queued = 0

    for chat_name, chat_cfg in chats.items():
        candles = candles_by_tf.get(chat_cfg['CANDLE_TIMEFRAME'], {})
        passed = 0
        for symbol, ohlcv in candles.items():
            try:
                payload = passes_scanner_filters(chat_cfg, ohlcv)
            except Exception as e:
                logger.debug("Фильтры %s для %s: %s", chat_name, symbol, e)
                continue
            if not payload:
                continue

            cache_key = (symbol, chat_cfg['PERIOD_INFO'])
            if cache_key not in period_cache:
                period_cache[cache_key] = await fetch_period_change(
                    exchange, sem, symbol, chat_cfg['PERIOD_INFO']
                )
            payload['period_change'] = period_cache[cache_key]

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

    return queued


async def scanner_loop(out_queue, scan_cfg):
    """Бесконечный цикл сканирования. Сам переживает падения биржи/сети."""
    chats = {name: cfg for name, cfg in scan_cfg['chats'].items() if cfg['chat_id']}
    if not chats:
        logger.warning("Сканер: не задан ни один CHAT_*_CHAT_ID, сканер не запущен")
        return

    mintime = max(5, int(scan_cfg['MINTIME']))
    logger.info("Сканер запущен: чаты %s, интервал %sс", list(chats), mintime)

    while True:
        exchange = ccxt.bybit({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
        })
        cycle = 0
        try:
            while True:
                started = time.monotonic()
                try:
                    await exchange.load_markets(reload=(cycle % MARKETS_RELOAD_EVERY == 0))
                    queued = await scan_once(exchange, chats, scan_cfg, out_queue)
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
