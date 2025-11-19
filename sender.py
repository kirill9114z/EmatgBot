import asyncio, logging
from aiogram import Bot
from utils import now_ts
from aiogram.client.default import DefaultBotProperties
logger = logging.getLogger("sender")

class Sender:
    def __init__(self, bot_token, storage):
        self.bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))
        self.storage = storage

    async def send_signal(self, chat_cfg, pair, payload, send_duplicate_seconds, is_ab):
        global text
        chat_id = chat_cfg
        # dedup check
        last = self.storage.get_last_sent(chat_id, pair)
        now = now_ts()
        if last and (now - int(last) < send_duplicate_seconds):
            logger.info("Skipping duplicate for %s to chat %s (last %s sec ago)", pair, chat_id, now - int(last))
            return False
        if is_ab:
            text = self.format_message(pair, payload)
        else:
            text = self.format_text2(pair, payload)
        try:
            await self.bot.send_message(chat_id, text)
            self.storage.set_last_sent(chat_id, pair, now)
            logger.info("Sent signal %s to %s", pair, chat_id)
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
        side = "+" if circle == "🟢" else ""

        time3 = payload["3time"]
        circle3 = payload["3circle"]
        vol3 = payload["3vol"]
        return (f"{circle} <code>{coin}</code> {side}{vol}%\n"
                f"EMA{ema_vol} {timefraim} 🟢 +{int(ema.get('deviation_pct'))}%\n"
                f"{time3} {circle3}{vol3}%")

    def format_text2(self, pair, payload):
        coin = pair.split('/')[0]
        circle = payload['circle']
        vol = payload['val']
        if str(vol)[-1] == "0":
            vol = int(vol)
        side = "+" if circle == "🟢" else ""
        second_sicrle = payload['circle3'] * payload['all_time']
        secind_tim = payload['timefraim']
        tresh_day = payload['trech_day']
        cirlce_day = payload['circle_day']
        return (f"{circle} <code>{coin}</code> {side}{vol}%\n"
                f"{second_sicrle} {secind_tim}\n"
                f"1D {cirlce_day}{tresh_day}%")


