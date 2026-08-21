import asyncio, logging
from aiogram import Bot
from utils import now_ts
from aiogram.client.default import DefaultBotProperties
logger = logging.getLogger("sender")

green_circle = '\U0001F7E2'
red_circle = '\U0001F534'


class Sender:
    def __init__(self, bot_token, storage):
        self.bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))
        self.storage = storage
        # {chat_id: сколько сигналов отброшено дедупликацией} — нарастающим
        # итогом за время работы процесса, для диагностики "фильтр сработал,
        # а сообщения нет".
        self.skipped = {}

    async def send_signal(self, chat_cfg, pair, payload, send_duplicate_seconds, is_ab):
        global text
        chat_id = chat_cfg
        # dedup check
        now = now_ts()

        # ДЕДУПЛИКАЦИЯ В ЗАВИСИМОСТИ ОТ ТИПА ГРУППЫ
        if is_ab == "Three":  # группы 5-6 с Pivot
            # извлекаем метку и таймфрейм из payload
            pivot_level = payload.get('metka')  # R1, S2, PP
            pivot_timeframe = payload.get('metka_tf')  # 5m, 1h, 1d

            if not pivot_level or not pivot_timeframe:
                logger.error("Pivot signal missing level/timeframe: %s", payload)
                return False

            # проверяем дедупликацию по pivot-ключу
            last = self.storage.get_last_sent_pivot(chat_id, pair, pivot_level, pivot_timeframe)
            if last and (now - int(last) < send_duplicate_seconds):
                return False

            text = self.format_text_pivot(pair, payload)

            try:
                await self.bot.send_message(chat_id, text)
                self.storage.set_last_sent_pivot(chat_id, pair, pivot_level, pivot_timeframe, now)
                return True
            except Exception as e:
                logger.exception("Failed to send Pivot message to %s: %s", chat_id, e)
                return False
        else:
            last = self.storage.get_last_sent(chat_id, pair)
            if last and (now - int(last) < send_duplicate_seconds):
                # Дубликат — не ошибка, но без этой строки "фильтр пропустил,
                # а сообщения нет" выглядит как поломка. Считаем и пишем сводку.
                self.skipped[chat_id] = self.skipped.get(chat_id, 0) + 1
                logger.debug("Дубликат %s для чата %s: прошло %sс из %sс",
                             pair, chat_id, now - int(last), send_duplicate_seconds)
                return False
            # ВАЖНО: "scanner" и "wae" — истинные строки, проверяем их ДО `if is_ab`.
            if is_ab == "scanner":
                text = self.format_scanner_message(pair, payload)
            elif is_ab == "wae":
                text = self.format_wae_message(pair, payload)
            elif is_ab:
                text = self.format_message(pair, payload)
            else:
                text = self.format_text2_group34(pair, payload)
            try:
                await self.bot.send_message(chat_id, text)
                self.storage.set_last_sent(chat_id, pair, now)
                # logger.info("Sent signal %s to %s", pair, chat_id)
                return True
            except Exception as e:
                logger.exception("Failed to send message to %s: %s", chat_id, e)
                return False

    def format_message(self, pair, payload):
        coin = pair.split('/')[0]
        # payload may contain ema, deviation, volume
        ema = payload.get('ema', {})
        ema_vol = payload['ema2']
        timefraim = payload["timeema"]

        vol = payload['vol']
        # vol = str(int(float(vol))) if float(vol).is_integer() else str(float(vol))
        if str(vol)[-1] == "0":
            vol = int(vol)
        circle = payload['circle']
        side = "+" if circle == f"{green_circle}" else ""

        time3 = payload["3time"]
        circle3 = payload["3circle"]
        vol3 = payload["3vol"]
        return (f"{circle} <code>{coin}</code> {side}{vol}%\n"
                f"EMA{ema_vol} {timefraim} {green_circle} +{int(ema.get('deviation_pct'))}%\n"
                f"{time3} {circle3}{vol3}%")

    def format_text2_group34(self, pair, payload):
        coin = pair.split('/')[0]
        circle = payload['circle']
        vol = payload['val']
        if str(vol)[-1] == "0":
            vol = int(vol)
        res = [f"{green_circle}" if i == "BUY" else f"{red_circle}" for i in payload["lst_alltime"]]
        result = ''.join(res)
        side = "+" if circle == f"{green_circle}" else ""
        secind_tim = payload['timefraim']
        tresh_day = payload['trech_day']
        cirlce_day = payload['circle_day']
        return (f"{circle} <code>{coin}</code> {side}{vol}%\n"
                f"{result}{green_circle if payload['first_cirle'] == '' else red_circle} {secind_tim}\n"
                f"1D {cirlce_day}{tresh_day}%")

    def format_wae_message(self, pair, payload):
        """Сообщение для WAE-чатов (CHAT_G / CHAT_H / CHAT_I).

        Макет повторяет format_wae из старой версии бота:
            🔴 BTC -1.2%       направление сигнала, тикер, тело текущей свечи
            🔴🔴 1d            цвета баров последовательности + таймфрейм WAE
            1d 🟢 +5%          информационный период и изменение за него

        Отличие от старой версии только в источнике первой строки: раньше там
        стоял процент из telegram-сигнала, здесь — тело текущей свечи, потому
        что сигнал приходит не из канала, а с биржи.
        """
        coin = pair.split('/')[0]
        circle = red_circle if payload.get('signal') == 'SELL' else green_circle
        colours = ''.join(
            red_circle if c == 'SELL' else green_circle
            for c in payload.get('colours', [])
        )

        body = payload.get('body_pct')
        head = f"{circle} <code>{coin}</code>"
        if body is not None:
            head += f" {body:+.1f}%"
        lines = [head]

        if colours:
            lines.append(f"{colours} {str(payload.get('timeframe', '')).upper()}")

        change_pct = payload.get('change_pct')
        if change_pct is not None:
            # Как в старой версии: зелёный строго при росте, ноль — красный.
            change_circle = green_circle if round(change_pct) > 0 else red_circle
            lines.append(
                f"{str(payload.get('change_label', '')).lower()} "
                f"{change_circle} {round(change_pct):+d}%"
            )

        return "\n".join(lines)

    def format_scanner_message(self, pair, payload):
        """Сообщение для чатов-сканеров свечей (CHAT_J / CHAT_K).

        Макет из ТЗ:
            🔴 LAB -1.1% 15M      цвет тела текущей свечи, тикер, размер тела, таймфрейм
            🟢🟢🔴 165%           кружки последних свечей + тело текущей в % от предыдущей
            15d 🔴 -22%           информационный период и изменение за него
        """
        coin = pair.split('/')[0]
        circle = green_circle if payload['colour'] == 'green' else red_circle
        circles = ''.join(
            green_circle if c == 'green' else red_circle
            for c in payload.get('circles', [])
        )

        lines = [
            f"{circle} <code>{coin}</code> "
            f"{payload['body_pct']:+.1f}% {payload['timeframe'].upper()}"
        ]

        ratio = payload.get('ratio')
        second = f"{circles} {round(ratio)}%" if ratio is not None else circles
        if second:
            lines.append(second)

        period_change = payload.get('period_change')
        if period_change is not None:
            period_circle = green_circle if period_change >= 0 else red_circle
            lines.append(
                f"{str(payload['period_info']).lower()} "
                f"{period_circle} {round(period_change):+d}%"
            )

        return "\n".join(lines)

    def format_text_pivot(self, pair, payload):
        coin = pair.split('/')[0]
        circle = payload['circle']
        val = payload['val']
        side = "+" if circle == f"{green_circle}" else ""

        metka = payload['metka']
        metka_tf = payload['metka_tf']
        metka_vol = payload['metka_tresh']
        sign = payload['metka_sign']

        circle2 = payload['circle2']
        time = payload["time"]
        globla_thres = payload['globla_thres']
        return (f"{circle} <code>{coin}</code> {side}{val}%\n"
                f"{metka} {metka_tf} {metka_vol}% {sign}\n"
                f"{time} {circle2}{globla_thres}%"
                )
