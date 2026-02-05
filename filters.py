import asyncio, logging
import time
import pandas as pd
import ccxt.async_support as ccxt
from utils import retry_sleep, now_ts
# import pandas_ta as ta
import pandas_ta_classic as ta
from typing import Dict

logger = logging.getLogger("filters")

ALL_PIVOT_LEVELS = ['S5', 'S4', 'S3', 'S2', 'S1', 'PP', 'R1', 'R2', 'R3', 'R4', 'R5']
R_LEVEL = ['R1', 'R2', 'R3', 'R4', 'R5']
S_LEVEL = ['S5', 'S4', 'S3', 'S2', 'S1']
AUTO_TIMEFRAME_MAP = {
        '1s': '1d', '5s': '1d', '15s': '1d', '30s': '1d',
        '1m': '1d', '3m': '1d', '5m': '1d', '15m': '1d', '30m': '1d',
        '1h': '1d', '2h': '1d', '4h': '1d', '6h': '1d', '12h': '1d',
        '1d': '1w',
        '1w': '1M',
        '1M': '3M',
    }

TIMEFRAIM_CHART = {
        "5m": "1h",
        "15m": "1h",
        "30m": "1d",
        "1h": "1d",
        "4h": "1d",
        "1d": "1w",
    }


def calculate_pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
    pp = (high + low + close) / 3
    range_value = high - low

    # базовые уровни (совпадают с UI)
    r1 = (2 * pp) - low
    r2 = pp + range_value
    r3 = high + 2 * (pp - low)

    s1 = (2 * pp) - high
    s2 = pp - range_value
    s3 = low - 2 * (high - pp)

    # ВАЖНО: расширение уровней 4/5 как на UI (равный шаг)
    dr = r3 - r2  # шаг вверх
    ds = s2 - s3  # шаг вниз

    r4 = r3 + dr
    r5 = r4 + dr

    s4 = s3 - ds
    s5 = s4 - ds

    return {
        'PP': pp,
        'R1': r1, 'R2': r2, 'R3': r3, 'R4': r4, 'R5': r5,
        'S1': s1, 'S2': s2, 'S3': s3, 'S4': s4, 'S5': s5,
        'range': range_value,
        'source_high': high,
        'source_low': low,
        'source_close': close
    }

@retry_sleep(tries=3)
async def fetch_ohlcv(exchange, pair, timeframe, limit=200):
    try:
        return await exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
    except Exception as e:
        if "bybit does not have market symbol" in str(e):
            return False


async def compute_ema_deviation_from_ohlcv(exchange, pair, timeframe, ema1):
    try:
        ohlcv = await fetch_ohlcv(exchange, pair, timeframe, limit=5000)
        if ohlcv == False:
            pair2 = pair.split(":")[0]
            ohlcv = await fetch_ohlcv(exchange, pair2, timeframe, limit=5000)

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # if len(df) < int(ema1) + 5:
        #     return None
        ema_short = df['close'].ewm(span=ema1, adjust=False).mean().iloc[-1]
        current_price = df['close'].iloc[-1]
        deviation = ((current_price - ema_short) / ema_short) * 100
        return {
            "ema_short": float(ema_short),
            "current_price": float(current_price),
            "deviation_pct": float(deviation)
        }
    except Exception as e:
        if "bybit does not have market symbol" in str(e):
            print(f'NOT SYMB {pair}')
            return None
        logger.error("EMA calculation failed for %s: %s", pair, e)
        return None

