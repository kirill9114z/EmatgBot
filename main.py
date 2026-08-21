import asyncio, json, os, sys, logging
from telethon_listener import start_telethon
from signal_parser import parse_raw_message
from filters import passes_all_filters, fetch_ohlcv
from sender import Sender
from storage import JSONStorage
import ccxt.async_support as ccxt
from utils import logger
from config import load_config2, load_scanner_config, load_wae_config
from market_scanner import scanner_loop
green_circle = '\U0001F7E2'
red_circle = '\U0001F534'

# load config (json preferred)
def load_config(path="config.json"):
    if os.path.exists(path):
        return json.load(open(path, "r", encoding="utf-8"))
    # fallback to old text parsing if needed - implement if required
    raise FileNotFoundError("config.json not found")


async def filter_worker(raw_queue, out_queue, config, config2, storage):
    global val_chan
    exchange = ccxt.bybit({'enableRateLimit': True})
    while True:
        raw = await raw_queue.get()
        try:
            pair, side, val = parse_raw_message(raw['text'])
            if pair:
                if raw['side'] == "bfpca1m2p":
                    val_chan = config2['global']['power_bfpca1m2p']
                if raw['side'] == "bfpca1m1p":
                    val_chan = config2['global']['power_bfpca1m1p']
                # print(f'ПАРА {pair}, {val} | {raw['side']} , {val_chan}')
                if abs(val) <= val_chan:
                    continue
                # Try per-chat timeframe configs: we'll check against each chat separately and if passes for chat, emit message for that chat
                pair = f'{pair}:USDT'
                for chat_name in config2['chats']:
                    # chat_cfg contains timeframes mapping; for simplicity we loop timeframes or pick default
                    is_ab = config2['chats'][chat_name]['is_ab']
                    if is_ab == True:
                        rsi_cfg = config2['chats'][chat_name]['rsi_map']
                        for item in config2['chats'][chat_name]["timeframes"]:
                            tfcfg = config2['chats'][chat_name]["timeframes"][item]

                            # for tf, tfcfg in chat_cfg['timeframes'].items():
                            # ensure tfcfg keys are ints
                            tfcfg_parsed = {
                                'EMA1': int(tfcfg['EMA1']),
                                'threshold_pct': float(tfcfg['threshold_pct']),
                                "timefraim": str(list(config2['chats'][chat_name]["timeframes"].keys())[0])
                            }
                            MIN_VOLUME = int(config2['chats'][chat_name]['MIN_VOLUME_USD'])
                            send_again = int(config2['chats'][chat_name]['SEND_DUPLICATE_PAIR_SECONDS'])
                            tresh_global_prcnt = int(config2['chats'][chat_name]['TIMEFRAME_GLOBAL_THRESHOLD'])
                            if side:
                                prase = "change down"
                                prase2 = "sell"
                            else:
                                prase = "change up"
                                prase2 = "buy"
                            ok, details = await passes_all_filters(pair, tfcfg_parsed, MIN_VOLUME, exchange, is_ab, rsi_cfg=rsi_cfg)
                            if ok:
                                if (prase == config2['chats'][chat_name]['accept_direction'].lower()) or (config2['chats'][chat_name]['accept_direction'].lower() == "all") or (prase2 == config2['chats'][chat_name]['accept_direction'].lower()):
                                    time = str(config2['chats'][chat_name]['TIMEFRAME_GLOBAL'])
                                    res = await fetch_ohlcv(exchange, pair, "1d", int(time[:-1]))
                                    if (res == False) or (res is None):
                                        pair2 = pair.split(':')[0]
                                        res = await fetch_ohlcv(exchange, pair2, "1d", int(time[:-1]))
                                    if res:
                                        res1 = res[0][-2]
                                        res2 = res[-1][-2]
                                        tresh = round(((float(res2) - float(res1)) / float(res1)) * 100)
                                        if tresh >= int(tresh_global_prcnt):
                                            circle2 = f"{green_circle} +" if tresh > 0 else f'{red_circle}'
                                            circle = f'{red_circle}' if side else f"{green_circle}"
                                            logger.info(f"Pair {pair} passed all filters")
                                            payload = {'pair': pair, 'ema': details.get('ema'), "circle": circle,
                                                       "vol": val, "ema2": int(tfcfg['EMA1']), "timeema": str(
                                                    list(config2['chats'][chat_name]["timeframes"].keys())[0]),
                                                       "3vol": tresh, "3circle": circle2, "3time": time}
                                            all_msg = {"chat_cfg": config2['chats'][chat_name]["chat_id"], "pair": pair,
                                                       "payload": payload, "send_again": send_again, "is_ab": True}
                                            await out_queue.put(all_msg)
                                    else:
                                        logger.info(f'Denide pair: {pair} {res}')

                    elif is_ab == "Three":
                        MIN_VOLUME = int(config2['chats'][chat_name]['MIN_VOLUME_USD'])
                        send_again = int(config2['chats'][chat_name]['SEND_DUPLICATE_PAIR_SECONDS'])
                        timefraim = (config2['chats'][chat_name]['TIMEFRAME_GLOBAL'])
                        lst_cfg = (config2['chats'][chat_name]['FILTR_S/R'])
                        if side:
                            prase = "change down"
                            prase2 = "sell"
                        else:
                            prase = "change up"
                            prase2 = "buy"

                        if (prase == config2['chats'][chat_name]['accept_direction'].lower()) or (config2['chats'][chat_name]['accept_direction'].lower() == "all") or (prase2 == config2['chats'][chat_name]['accept_direction'].lower()):
                            ok, details = await passes_all_filters(pair, timefraim, MIN_VOLUME, exchange, is_ab, lst_cnf=lst_cfg)
                            if ok:
                                time = str(config2['chats'][chat_name]['TIMEFRAME_GLOBAL'])
                                res = await fetch_ohlcv(exchange, pair, "1d", int(time[:-1]))
                                if (res == False) or (res is None):
                                    pair2 = pair.split(':')[0]
                                    res = await fetch_ohlcv(exchange, pair2, "1d", int(time[:-1]))
                                if res:
                                    res1 = res[0][-2]
                                    res2 = res[-1][-2]
                                    tresh = round(((float(res2) - float(res1)) / float(res1)) * 100)
                                    circle2 = f"{green_circle} +" if tresh > 0 else f'{red_circle} '
                                    circle = f'{red_circle}' if side else f"{green_circle}"
                                    for i in (details):
                                        payload = {"circle": circle, "val": val,
                                                   "metka": i['level'], "metka_tf": i['timeframe'], "metka_tresh": i["deviation_percent"],"metka_sign": i["sign"],
                                                   "circle2": circle2, "time": time, "globla_thres": tresh
                                                   }
                                        all_msg = {"chat_cfg" : config2['chats'][chat_name]["chat_id"],
                                                   "pair" : pair,
                                                   "payload": payload,
                                                   "send_again": send_again,
                                                   "is_ab": is_ab
                                                   }
                                        await out_queue.put(all_msg)
                        else:
                            continue

                    else:
                        rsi_cfg = config2['chats'][chat_name]['rsi_map']
                        for item in config2['chats'][chat_name]["timeframes"]:
                            tfcfg = config2['chats'][chat_name]["timeframes"][item]

                            # for tf, tfcfg in chat_cfg['timeframes'].items():
                            # ensure tfcfg keys are ints
                            tfcfg_parsed = {
                                'EMA1': int(tfcfg['EMA1']),
                                'threshold_pct': float(tfcfg['threshold_pct']),
                                "timefraim": str(list(config2['chats'][chat_name]["timeframes"].keys())[0])
                            }
                            MIN_VOLUME = int(config2['chats'][chat_name]['MIN_VOLUME_USD'])
                            send_again = int(config2['chats'][chat_name]['SEND_DUPLICATE_PAIR_SECONDS'])
                            timefraim = (config2['chats'][chat_name]['TIMEFRAME'])
                            colour = (config2['chats'][chat_name]['COLOUR'])
                            alltime = int(config2['chats'][chat_name]['ALLTIME'])
                            power = config2['chats'][chat_name]['POWER']
                            lst_alltime = config2['chats'][chat_name]['Time_lst']

                            if side:
                                prase = "change down"
                                prase2 = "sell"
                            else:
                                prase = "change up"
                                prase2 = "buy"

                            if (prase == config2['chats'][chat_name]['accept_direction'].lower()) or (config2['chats'][chat_name]['accept_direction'].lower() == "all") or (prase2 == config2['chats'][chat_name]['accept_direction'].lower()):
                                ok = await passes_all_filters(pair, timefraim, MIN_VOLUME, exchange, is_ab, alltime,
                                                              lst_alltime, colour, power, tfcfg_parsed, rsi_cfg)
                                if ok == True:
                                    res = await fetch_ohlcv(exchange, pair, "1d", 2)
                                    if (res == False) or (res is None):
                                        pair2 = pair.split(':')[0]
                                        res = await fetch_ohlcv(exchange, pair2, "1d", 2)
                                    if res:
                                        res1 = res[0][-2]
                                        res2 = res[-1][-2]
                                        tresh = round(((float(res2) - float(res1)) / float(res1)) * 100)
                                        circle2 = f"{green_circle} +" if tresh > 0 else f'{red_circle} '
                                        circle = f'{red_circle}' if side else f"{green_circle}"
                                        circle3 = f"{green_circle}" if colour == 'BUY' else f"{red_circle}"
                                        payload = {"circle": circle, "val": val, "trech_day": tresh,
                                                   "circle_day": circle2, "all_time": alltime, "timefraim": timefraim,
                                                   "circle3": circle3, "lst_alltime": lst_alltime, "first_cirle": colour}
                                        all_msg = {"chat_cfg": config2['chats'][chat_name]["chat_id"],
                                                   "pair": pair.split(':')[0], "payload": payload,
                                                   "send_again": send_again, "is_ab": is_ab}
                                        await out_queue.put(all_msg)
                                    else:
                                        print(f'Нет пары на Bybit, не удалось получить данные свеч')
                            else:
                                continue


        except Exception as e:
            logger.exception("Filter worker error: %s", e)
        finally:
            raw_queue.task_done()


