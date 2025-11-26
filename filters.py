import asyncio, logging
import time
import pandas as pd
import ccxt.async_support as ccxt
from utils import retry_sleep, now_ts
import pandas_ta as ta

logger = logging.getLogger("filters")

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
        print(f"Ошибка в check_volume_sma_filter: {e}")
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

async def passes_all_filters(pair, timeframe_cfg, min_volume_usd, exchange, is_AB, alltime=None, lst_all=None, colour=None, power = None, ema_timfraim=None, rsi_cfg=None,i=1):
    """
    timeframe_cfg = {"EMA1":10, "EMA2":50, "threshold_pct":2.5}
    """
    vol = await fetch_24h_volume_usd(exchange, pair)
    # pair = f'{pair}:USDT'
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
        rsi = await rsi_check(exchange, pair, rsi_cfg['timeframe'])
        if rsi < rsi_cfg['treshold']:
            return False, {"vol": 0, "ema": 0}
        return True, {"volume": vol, "ema": ema_res}
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
                if all_match:
                    # Сделать здесь проверку на ema(так же сделать обработку ema в конфиге и импорт в main файле, чтобы закинуть сюда потом это
                    ema_res = await compute_ema_deviation_from_ohlcv(exchange, pair, ema_timfraim['timefraim'],
                                                                     ema_timfraim['EMA1'])
                    if ema_res is None:
                        return False
                    if ema_res["deviation_pct"] < ema_timfraim['threshold_pct']:
                        logger.info("%s rejected by ema deviation: %.2f%% < %.2f%%", pair, ema_res["deviation_pct"], ema_timfraim['threshold_pct'])
                        return False
                    rsi = await rsi_check(exchange, pair, rsi_cfg['timeframe'])
                    if rsi < rsi_cfg['treshold']:
                        return False
                    return True
                else:
                    return False
            else:
                # print(f'МЕНЬШЕ {pair}: {lst_res}')
                return False
        # else:
        #     print(f'Не одна длина в filtrs')
        #     return False
        except Exception as e:
            if i == 1:
                pair2 = pair.split(':')[0]
                await passes_all_filters(pair2, timeframe_cfg, min_volume_usd, exchange, is_AB, alltime, lst_all, colour, power, ema_timfraim, rsi_cfg,2)
            if "bybit does not have market symbol" in str(e) and i == 2:
                return False



async def main():
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        })
    t1 = time.time()
    ok = await passes_all_filters("DOGE/USDT", '4h', 1000, exchange, False, 3, [20, 100, 1], "SELL", 1)
    print(f'3 {ok}')
    # print(f'RES: {t, l}\n{time.time() - t1}')
    await exchange.close()
if __name__ == "__main__":
    asyncio.run(main())
