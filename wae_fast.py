"""Быстрый Waddah Attar Explosion V2 — численно идентичен wae_filter.wae_v2.

Зачем отдельный модуль
----------------------
`wae_filter.py` перенесён из старой версии бота побайтово и остаётся эталоном:
менять его нельзя, по нему сверяется поведение. Но он написан на чистых
python-циклах, а сканеру нужно считать индикатор по ~500 парам за цикл, то есть
несколько раз в минуту. Здесь те же формулы, переписанные на векторные операции.

Что именно ускорено
-------------------
* `calc_sma` / `calc_std` — были O(n·period): по одному вызову np.mean/np.std на
  каждое окно. Стали одним вызовом pandas .rolling() на всю серию.
* `t1` и `tr` — были python-циклы, стали numpy-выражениями.
* `calc_ema` / `calc_rma` — рекуррентные, векторизации не поддаются, но заменены
  на pandas .ewm(adjust=False), который считает ТУ ЖЕ рекурсию в C.

Почему результат совпадает бит в бит
------------------------------------
* ewm(alpha=2/(p+1), adjust=False) разворачивается в y[i] = k·x[i] + (1-k)·y[i-1]
  с y[0] = x[0] — ровно то, что делает calc_ema.
* calc_rma — та же рекурсия с k = 1/period, но стартует не с первого элемента, а
  со среднего первых `period` значений. Подставляем это среднее в начало среза и
  запускаем ewm(alpha=1/period) от него.
* e1 считается тем же выражением (basis + mult·std) - (basis - mult·std), а не
  упрощённым 2·mult·std: упрощение математически равно, но даёт другой результат
  в последних битах мантиссы.

Эквивалентность проверяется скриптом verify_wae.py на реальных данных Bybit.
Входы с NaN (в норме не встречаются) отдаются эталонной реализации.
"""
import numpy as np
import pandas as pd

from wae_filter import wae_v2

# Минимум свечей, ниже которого dead_zone(100) не успевает выйти из NaN.
# Значение взято из wae_filter.fetch_wae.
MIN_CANDLES = 101


def _has_nan(*arrays):
    return any(np.isnan(a).any() for a in arrays)


def calc_ema_fast(series: np.ndarray, period: int) -> np.ndarray:
    """EMA. Эквивалент wae_filter.calc_ema для серий без NaN."""
    if len(series) == 0:
        return np.full(0, np.nan)
    k = 2.0 / (period + 1)
    return pd.Series(series).ewm(alpha=k, adjust=False).mean().to_numpy()


def calc_rma_fast(series: np.ndarray, period: int) -> np.ndarray:
    """RMA (сглаживание Уайлдера). Эквивалент wae_filter.calc_rma."""
    n = len(series)
    result = np.full(n, np.nan)
    if n < period:
        return result
    start = period - 1
    # Затравка — среднее первых period значений, дальше обычная рекурсия.
    seeded = series[start:].copy()
    seeded[0] = np.mean(series[:period])
    result[start:] = pd.Series(seeded).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    return result


def calc_sma_fast(series: np.ndarray, period: int) -> np.ndarray:
    """SMA. Эквивалент wae_filter.calc_sma."""
    return pd.Series(series).rolling(period).mean().to_numpy()


def calc_std_fast(series: np.ndarray, period: int) -> np.ndarray:
    """Стандартное отклонение популяции (ddof=0). Эквивалент wae_filter.calc_std."""
    return pd.Series(series).rolling(period).std(ddof=0).to_numpy()