async def sender_worker(out_queue, config, config2, storage):
    bot_token = config['aiogram']['bot_token']
    sender = Sender(bot_token, storage)
    sent = 0
    while True:
        all_msg = await out_queue.get()
        chat_cfg = all_msg['chat_cfg']
        pair = all_msg['pair']
        payload = all_msg['payload']
        send_again = all_msg['send_again']
        is_ab = all_msg['is_ab']
        try:
            ok = await sender.send_signal(chat_cfg, pair, payload, send_again, is_ab)
            sent += bool(ok)
        except Exception as e:
            logger.exception("Sender worker error: %s", e)
        finally:
            out_queue.task_done()

        # Разрыв между "фильтр пропустил" и "сообщение пришло" почти всегда
        # объясняется дедупликацией. Раз в сотню сигналов показываем баланс.
        if (sent + sum(sender.skipped.values())) % 100 == 0 and sender.skipped:
            logger.info("Отправлено %s, отброшено дубликатами по чатам: %s",
                        sent, sender.skipped)


def is_test_mode():
    """Тестовый режим: работает только сканер Bybit (CHAT_J/B и WAE-чаты).

    Telethon и filter_worker не запускаются, поэтому api_id/api_hash личного
    аккаунта не нужны — из config.json читается только токен бота.

    Включается флагом `--test` в командной строке или TEST_MODE=1 в .env.
    """
    if any(arg in ("--test", "--scanner-only") for arg in sys.argv[1:]):
        return True
    return str(os.getenv("TEST_MODE", "0")).strip().lower() in ("1", "true", "yes", "on")