@retry_sleep(tries=3)
async def fetch_24h_volume_usd(exchange, pair):
    # Try fetch_ticker first
    # symbol = pair.replace("/", "")
    symbol = pair
    try:
        t = await exchange.fetch_ticker(symbol)
        # Many exchanges return 'quoteVolume' or 'baseVolume'
        quote_v = t.get('quoteVolume') or t.get('info', {}).get('quoteVolume')
        base_v = t.get('baseVolume') or t.get('info', {}).get('baseVolume')
        last = t.get('last') or (t.get('info', {}).get('lastPrice') if t.get('info') else None)
        if quote_v:
            return float(quote_v)
        elif base_v and last:
            return float(base_v) * float(last)
    except Exception:
        pass

    # Fallback: compute from OHLCV last 24h (approx) depending on timeframe
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, '1h', limit=24)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        avg_price = df['close'].mean()
        vol = df['volume'].sum() * avg_price
        return float(vol)
    except Exception as e:
        if "bybit does not have market symbol" in str(e):
            return False
        # logger.exception("Volume fetch failed for %s: %s", pair, e)
        return 0.0

async def one_sma_filter(
            candles,
            df,
            i,
    ):
    try:
        # Загружаем свечи
        if len(candles) < 12:
            return False, None

        # Создаем DataFrame

        # ПРАВИЛЬНЫЙ расчет SMA9 - используем window=9!
        df['vol_ma_base'] = df['volume'].rolling(window=20, min_periods=20).mean()

        # Шаг 2: сглаживание (например, smoothing_length = 9)
        # Применим скользящее среднее к уже посчитанному MA
        df['volume_sma9'] = df['vol_ma_base'].rolling(window=9,
                                                      min_periods=9).mean()

        # Убедимся, что у нас достаточно данных
        if len(df) < 11 or pd.isna(df['volume_sma9'].iloc[-1]):
            # print("Недостаточно данных для расчета SMA9")
            return False, None

        # Получаем свечи
        current_candle = df.iloc[-i]

        # Получаем SMA9 значения
        current_sma9 = df['volume_sma9'].iloc[-i]

        # Рассчитываем процент превышения
        current_volume_percent = ((current_candle['volume'] - current_sma9) / current_sma9) * 100
        current_candle_green = current_candle['close'] >= current_candle['open']
        info = {
            'volume_percent': current_volume_percent,
            'candle_color': 'BUY' if current_candle_green else 'SELL',
        }
        return info


    except Exception as e:
        return False, None


async def rsi_check(exchange, pair, timfraim):
    ohlcv = await fetch_ohlcv(exchange, pair, timfraim, 5000)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['close'] = df['close'].astype(float)

    # Расчет RSI с помощью pandas_ta
    df['rsi'] = ta.rsi(df['close'], length=14)
    current_rsi = df['rsi'].iloc[-1]
    return current_rsi

