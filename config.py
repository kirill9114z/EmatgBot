import os
from dotenv import load_dotenv
import re
from collections import defaultdict


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
        val = os.getenv(env_name, 1)
        if val is None:
            print(f"Warning: {env_name} not found in .env, defaulting to 0")
            time_offsets.append(0)
        try:
            time_offsets.append((val))
        except ValueError:
            print(f"Warning: {env_name} has non-numeric value {val}, defaulting to 0")
            time_offsets.append(0)
    # print(f'{prefix}   {time_offsets}')
    return time_offsets
def load_config2():
    """Загрузка конфигурации из переменных окружения"""

    # Разделяем строку с каналами по запятым

    return {
        "global": {
            "MIN_VOLUME_USD": float(os.getenv('MIN_VOLUME_USD', 1000000)),
            "SEND_DUPLICATE_PAIR_SECONDS": int(os.getenv('SEND_DUPLICATE_PAIR_SECONDS', 300)),
            "TIMEFRAME_GLOBAL": str(os.getenv('TIMEFRAME_GLOBAL', "1d")),
            "SCAN_bfpca1m2p": float(os.getenv("SCAN_bfpca1m2p", 1)),
            "SCAN_bfpca1m1p": float(os.getenv("SCAN_bfpca1m1p", 1)),
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
                },
                "rsi_map": {
                    "RSI": int(os.getenv('CHAT_A_RSI', 0)),
                    "RSI_VOL": int(os.getenv('CHAT_A_RSI_VOLUME', 20)),
                    "timefraim": str(os.getenv('CHAT_A_RSI_TIMEFRAIM', "30m"))
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
                        "EMA1": float(os.getenv('CHAT_B_EMA1', 20)),
                        "threshold_pct": float(os.getenv('CHAT_B_THRESHOLD_PCT', 1))
                    }
                },
                "rsi_map": {
                    "RSI": int(os.getenv('CHAT_B_RSI', 0)),
                    "RSI_VOL": float(os.getenv('CHAT_B_RSI_VOLUME', 20)),
                    "timefraim": str(os.getenv('CHAT_B_RSI_TIMEFRAIM', "30m"))
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
                    str(os.getenv("TIMEFRAIM_C_EMA", "30m")): {
                        "EMA1": int(os.getenv('VOLUME_C_EMA', 20)),
                        "threshold_pct": float(os.getenv('TRESHOLD_C_EMA', 1))
                    }
                },
                "rsi_map": {
                    "RSI": int(os.getenv('CHAT_C_RSI', 0)),
                    "RSI_VOL": float(os.getenv('CHAT_C_RSI_VOLUME', 20)),
                    "timefraim": str(os.getenv('CHAT_C_RSI_TIMEFRAIM', "30m"))
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
                },
                "rsi_map": {
                    "RSI": int(os.getenv('CHAT_D_RSI', 0)),
                    "RSI_VOL": float(os.getenv('CHAT_D_RSI_VOLUME', 20)),
                    "timefraim": str(os.getenv('CHAT_D_RSI_TIMEFRAIM', "30m"))
                }
            },
            "CHAT_E": {
                "is_ab": "Three",
                "chat_id": -1003816224033,
                "accept_direction": os.getenv('CHAT_E_ACCEPT_DIRECTION', "change up"),
                "MIN_VOLUME_USD": float(os.getenv('CHAT_E_MIN_VOLUME', 1000000)),
                "SEND_DUPLICATE_PAIR_SECONDS": int(os.getenv('CHAT_E_SEND_DUPLICATE_PAIR_SECONDS', 300)),
                "TIMEFRAME_GLOBAL": str(os.getenv('CHAT_A_TIMEFRAME_GLOBAL', "1d")),
                "FILTR_S/R": parse_pivot_config_from_env(prefix="R"),

            },
            "CHAT_F": {
                "is_ab": "Three",
                "chat_id": -1003561670666,
                "accept_direction": os.getenv('CHAT_F_ACCEPT_DIRECTION', "change up"),
                "MIN_VOLUME_USD": float(os.getenv('CHAT_F_MIN_VOLUME', 1000000)),
                "SEND_DUPLICATE_PAIR_SECONDS": int(os.getenv('CHAT_F_SEND_DUPLICATE_PAIR_SECONDS', 300)),
                "TIMEFRAME_GLOBAL": str(os.getenv('CHAT_A_TIMEFRAME_GLOBAL', "1d")),
                "FILTR_S/R": parse_pivot_config_from_env(prefix="S"),

            },
        }
    }


