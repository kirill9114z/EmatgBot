import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()
def load_chat_config(prefix: str):
    """
    Загружает конфигурацию для чата с данным префиксом, включая offsets.
    prefix: например, 'C' (для CHAT_C), или 'B' и т.д.
    """
    # ключи, зависящие от префикса
    alltime = int(os.getenv(f'ALLTIME_{prefix}', 1))
    time_offsets = []
    for i in range(1, alltime + 1):
        env_name = f'Time_{prefix}_{i}'
        val = os.getenv(env_name)
        if val is None:
            print(f"Warning: {env_name} not found in .env, defaulting to 0")
            time_offsets.append(0)
        try:
            time_offsets.append((val))
        except ValueError:
            print(f"Warning: {env_name} has non-numeric value {val}, defaulting to 0")
            time_offsets.append(0)
    return time_offsets
def load_config2():
    """Загрузка конфигурации из переменных окружения"""

    # Разделяем строку с каналами по запятым
    telethon_channels = os.getenv('TELETHON_CHANNELS', '').split(',')

    return {
        "global": {
            "MIN_VOLUME_USD": float(os.getenv('MIN_VOLUME_USD', 1000000)),
            "SEND_DUPLICATE_PAIR_SECONDS": int(os.getenv('SEND_DUPLICATE_PAIR_SECONDS', 300)),
            "TIMEFRAME_GLOBAL": str(os.getenv('TIMEFRAME_GLOBAL', "1d")),
            "SCAN_IiLQkMaO8y4wMTM1": float(os.getenv("SCAN_IiLQkMaO8y4wMTM1", 1)),
            "SCAN_bfpca1m2p": float(os.getenv("SCAN_bfpca1m2p", 1)),
            "SCAN_bfpca1m1p": float(os.getenv("SCAN_bfpca1m1p", 1)),
            "power_IiLQkMaO8y4wMTM1": float(os.getenv("power_IiLQkMaO8y4wMTM1", 1.1)),
            "power_bfpca1m1p": float(os.getenv("power_bfpca1m1p", 1.2)),
            "power_bfpca1m2p": float(os.getenv("power_bfpca1m2p", 2.1)),
        },
        "chats": {
            "CHAT_A": {
                "is_ab": True,
                "chat_id": -1002791943913,
                "accept_direction": os.getenv('CHAT_A_ACCEPT_DIRECTION', "change down"),
                "MIN_VOLUME_USD": float(os.getenv('CHAT_A_MIN_VOLUME', 1000000)),
                "SEND_DUPLICATE_PAIR_SECONDS": int(os.getenv('CHAT_A_SEND_DUPLICATE_PAIR_SECONDS', 300)),
                "TIMEFRAME_GLOBAL": str(os.getenv('CHAT_A_TIMEFRAME_GLOBAL', "1d")),
                "TIMEFRAME_GLOBAL_THRESHOLD": str(os.getenv('CHAT_A_TIMEFRAME_GLOBAL_THRESHOLD', 10)),
                "timeframes": {
                    str(os.getenv("CHAT_A_TIMEFRAIM", "1h")): {
                        "EMA1": int(os.getenv('CHAT_A_EMA1', 50)),
                        "threshold_pct": float(os.getenv('CHAT_A_THRESHOLD_PCT', 2))
                    }
                }
            },
            "CHAT_B": {
                "is_ab": True,
                "chat_id": -1002618022177,
                "accept_direction": os.getenv('CHAT_B_ACCEPT_DIRECTION', "change up"),
                "MIN_VOLUME_USD": float(os.getenv('CHAT_B_MIN_VOLUME', 1000000)),
                "SEND_DUPLICATE_PAIR_SECONDS": int(os.getenv('CHAT_B_SEND_DUPLICATE_PAIR_SECONDS', 300)),
                "TIMEFRAME_GLOBAL": str(os.getenv('CHAT_B_TIMEFRAME_GLOBAL', "1d")),
                "TIMEFRAME_GLOBAL_THRESHOLD": str(os.getenv('CHAT_B_TIMEFRAME_GLOBAL_THRESHOLD', 10)),
                "timeframes": {
                    str(os.getenv("CHAT_B_TIMEFRAIM", "30m")): {
                        "EMA1": int(os.getenv('CHAT_B_EMA1', 20)),
                        "threshold_pct": float(os.getenv('CHAT_B_THRESHOLD_PCT', 1))
                    }
                }
            },
            "CHAT_C": {
                "is_ab": False,
                "chat_id": -1003225444171,
                "accept_direction": os.getenv('CHAT_C_ACCEPT_DIRECTION', "change up"),
                "MIN_VOLUME_USD": float(os.getenv('CHAT_C_MIN_VOLUME', 1000000)),
                "SEND_DUPLICATE_PAIR_SECONDS": int(os.getenv('CHAT_C_SEND_DUPLICATE_PAIR_SECONDS', 300)),
                "TIMEFRAME": str(os.getenv('CHAT_C_TIMEFRAME_GLOBAL', "1d")),
                "COLOUR": str(os.getenv("COLOUR_C", 'BUY')),
                "POWER": float(os.getenv("POWER_C", 1)),
                "ALLTIME": int(os.getenv('ALLTIME_C', 5)),
                "Time_lst": load_chat_config('C'),
                "timeframes": {
                    str(os.getenv("TIMEFRAIM_EMA_C", "30m")): {
                        "EMA1": int(os.getenv('VOLUME_EMA_C', 20)),
                        "threshold_pct": float(os.getenv('TRESHOLD_EMA_C', 1))
                    }
                }
            },
            "CHAT_D": {
                "is_ab": False,
                "chat_id": -1003221079835,
                "accept_direction": os.getenv('CHAT_D_ACCEPT_DIRECTION', "change up"),
                "MIN_VOLUME_USD": float(os.getenv('CHAT_D_MIN_VOLUME', 1000000)),
                "SEND_DUPLICATE_PAIR_SECONDS": int(os.getenv('CHAT_D_SEND_DUPLICATE_PAIR_SECONDS', 300)),
                "TIMEFRAME": str(os.getenv('CHAT_D_TIMEFRAME_GLOBAL', "1d")),
                "COLOUR": str(os.getenv("COLOUR_D", 'BUY')),
                "POWER": float(os.getenv("POWER_D", 1)),
                "ALLTIME": int(os.getenv('ALLTIME_D', 5)),
                "Time_lst": load_chat_config('D'),
                "timeframes": {
                    str(os.getenv("TIMEFRAIM_EMA_D", "30m")): {
                        "EMA1": int(os.getenv('VOLUME_EMA_D', 20)),
                        "threshold_pct": float(os.getenv('TRESHOLD_EMA_D', 1))
                    }
                }
            },
        }
    }


# Загружаем конфигурацию
config = load_config2()

# Теперь вы можете использовать config в вашем приложении
if __name__ == "__main__":
    import json
    rs = load_chat_config("C")
    print(f'2: {rs}')