async def check_volume_sma_filter(
            timeframe: str,
            symbol: str,
            exchange,
            volume_percent_threshold: float = 10.0
    ):
        try:
            # Загружаем свечи
            candles = await exchange.fetch_ohlcv(symbol, timeframe, limit=50)
            if len(candles) < 12:
                return False, None

            # Создаем DataFrame
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # ПРАВИЛЬНЫЙ расчет SMA9 - используем window=9!
            df['vol_ma_base'] = df['volume'].rolling(window=20, min_periods=20).mean()

            # Шаг 2: сглаживание (например, smoothing_length = 9)
            # Применим скользящее среднее к уже посчитанному MA
            df['volume_sma9'] = df['vol_ma_base'].rolling(window=9,
                                                              min_periods=9).mean()

            # Убедимся, что у нас достаточно данных
            if len(df) < 11 or pd.isna(df['volume_sma9'].iloc[-1]):
                print("Недостаточно данных для расчета SMA9")
                return False, None

            # Получаем свечи
            current_candle = df.iloc[-1]
            prev_candle = df.iloc[-2]

            # Получаем SMA9 значения
            current_sma9 = df['volume_sma9'].iloc[-1]
            prev_sma9 = df['volume_sma9'].iloc[-2]

            # Рассчитываем процент превышения
            current_volume_percent = ((current_candle['volume'] - current_sma9) / current_sma9) * 100
            prev_volume_percent = ((prev_candle['volume'] - prev_sma9) / prev_sma9) * 100

            current_volume_condition = current_volume_percent >= volume_percent_threshold
            prev_volume_condition = prev_volume_percent >= volume_percent_threshold

            # Определяем цвет свечей
            current_candle_green = current_candle['close'] >= current_candle['open']
            prev_candle_green = prev_candle['close'] >= prev_candle['open']
            same_color = current_candle_green == prev_candle_green
            #
            # print(f'\nТЕКУЩАЯ СВЕЧА:')
            # print(f'  Объем: {current_candle["volume"]:.2f}')
            # print(f'  SMA9: {current_sma9:.2f}')
            # print(f'  Процент: {current_volume_percent:.2f}%')
            # print(f'ПРЕДЫДУЩАЯ СВЕЧА:')
            # print(f'  Объем: {prev_candle["volume"]:.2f}')
            # print(f'  SMA9: {prev_sma9:.2f}')
            # print(f'  Процент: {prev_volume_percent:.2f}%')
            # print(
            #     f'Цвета: текущая - {"зеленая" if current_candle_green else "красная"}, предыдущая - {"зеленая" if prev_candle_green else "красная"}')

            # Проверяем все условия
            conditions_met = all([
                current_volume_condition,
                prev_volume_condition,
                same_color
            ])

            if conditions_met:
                info = {
                    'current_volume_percent': current_volume_percent,
                    'current_sma9': current_sma9,
                    'prev_volume': prev_candle['volume'],
                    'prev_volume_percent': prev_volume_percent,
                    'prev_sma9': prev_sma9,
                    'current_candle_color': 'green' if current_candle_green else 'red',
                    'prev_candle_color': 'green' if prev_candle_green else 'red',
                    'volume_threshold': volume_percent_threshold,
                    'current_close': current_candle['close'],
                    'prev_close': prev_candle['close'],
                    'timestamp': current_candle['timestamp']
                }
                return True, info
            else:
                debug_info = {
                    'timeframe': timeframe,
                    'symbol': symbol,
                    'current_volume_percent': current_volume_percent,
                    'prev_volume_percent': prev_volume_percent,
                    'same_color': same_color,
                    'conditions_met': {
                        'current_volume': current_volume_condition,
                        'prev_volume': prev_volume_condition,
                        'same_color': same_color
                    }
                }
                return False, debug_info

        except Exception as e:
            print(f"Ошибка в check_volume_sma_filter: {e}")
            return False, None


async def check_level(exchange,
               symbol: str,
               target_level: str,
               pivot_timeframe: str,
               sign: str,
               threshold_min: float = -1.0,
               threshold_max: float = 1.0,
               ) -> Dict:
    if target_level not in ALL_PIVOT_LEVELS:
        print(f'Нам не подашел {target_level}')
        return {
            'success': False,
            'error': f'Неверная метка. Доступные: {", ".join(ALL_PIVOT_LEVELS)}'
        }
    try:
        # Определяем таймфрейм для расчета

        # Получаем последние 2 свечи для расчета Pivot
        ohlcv = await exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=pivot_timeframe,
            limit=2
        )

        if len(ohlcv) < 2:
            return {
                'success': False,
                'error': 'Недостаточно данных для расчета Pivot'
            }

        # Рассчитываем Pivot на основе ПРЕДЫДУЩЕЙ завершенной свечи
        prev_candle = ohlcv[-2]
        high = prev_candle[2]
        low = prev_candle[3]
        close = prev_candle[4]

        pivots = calculate_pivot_points(high, low, close)
        # print(f'\n\n\nPIVOTS: {pivots}\n\n\n')
        # Получаем текущую цену (close текущей незакрытой свечи)
        current_price = ohlcv[-1][4]

        if current_price is None:
            return {
                'success': False,
                'error': 'Не удалось получить текущую цену'
            }

        # Получаем значение целевого уровня
        level_value = pivots[target_level]

        # Рассчитываем отклонение
        deviation = ((current_price - level_value) / level_value) * 100
        if level_value < 0:
            deviation *= -1
        if sign == '+':
            in_range = threshold_min <= deviation
        elif sign == '-':
            in_range = threshold_max >= deviation
        else:
            in_range = threshold_min <= deviation <= threshold_max
        return {
            'success': True,
            'pass_filter': in_range,
            'symbol': symbol,
            'target_level': target_level,
            'level_value': level_value,
            'current_price': current_price,
            'deviation_percent': round(deviation, 1),
            'threshold_min': threshold_min,
            'threshold_max': threshold_max,
            'in_range': in_range,
        }

    except Exception as e:
        return {
            'success': False,
            'error': f'Ошибка: {str(e)}'
        }