def get_three(prefix):
    lst = {}
    for i in range(1, 6):
        lst_min = {}
        don = os.getenv(f"{prefix}{i}", "5m 1%").split()
        if len(don) == 3:
            lst_min[f'time'] = don[0]
            lst_min[f'thres'] = float(don[1][0:-1])
            lst_min[f'sign'] = don[2]
            lst[f'{prefix}{i}'] = lst_min
        else:
            lst_min[f'time'] = don[0]
            lst_min[f'thres'] = float(don[1][0:-1])
            lst_min[f'sign'] = ''
            lst[f'{prefix}{i}'] = lst_min
    return lst


def parse_pivot_config_from_env(env_file='.env', prefix='R'):

    pattern = re.compile(
        rf'^({prefix}[1-5])\s*=\s*'  # метка R1-R5 или S1-S5
        r'(\S+)\s+'  # таймфрейм (5m, 1h, 1d)
        r'([\d.]+)%'  # порог (число с %)
        r'(?:\s+([+\-]))?'  # знак (опционально)
        r'\s*$',
        re.IGNORECASE
    )

    configs = defaultdict(list)

    if not os.path.exists(env_file):
        print(f"⚠️ Файл {env_file} не найден")
        return {}

    with open(env_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()

            # Пропускаем пустые строки и комментарии
            if not line or line.startswith('#'):
                continue

            match = pattern.match(line)
            if not match:
                continue

            level, timeframe, threshold, sign = match.groups()

            config = {
                'time': timeframe,
                'thres': float(threshold),
                'sign': sign if sign else ''
            }

            configs[level].append(config)

    # Валидация: таймфреймы у одинаковых меток должны быть уникальными
    for level, cfgs in configs.items():
        timeframes = [c['time'] for c in cfgs]
        if len(timeframes) != len(set(timeframes)):
            duplicates = [tf for tf in timeframes if timeframes.count(tf) > 1]
            print(f"⚠️ WARNING: {level} имеет дублирующиеся таймфреймы: {duplicates}")

    return dict(configs)

# ---------------------------------------------------------------------------
# Сканер свечей Bybit (чаты CHAT_J / CHAT_K)
#
# В отличие от чатов A-F, эти чаты не слушают telegram-каналы, а сами
# опрашивают рынок бессрочных фьючерсов раз в SCAN_MINTIME секунд.
# ---------------------------------------------------------------------------

SCANNER_TIMEFRAMES = ('5m', '15m', '30m', '45m', '1h', '2h', '4h', '1d', '1w')


def _scan_off_number(env_name: str, default='off'):
    """Числовая настройка сканера, которую можно выключить словом off.

    Возвращает float или None (фильтр выключен).
    """
    raw = str(os.getenv(env_name, default)).strip().lower().rstrip('%')
    if raw in ('', 'off', 'none', '-'):
        return None
    try:
        return float(raw.replace(',', '.'))
    except ValueError:
        print(f"⚠️ {env_name}='{raw}' — не число и не 'off', фильтр выключен")
        return None


def _scan_colour(env_name: str, default='off', allow_off=True):
    """Цвет тела свечи: red / green (/ off, если allow_off)."""
    raw = str(os.getenv(env_name, default)).strip().lower()
    if raw in ('red', 'green'):
        return raw
    if allow_off and raw in ('', 'off', 'none', '-'):
        return None
    print(f"⚠️ {env_name}='{raw}' — ожидается red/green"
          f"{'/off' if allow_off else ''}, взято '{default}'")
    return default if default in ('red', 'green') else None


def _scan_timeframe(env_name: str, default='15m'):
    raw = str(os.getenv(env_name, default)).strip()
    if raw in SCANNER_TIMEFRAMES:
        return raw
    print(f"⚠️ {env_name}='{raw}' — недопустимый таймфрейм, взято '{default}'")
    return default


def load_scanner_chat(prefix: str):
    """Конфиг одного чата-сканера свечей, например prefix='CHAT_J'."""
    try:
        candles = int(os.getenv(f'{prefix}_PERIOD_CANDLES', 3))
    except ValueError:
        candles = 3
    return {
        # 'scanner' — отдельная ветка форматирования в sender.py
        "is_ab": "scanner",
        "chat_id": int(os.getenv(f'{prefix}_CHAT_ID', 0)),
        # RSI: число (от и более) или off. Таймфрейм берётся из CANDLE_TIMEFRAME.
        "RSI": _scan_off_number(f'{prefix}_RSI'),
        # Цвет тела текущей свечи — обязательный фильтр, off не предусмотрен ТЗ.
        "CANDLE_COLOUR": _scan_colour(f'{prefix}_CANDLE_COLOUR', 'green', allow_off=False),
        # Таймфрейм, на котором считаются свечи и RSI для этого чата.
        "CANDLE_TIMEFRAME": _scan_timeframe(f'{prefix}_CANDLE_TIMEFRAME'),
        # Размер тела текущей свечи в % от тела предыдущей (от и более) или off.
        "CANDLE_SIZE": _scan_off_number(f'{prefix}_CANDLE_SIZE'),
        # Цвет тела предыдущей закрытой свечи или off.
        "PREVIOS_CANDLE": _scan_colour(f'{prefix}_PREVIOS_CANDLE'),
        # Движение тела текущей свечи в % (без фитиля) или off.
        "CHANGE": _scan_off_number(f'{prefix}_CHANGE'),
        # Информационный период для последней строки сообщения, например '15D'.
        "PERIOD_INFO": str(os.getenv(f'{prefix}_PERIOD_INFO', '15D')).strip(),
        # Сколько кружков-свечей показать (последний = текущая свеча).
        "PERIOD_CANDLES": max(1, min(9, candles)),
    }


def load_scanner_config():
    """Общие настройки сканера свечей + конфиги чатов CHAT_J / CHAT_K.

    Нумерация продолжает общий алфавит: A-F — чаты на telegram-сигналах,
    G/H/I — WAE-чаты (эти буквы за ними исторически), значит свечным сканерам
    достаются следующие свободные J и K. В ТЗ заказчика они называются
    "CHAT A" / "CHAT B", но буквы A/B в проекте уже заняты.
    """
    return {
        # Работаем по бессрочным фьючерсам с оборотом от VOLUME usdt / 24ч.
        "VOLUME": float(os.getenv('SCAN_VOLUME', 10_000_000)),
        # Сканируем рынок раз в MINTIME секунд.
        "MINTIME": int(os.getenv('SCAN_MINTIME', 60)),
        # По одной и той же монете алерт не чаще 1 раза в DUPLICATE секунд.
        "DUPLICATE": int(os.getenv('SCAN_DUPLICATE', 300)),
        "chats": {
            "CHAT_J": load_scanner_chat('CHAT_J'),
            "CHAT_K": load_scanner_chat('CHAT_K'),
        },
    }


# ---------------------------------------------------------------------------
# WAE-чаты (Waddah Attar Explosion) — чаты 7/8/9
#
# В старой версии бота эти чаты фильтровали сигналы, прилетавшие из telegram-
# каналов. Здесь они переведены на самостоятельное сканирование рынка Bybit:
# источник данных другой, но сам фильтр (wae_filter.check_sequence) тот же.
#
# Имена переменных полностью совпадают со старой версией (CHAT_G_*, ALLTIME_G,
# Time_G_1, COLOUR_G, POWER_G, CHANGE_G_*), чтобы настройки переносились из
# старого .env копированием. Свечные чаты сканера, которые раньше занимали
# CHAT_G/CHAT_H, переименованы в CHAT_J/CHAT_K — см. load_scanner_config.
#
# Единственный ключ, которого в старом .env не было: CHAT_G_CHAT_ID. Раньше id
# был зашит в config.py числом; здесь он вынесен в .env, как у всех остальных
# чатов сканера.
# ---------------------------------------------------------------------------

WAE_CHAT_PREFIXES = ('G', 'H', 'I')


def load_wae_sequence(alltime, prefix):
    """Последовательность баров WAE из .env. Порт load_config_WAE как есть.

    ALLTIME_G=2 + Time_G_1='SELL 10' + COLOUR_G=SELL + POWER_G=45
        -> [{'SELL': '10'}, {'SELL': 45}]

    Порядок важен: слева самый старый бар, справа текущий. Последний элемент
    всегда собирается из COLOUR_/POWER_, а промежуточные — из Time_*, причём
    в обратном порядке. Логика повторяет старую версию, включая alltime -= 1.
    """
    lst = []
    alltime -= 1
    if alltime < 0:
        return None
    colour = str(os.getenv(f'COLOUR_{prefix}', 'SELL')).strip().upper()
    try:
        power = int(os.getenv(f'POWER_{prefix}', 0))
    except ValueError:
        print(f"⚠️ POWER_{prefix} не число, взято 0")
        power = 0

    if alltime == 0:
        return [{colour: power}]

    for i in range(1, alltime + 1):
        raw = os.getenv(f'Time_{prefix}_{i}')
        if not raw:
            print(f"⚠️ Time_{prefix}_{i} не задан — последовательность WAE_{prefix} игнорируется")
            return None
        parts = raw.split()
        if len(parts) < 2:
            print(f"⚠️ Time_{prefix}_{i}='{raw}' — ожидается 'BUY 10' или 'SELL -90'")
            return None
        lst.append({parts[0].strip().upper(): parts[1]})
    lst.reverse()
    lst.append({colour: power})
    return lst


def load_wae_change(prefix: str):
    """Фильтр по изменению цены за период: CHANGE_G_IS / CHANGE_G_TIMEFRAIM / CHANGE_G.

    Порт блока Last_DAY из старой версии. ВНИМАНИЕ на роли переменных, они
    неочевидны и однажды уже были прочитаны наоборот (config.py:169-172 старой
    версии):

        CHANGE_G            — ВКЛЮЧАТЕЛЬ фильтра (0 = выключен), CHANGE_DAY
        CHANGE_G_IS         — ПОРОГОВОЕ значение в %,            CHANGE_DAY_VL
        CHANGE_G_TIMEFRAIM  — период,                            CHANGE_DAY_TF

    Да, `_IS` — это порог, а не «is enabled». Имена в оригинале сбивают с толку.

    Поведение старого кода:
      * фильтр ВЫКЛЮЧЕН (CHANGE_G=0) — берутся 2 дневные свечи, считается
        настоящее суточное изменение, показывается в сообщении, ничего не
        отсеивается. Именно так и работали все три чата у заказчика;
      * фильтр ВКЛЮЧЁН — берётся int(CHANGE_G_TIMEFRAIM без последней буквы)
        дневных свечей, и пары с изменением ниже CHANGE_G_IS отбрасываются;
      * таймфрейм всегда дневной, из периода берётся только число
        ('15d' -> 15 дневных свечей);
      * изменение считается от close первой свечи выборки к close последней;
      * подпись в сообщении — всегда значение CHANGE_G_TIMEFRAIM, даже когда
        фильтр выключен и изменение на деле посчитано за сутки.
    """
    raw_on = str(os.getenv(f'CHANGE_{prefix}', 0)).strip().upper()
    enabled = raw_on in ('1', 'ON', 'TRUE', 'YES')

    label = str(os.getenv(f'CHANGE_{prefix}_TIMEFRAIM', '1d')).strip()
    match = re.match(r'^\s*(\d+)', label)
    candles = int(match.group(1)) if match else 2

    min_pct = None
    if enabled:
        try:
            min_pct = float(str(os.getenv(f'CHANGE_{prefix}_IS', 0)).replace(',', '.'))
        except ValueError:
            print(f"⚠️ CHANGE_{prefix}_IS не число, фильтр по изменению выключен")
            enabled = False

    return {
        "ENABLED": enabled,
        # Выключённый фильтр всё равно показывает изменение — за сутки,
        # по двум свечам, как в старой версии.
        "CANDLES": max(2, candles) if enabled else 2,
        "MIN_PCT": min_pct,
        "LABEL": label,
    }


def load_wae_chat(prefix: str, defaults: dict):
    """Конфиг одного WAE-чата, например prefix='G' (переменные CHAT_G_*)."""
    try:
        alltime = int(os.getenv(f'ALLTIME_{prefix}', 1))
    except ValueError:
        alltime = 1
    return {
        # Отдельная ветка форматирования в sender.py.
        "is_ab": "wae",
        "chat_id": int(os.getenv(f'CHAT_{prefix}_CHAT_ID', 0)),
        # Таймфрейм, на котором считается индикатор. Имя ключа как в старой
        # версии; по умолчанию — общий TIMEFRAME_GLOBAL, как просил заказчик.
        "TIMEFRAME": _scan_timeframe(f'CHAT_{prefix}_TIMEFRAME_GLOBAL',
                                     defaults['TIMEFRAME_GLOBAL']),
        # Последовательность баров: цвет + минимальный отрыв от explosion line.
        "SEQUENCE": load_wae_sequence(alltime, prefix),
        # Изменение за период: и фильтр, и последняя строка сообщения.
        "CHANGE": load_wae_change(prefix),
    }


def load_wae_config():
    """Настройки WAE-чатов.

    Оборот, окно дедупликации и таймфрейм берутся из ОБЩИХ переменных
    (MIN_VOLUME_, SEND_DUPLICATE_PAIR_SECONDS, TIMEFRAME_GLOBAL) — это
    требование заказчика. Частота сканирования общая со сканером свечей
    (SCAN_MINTIME), потому что оба живут в одном цикле.

    Историческая деталь: load_config2 читает оборот из MIN_VOLUME_USD, тогда
    как в .env лежит MIN_VOLUME_. Здесь принимаются оба имени, приоритет у
    того, что реально прописано в файле.
    """
    volume = os.getenv('MIN_VOLUME_') or os.getenv('MIN_VOLUME_USD') or 10_000_000
    defaults = {
        "TIMEFRAME_GLOBAL": str(os.getenv('TIMEFRAME_GLOBAL', '1d')).strip(),
    }
    return {
        "VOLUME": float(volume),
        "DUPLICATE": int(os.getenv('SEND_DUPLICATE_PAIR_SECONDS', 300)),
        "TIMEFRAME_GLOBAL": defaults["TIMEFRAME_GLOBAL"],
        "chats": {
            f"CHAT_{prefix}": load_wae_chat(prefix, defaults)
            for prefix in WAE_CHAT_PREFIXES
        },
    }


config = load_config2()

# Теперь вы можете использовать config в вашем приложении
if __name__ == "__main__":
    ds = parse_pivot_config_from_env(prefix="R")
    print(f'1: {ds}')
    print(f'scanner: {load_scanner_config()}')
    print(f'wae: {load_wae_config()}')