async def main():
    from dotenv import load_dotenv

    load_dotenv()
    test_mode = is_test_mode()

    config = load_config()
    config2 = load_config2()
    storage = JSONStorage("storage.json")

    raw_queue = asyncio.Queue()
    out_queue = asyncio.Queue()

    tasks = []
    if test_mode:
        logger.warning(
            "ТЕСТОВЫЙ РЕЖИМ: запущен только сканер Bybit "
            "(CHAT_J / CHAT_K и WAE-чаты CHAT_G / CHAT_H / CHAT_I). "
            "Telethon и обработка сигналов из telegram-каналов отключены."
        )
    else:
        channels = []
        if int(os.getenv("SCAN_bfpca1m2p", 1)) == 1:
            channels.append('bfpca1m2p')
        if int(os.getenv("SCAN_bfpca1mq1p", 1)) == 1:
            channels.append('bfpca1m1p')
        # start telethon listener in background
        tasks.append(asyncio.create_task(start_telethon(
            config['telethon']['api_id'],
            config['telethon']['api_hash'],
            channels,
            raw_queue
        )))

        # spawn workers
        tasks.extend(asyncio.create_task(filter_worker(raw_queue, out_queue, config, config2, storage))
                     for _ in range(3))

    tasks.append(asyncio.create_task(sender_worker(out_queue, config, config2, storage)))

    # Сканер рынка Bybit — не зависит от telegram-каналов, кладёт готовые
    # сигналы в ту же out_queue. Сам себя перезапускает при сбоях. Обслуживает
    # две независимые группы чатов в одном проходе: свечные CHAT_J / CHAT_K и
    # CHAT_G / CHAT_H / CHAT_I по индикатору Waddah Attar Explosion.
    tasks.append(asyncio.create_task(
        scanner_loop(out_queue, load_scanner_config(), load_wae_config())
    ))

    # return_exceptions=True: падение одной задачи не отменяет остальные.
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