async def pivot_allchack(exchange, pair, lst_conf):
    valid_levels = []
    SOM = {
        "5m": "1d",
        "15m": "1d",
        "30m": "1w",
        "1h": "1w",
        "4h": "1w",
        "1d": "1M"
    }
    for level_name, configs in lst_conf.items():
        for config in configs:
            if level_name not in ALL_PIVOT_LEVELS:
                print(f"⚠️ Неверная метка: {level_name}")
                continue

            timeframe = config.get('time', '')
            thres = config.get('thres', 0)
            sign = config.get("sign", '')

            if timeframe not in AUTO_TIMEFRAME_MAP:
                print(f"⚠️ Неверный таймфрейм для {level_name}: {timeframe}")
                continue

            valid_levels.append({
                'level': level_name,
                'timeframe': timeframe,
                'thres': thres,
                "sign": sign
            })

    if not valid_levels:
        print("❌ Нет валидных меток для проверки")
        return []


    tf_groups = {}
    for level_info in valid_levels:
        tf = level_info['timeframe']
        if tf not in tf_groups:
            tf_groups[tf] = []
        tf_groups[tf].append(level_info)


    # Результаты
    passed_levels = []
    lst_success_tf = []


    for timeframe, levels_in_tf in tf_groups.items():
        # print(f"\n📊 Проверяем таймфрейм: {timeframe} ({len(levels_in_tf)} меток)")

        level_priority = {
            'R5': 5, 'R4': 4, 'R3': 3, 'R2': 2, 'R1': 1,
            'S5': 5, 'S4': 4, 'S3': 3, 'S2': 2, 'S1': 1
        }

        sorted_levels = sorted(
            levels_in_tf,
            key=lambda x: level_priority[x['level']],
            reverse=True  # от старшей к младшей
        )

        # lst_success_tf = []

        # Проверяем от старшей к младшей
        for level_info in sorted_levels:
            level_name = level_info['level']
            thres = level_info['thres']
            sign = level_info['sign']
            if timeframe in lst_success_tf:
                print(f'{timeframe}  | {lst_success_tf}')
                continue
            result = await check_level(
                exchange,
                symbol=pair,
                target_level=level_name,
                pivot_timeframe=SOM[timeframe],
                sign=sign,
                threshold_min=-thres,  # симметричный диапазон ±thres
                threshold_max=thres,

            )

            if result['success'] and result['pass_filter']:
                lst_success_tf.append(timeframe)
                # print(f"    ✅ ПРОЙДЕНО! deviation: {result['deviation_percent']:+.4f}%")
                passed_levels.append({
                    'level': level_name,
                    'timeframe': timeframe,
                    'deviation_percent': f"+{result['deviation_percent']}" if result['deviation_percent'] > 0 else result['deviation_percent'],
                    'level_value': result['level_value'],
                    'sign': sign
                })
                # Продолжаем проверять младшие (может быть несколько)
            else:
                dev = result.get('deviation_percent', None)
                if isinstance(dev, (int, float)):
                    print(f"❌ Не пройдено (deviation: {dev:+.4f}%)")
                else:
                    print(f"❌ Не пройдено (deviation: {dev})")

    # print(f'\n\n\n{passed_levels}\n\n\n')
    return passed_levels


