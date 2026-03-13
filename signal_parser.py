import re, logging
logger = logging.getLogger("parser")

# Heuristic: match pairs like ETHUSDT, BTCUSDT, or tokens like ETH, BTC, BNB, UNI, etc.
PAIR_REGEX = re.compile(r"\b([A-Z]{2,10})(?:[-_/ ]?(USDT|USD|ETH|BTC))?\b")

# def parse_raw_message(raw_text):
#     """
#     Returns list of normalized pair strings like 'ETH/USDT' or ['ETH']
#     In practice you'll need to refine this based on actual channel formats.
#     """
#     text = raw_text.upper()
#     found = []
#     for m in PAIR_REGEX.finditer(text):
#         base = m.group(1)
#         quote = m.group(2) or "USDT"
#         pair = f"{base}/{quote}"
#         found.append(pair)
#     # Keep unique preserving order
#     seen = set()
#     uniq = []
#     for p in found:
#         if p not in seen:
#             uniq.append(p); seen.add(p)
#     return uniq

import re
green_circle = '\U0001F7E2'
red_circle = '\U0001F534'
def parse_raw_message(text: str):
    """
    Извлекает из текста строку вида 'BSWUSDT' и возвращает формат 'BSW/USDT'.
    Если тикер не найден, возвращает None.
    """
    # Ищем, например, BSWUSDT или ETHUSDT — от 2 до 6 букв, затем стандартные квоты
    m = re.search(r'\b([A-Z]{1,15})(USDT)\b', text.upper())
    if m:
        base = m.group(1)
        quote = m.group(2)
        side = red_circle in text
        pct_match = re.search(r'%-?([0-9]+(?:\.[0-9]+)?)', text)  # формат 1: %2.04 или %-2.04
        if not pct_match:
            pct_match = re.search(r'([0-9]+(?:\.[0-9]+)?)%', text)  # формат 2: 2.05%

        change_pct = None
        if pct_match:
            try:
                value = float(pct_match.group(1))
                # если в тексте был минус — он уже учтён; если нет, добавляем знак по кружку
                if '-' in pct_match.group(0):
                    change_pct = -round(value, 1)
                else:
                    change_pct = -round(value, 1) if side else round(value, 1)
            except:
                change_pct = None
        return f"{base}/{quote}", side, change_pct
    return None, None, None

if __name__ == '__main__':
    pair, side, tres = parse_raw_message("💰 #LIGHTUSDT Change: 🔴-1.23% Last Price: 1.784500 Previous Price: 1.806800 Alerts in this hour: 4⭐️12:47:00 (UTC)")
    print(f'! {pair} {side} {tres}')

