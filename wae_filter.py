import numpy as np


# ============================================================================
# Вспомогательные функции (без изменений)
# ============================================================================

def calc_ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    k = 2.0 / (period + 1)
    start = 0
    while start < len(series) and np.isnan(series[start]):
        start += 1
    if start >= len(series):
        return result
    result[start] = series[start]
    for i in range(start + 1, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def calc_rma(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    k = 1.0 / period
    start = period - 1
    if len(series) < period:
        return result
    result[start] = np.mean(series[:period])
    for i in range(start + 1, len(series)):
        if not np.isnan(series[i]):
            result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def calc_sma(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        result[i] = np.mean(series[i - period + 1:i + 1])
    return result


def calc_std(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        result[i] = np.std(series[i - period + 1:i + 1], ddof=0)
    return result


# ============================================================================
# Ядро WAE (без изменений)
# ============================================================================

def wae_v2(
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        sensitivity: int = 150,
        fast_length: int = 20,
        slow_length: int = 40,
        channel_length: int = 20,
        mult: float = 2.0,
        dead_zone_atr_period: int = 100,
        dead_zone_multiplier: float = 3.7,
) -> dict:
    n = len(close)
    fast_ma   = calc_ema(close, fast_length)
    slow_ma   = calc_ema(close, slow_length)
    macd_line = fast_ma - slow_ma

    t1 = np.full(n, np.nan)
    for i in range(1, n):
        if not np.isnan(macd_line[i]) and not np.isnan(macd_line[i - 1]):
            t1[i] = (macd_line[i] - macd_line[i - 1]) * sensitivity

    bb_basis = calc_sma(close, channel_length)
    bb_std   = calc_std(close, channel_length)
    e1       = (bb_basis + mult * bb_std) - (bb_basis - mult * bb_std)

    tr    = np.full(n, np.nan)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )

    dead_zone  = calc_rma(tr, dead_zone_atr_period) * dead_zone_multiplier
    trend_up   = np.where(t1 >= 0, t1, 0.0)
    trend_down = np.where(t1 < 0, -t1, 0.0)

    return {
        't1': t1,
        'trend_up':   trend_up,
        'trend_down': trend_down,
        'e1':         e1,
        'dead_zone':  dead_zone,
        'macd_line':  macd_line,
    }


# ============================================================================
# НОВОЕ: определение цвета одного бара
# ============================================================================

def bar_color(trend_up_val: float, trend_down_val: float) -> int:
    return "BUY" if trend_up_val >= trend_down_val else "SELL"


# ============================================================================
# НОВОЕ: проверка последовательности + отрыв от explosion line
# ============================================================================

def check_sequence(
    wae: dict,
    sequence: list[int],
) -> tuple[bool, dict]:
    n = len(sequence)
    trend_up = wae['trend_up']
    trend_down = wae['trend_down']
    e1 = wae['e1']

    # Проверяем все бары последовательности слева направо
    for j, expected_color in enumerate(sequence):
        # j=0 → самый старый бар -(n+1),  j=n-1 → последний закрытый -2
        idx    = -(n - j + 0)
        actual = bar_color(float(trend_up[idx]), float(trend_down[idx]))
        # print(f'ID: {idx} | {actual} {expected_color}')
        last_color = list(expected_color.keys())[0]
        if actual != last_color:
            return False, {"reason": f'wrong colour {idx}'}

        tu_last  = float(trend_up[idx])
        td_last  = float(trend_down[idx])
        e1_last  = float(e1[idx])

        # Считаем отрыв от explosion line для нужной стороны
        histogram_val = tu_last if last_color == "BUY" else td_last
        if e1_last == 0:
            return False, {"reason": 'e1 == 0'}

        deviation_pct = ((histogram_val - e1_last) / e1_last) * 100
        min_histogram = int(expected_color.get(last_color))
        # print(f'{idx}: {deviation_pct}% | {min_histogram}')
        if deviation_pct < min_histogram:
            # print(f'Res<min_Amount : {deviation_pct}%')
            return False, {"reason": f'deviation {deviation_pct}<{min_histogram}'}
    return True, {
        'wae_signal': last_color,
        'sequence': sequence,
        'trend_up': round(tu_last, 6),
        'trend_down': round(td_last, 6),
        'explosion_line': round(e1_last, 6),
        'deviation_pct': round(deviation_pct, 4),
        'sequence_matched': True,
    }


# ============================================================================
# fetch_wae (незначительные изменения: limit теперь учитывает длину sequence)
# ============================================================================

async def fetch_wae(exchange, symbol: str, timeframe: str,
                    limit: int = 200, **wae_params):
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 101:
            return None

        high  = np.array([c[2] for c in ohlcv], dtype=float)
        low   = np.array([c[3] for c in ohlcv], dtype=float)
        close = np.array([c[4] for c in ohlcv], dtype=float)

        wae = wae_v2(high, low, close, **wae_params)

        return {
            'symbol':    symbol,
            'timeframe': timeframe,
            'wae':       wae,
        }
    except Exception as e:
        return None


# ============================================================================
# passes_wae_filter — два режима: sequence и классический
# ============================================================================

async def passes_wae_filter(
    exchange,
    symbol: str,
    timeframe: str,
    require: str = 'buy',
    sequence = None,
) -> tuple[bool, dict]:
    extra  = len(sequence) + 5 if sequence else 5
    limit  = max(200, 150 + extra)

    result = await fetch_wae(exchange, symbol, timeframe, limit=limit)
    if not result:
        return False, {'reason': 'not fetch'}

    wae = result['wae']

    # --- SEQUENCE MODE ---
    if sequence is not None:
        return check_sequence(wae, sequence)

    # --- CLASSIC MODE ---
    trend_up   = wae['trend_up']
    trend_down = wae['trend_down']
    e1         = wae['e1']

    tu = float(trend_up[-1])
    td = float(trend_down[-1])
    e1_v = float(e1[-1])

    if e1_v == 0:
        return False, {}
    min_histogram = 0
    if require == 'buy':
        res    = ((tu - e1_v) / e1_v) * 100
        passed = res >= min_histogram
    elif require == 'sell':
        res    = ((td - e1_v) / e1_v) * 100
        passed = res >= min_histogram
    elif require == 'any_above_deadzone':
        res    = max(((tu - e1_v) / e1_v) * 100, ((td - e1_v) / e1_v) * 100)
        passed = res >= min_histogram
    else:
        return False, {'reason': 'not buy/sell'}

    if passed:
        return True, {
            'wae_signal': require,
            'trend_up': round(tu, 6),
            'trend_down': round(td, 6),
            'explosion_line': round(e1_v, 6),
            'deviation_pct':  round(res, 4),
        }

    return False, {'reason': f"not passed {res}"}