async def passes_all_filters(pair, timeframe_cfg, min_volume_usd, exchange, is_AB, alltime=None, lst_all=None, colour=None, power = None, ema_timfraim=None, rsi_cfg=None, lst_cnf=None, i=1):
    """
    timeframe_cfg = {"EMA1":10, "EMA2":50, "threshold_pct":2.5}
    """
    vol = await fetch_24h_volume_usd(exchange, pair)
    if is_AB == True:
        if vol == False:
            pair2 = pair.split(':')[0]
            vol = await fetch_24h_volume_usd(exchange, pair2)
            if vol:
                if vol < min_volume_usd:
                    return False, {"reason":"volume", "volume": vol}
                else:
                    ema_res = await compute_ema_deviation_from_ohlcv(exchange, pair2, timeframe_cfg['timefraim'],
                                                                     timeframe_cfg['EMA1'])
                    # print(f"EMA2 {timeframe_cfg['timefraim']}: {ema_res} {vol} {pair2}")
                    if ema_res is None:
                        return False, {"reason": "ema_failed"}
                    if ema_res["deviation_pct"] < timeframe_cfg['threshold_pct']:
                        # logger.info("%s rejected by ema deviation: %.2f%% < %.2f%%", pair2, ema_res["deviation_pct"],
                        #             timeframe_cfg['threshold_pct'])
                        return False, {"reason": "ema_threshold", "deviation": ema_res["deviation_pct"]}
                    else:
                        if rsi_cfg['RSI'] == 1:
                            rsi = await rsi_check(exchange, pair, rsi_cfg['timefraim'])
                            if rsi < rsi_cfg['RSI_VOL']:
                                return False, {"vol": 0, "ema": 0}
                            return True, {"volume": vol, "ema": ema_res}
                        else:
                            return True, {"volume": vol, "ema": ema_res}
            else:
                return False, {"reason":"volume", "volume": vol}
        else:
            if vol < min_volume_usd:
                return False
        ema_res = await compute_ema_deviation_from_ohlcv(exchange, pair, timeframe_cfg['timefraim'],timeframe_cfg['EMA1'])
        # print(f"EMA {timeframe_cfg['timefraim']}: {ema_res} {vol}")
        if ema_res is None:
            return False, {"reason":"ema_failed"}
        if ema_res["deviation_pct"] < timeframe_cfg['threshold_pct']:
            # logger.info("%s rejected by ema deviation: %.2f%% < %.2f%%", pair, ema_res["deviation_pct"], timeframe_cfg['threshold_pct'])
            return False, {"reason":"ema_threshold", "deviation": ema_res["deviation_pct"]}
        if rsi_cfg['RSI'] == 1:
            rsi = await rsi_check(exchange, pair, rsi_cfg['timefraim'])
            if rsi < rsi_cfg['RSI_VOL']:
                return False, {"vol": 0, "ema": 0}
            return True, {"volume": vol, "ema": ema_res}
        else:
            return True, {"volume": vol, "ema": ema_res}

    elif is_AB == "Three":
        if vol == False:
            pair = pair.split(':')[0]
            vol = await fetch_24h_volume_usd(exchange, pair)
            if vol:
                if vol < min_volume_usd:
                    return False, 0
        else:
            if vol < min_volume_usd:
                return False, 0
        try:
            res = await pivot_allchack(exchange, pair, lst_cnf)
            if res:
                return True, res
            else:
                return False, 0
        except Exception as e:
            if i == 1:
                pair2 = pair.split(':')[0]
                await passes_all_filters(pair2, timeframe_cfg, min_volume_usd, exchange, is_AB, alltime, lst_all,
                                         colour, power, ema_timfraim, rsi_cfg, lst_cnf, 2)
            if "bybit does not have market symbol" in str(e) and i == 2:
                return False,  0
            else:
                return False, 0
    else:
        if vol == False:
            pair = pair.split(':')[0]
            vol = await fetch_24h_volume_usd(exchange, pair)
            if vol:
                if vol < min_volume_usd:
                    return False
        else:
            if vol < min_volume_usd:
                return False
        try:
            candles = await exchange.fetch_ohlcv(pair, timeframe_cfg, limit=50)
            if len(candles) < 12:
                return False
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            lst_res = [await one_sma_filter(candles, df, 1)]
            # lst_all.reverse()
            f = True
            # if len(lst_res) == len(lst_all):
            if float(lst_res[0]['volume_percent']) <= power or lst_res[0]['candle_color'] != colour:
                f = False
            if f:
                # print(f'ПРОШЕЛ SMA9: {pair} {lst_res} {power}')
                historical_results = []
                for offset, expected_color in enumerate(lst_all, start=2):
                    historical_info = await one_sma_filter(candles, df, offset)
                    if historical_info is None:
                        # print(f"Не удалось получить данные для свечи {offset}")
                        return False
                    historical_results.append(historical_info)

                # Сравниваем реальные цвета с ожидаемыми из lst_all
                all_match = all(historical_results[i]['candle_color'] == lst_all[i]for i in range(len(lst_all)))
                # print(f'Pair: {pair}: {all_match}')
                # if rsi_cfg['RSI'] == 1:
                #     rsi = await rsi_check(exchange, pair, rsi_cfg['timefraim'])
                #     print(f'{pair}: {rsi} ^ {rsi_cfg['RSI_VOL']} {rsi_cfg['timefraim']}  | {is_AB}')
                #     if rsi < rsi_cfg['RSI_VOL']:
                #         return False
                if all_match:
                    # Сделать здесь проверку на ema(так же сделать обработку ema в конфиге и импорт в main файле, чтобы закинуть сюда потом это
                    ema_res = await compute_ema_deviation_from_ohlcv(exchange, pair, ema_timfraim['timefraim'],
                                                                     ema_timfraim['EMA1'])
                    if ema_res is None:
                        return False
                    if ema_res["deviation_pct"] < ema_timfraim['threshold_pct']:
                        logger.info("%s rejected by ema deviation: %.2f%% < %.2f%%", pair, ema_res["deviation_pct"], ema_timfraim['threshold_pct'])
                        return False
                    if rsi_cfg['RSI'] == 1:
                        rsi = await rsi_check(exchange, pair, rsi_cfg['timefraim'])
                        if rsi < rsi_cfg['RSI_VOL']:
                            return False
                        return True
                    else:
                        return True
                else:
                    return False
            else:
                return False
        # else:
        #     print(f'Не одна длина в filtrs')
        #     return False
        except Exception as e:
            if i == 1:
                pair2 = pair.split(':')[0]
                await passes_all_filters(pair2, timeframe_cfg, min_volume_usd, exchange, is_AB, alltime, lst_all, colour, power, ema_timfraim, rsi_cfg,lst_cnf, 2)
            if "bybit does not have market symbol" in str(e) and i == 2:
                return False



async def main():
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        })

    lst_conf = {
        "R1": [{'time': '5m', 'thres': 20, 'sign': '+'}, {'time': '5m', 'thres': 0.5, 'sign': ''}],
        "R2": [{"time": "5m", "thres": 0.1, "sign": "+"}],
        "R3": [{"time": "30m", "thres": 0.01, "sign": "+"}],
        "R4": [{"time": "1d", "thres": 1, "sign": "+"}],
        "R5": [{"time": "1d", "thres": 2, "sign": "+"}]
    }
    res = await pivot_allchack(exchange, "SENT/USDT", lst_conf)
    # res = await pivot_allchack(exchange, "XAUT/USDT", lst_conf)
    print(f'res999: {res} ')
    await exchange.close()
if __name__ == "__main__":
    asyncio.run(main())