def wae_v2_fast(
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
    """Векторный WAE V2. Сигнатура и структура ответа как у wae_filter.wae_v2."""
    n = len(close)
    if n == 0:
        return wae_v2(high, low, close, sensitivity, fast_length, slow_length,
                      channel_length, mult, dead_zone_atr_period, dead_zone_multiplier)

    # NaN во входных данных — редкий случай (битая свеча). Считаем эталоном,
    # чтобы не расходиться в обработке дырок.
    if _has_nan(high, low, close):
        return wae_v2(high, low, close, sensitivity, fast_length, slow_length,
                      channel_length, mult, dead_zone_atr_period, dead_zone_multiplier)

    fast_ma = calc_ema_fast(close, fast_length)
    slow_ma = calc_ema_fast(close, slow_length)
    macd_line = fast_ma - slow_ma

    # t1[i] = (macd[i] - macd[i-1]) * sensitivity, t1[0] остаётся NaN.
    t1 = np.full(n, np.nan)
    if n > 1:
        t1[1:] = np.diff(macd_line) * sensitivity

    bb_basis = calc_sma_fast(close, channel_length)
    bb_std = calc_std_fast(close, channel_length)
    e1 = (bb_basis + mult * bb_std) - (bb_basis - mult * bb_std)

    # True Range: первый бар — размах свечи, дальше максимум из трёх величин.
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    if n > 1:
        prev_close = close[:-1]
        tr[1:] = np.maximum.reduce([
            high[1:] - low[1:],
            np.abs(high[1:] - prev_close),
            np.abs(low[1:] - prev_close),
        ])

    dead_zone = calc_rma_fast(tr, dead_zone_atr_period) * dead_zone_multiplier
    trend_up = np.where(t1 >= 0, t1, 0.0)
    trend_down = np.where(t1 < 0, -t1, 0.0)

    return {
        't1': t1,
        'trend_up': trend_up,
        'trend_down': trend_down,
        'e1': e1,
        'dead_zone': dead_zone,
        'macd_line': macd_line,
    }


def wae_from_ohlcv(ohlcv, **wae_params):
    """WAE по сырым свечам ccxt. None, если данных не хватает.

    Порог в 101 свечу взят из wae_filter.fetch_wae — сохраняем как есть, иначе
    dead_zone на периоде 100 не успевает выйти из NaN.
    """
    if not ohlcv or len(ohlcv) < MIN_CANDLES:
        return None
    rows = np.asarray(ohlcv, dtype=float)
    return wae_v2_fast(rows[:, 2], rows[:, 3], rows[:, 4], **wae_params)


# ===========================================================================
# Пакетный расчёт: весь рынок одной матрицей
# ===========================================================================
#
# Даже векторная версия тратит ~1 мс на пару, и почти всё это — накладные
# расходы pandas на создание Series (их пять штук на пару). При 500 парах это
# полсекунды на таймфрейм на пустом месте.
#
# Здесь те же операции выполняются над матрицей (свечи × пары): pandas умеет
# .ewm() и .rolling() поколоночно, поэтому один вызов обсчитывает сразу весь
# рынок. Накладные расходы делятся на число пар и становятся незаметны.

def wae_v2_batch(
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
    """WAE сразу по многим парам. Массивы имеют форму (свечи, пары).

    Возвращает те же поля, что wae_v2, но каждое — матрица; столбец j отвечает
    паре j. Порядок вычислений совпадает с одиночной версией, поэтому и
    результат тот же.
    """
    n_bars = close.shape[0]

    fast_ma = pd.DataFrame(close).ewm(alpha=2.0 / (fast_length + 1), adjust=False).mean().to_numpy()
    slow_ma = pd.DataFrame(close).ewm(alpha=2.0 / (slow_length + 1), adjust=False).mean().to_numpy()
    macd_line = fast_ma - slow_ma

    t1 = np.full_like(close, np.nan)
    if n_bars > 1:
        t1[1:] = np.diff(macd_line, axis=0) * sensitivity

    close_df = pd.DataFrame(close)
    bb_basis = close_df.rolling(channel_length).mean().to_numpy()
    bb_std = close_df.rolling(channel_length).std(ddof=0).to_numpy()
    e1 = (bb_basis + mult * bb_std) - (bb_basis - mult * bb_std)

    tr = np.empty_like(close)
    tr[0] = high[0] - low[0]
    if n_bars > 1:
        prev_close = close[:-1]
        tr[1:] = np.maximum.reduce([
            high[1:] - low[1:],
            np.abs(high[1:] - prev_close),
            np.abs(low[1:] - prev_close),
        ])

    dead_zone = np.full_like(close, np.nan)
    if n_bars >= dead_zone_atr_period:
        start = dead_zone_atr_period - 1
        seeded = tr[start:].copy()
        seeded[0] = tr[:dead_zone_atr_period].mean(axis=0)
        dead_zone[start:] = pd.DataFrame(seeded).ewm(
            alpha=1.0 / dead_zone_atr_period, adjust=False
        ).mean().to_numpy()
    dead_zone *= dead_zone_multiplier

    return {
        't1': t1,
        'trend_up': np.where(t1 >= 0, t1, 0.0),
        'trend_down': np.where(t1 < 0, -t1, 0.0),
        'e1': e1,
        'dead_zone': dead_zone,
        'macd_line': macd_line,
    }


def compute_wae_map(candles_map, **wae_params) -> dict:
    """{символ: ohlcv} -> {символ: wae}. Считает весь рынок пакетами.

    Пары с разной длиной истории (свежие листинги отдают меньше свечей) режутся
    на группы одинаковой длины — матрица должна быть прямоугольной. На практике
    групп получается две-три, то есть два-три пакетных вызова на весь рынок.
    Пары с NaN в свечах откладываются на эталонный путь поштучно.
    """
    by_length = {}
    fallback = []
    for symbol, ohlcv in candles_map.items():
        if not ohlcv or len(ohlcv) < MIN_CANDLES:
            continue
        rows = np.asarray(ohlcv, dtype=float)
        if np.isnan(rows[:, 2:5]).any():
            fallback.append((symbol, rows))
            continue
        by_length.setdefault(len(ohlcv), []).append((symbol, rows))

    result = {}
    for group in by_length.values():
        symbols = [s for s, _ in group]
        high = np.column_stack([r[:, 2] for _, r in group])
        low = np.column_stack([r[:, 3] for _, r in group])
        close = np.column_stack([r[:, 4] for _, r in group])

        batch = wae_v2_batch(high, low, close, **wae_params)
        for j, symbol in enumerate(symbols):
            result[symbol] = {field: values[:, j] for field, values in batch.items()}

    for symbol, rows in fallback:
        result[symbol] = wae_v2_fast(rows[:, 2], rows[:, 3], rows[:, 4], **wae_params)

    return result
