import asyncio, re, logging
from telethon import TelegramClient, events
from telethon.sessions.abstract import Session
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
logger = logging.getLogger("telethon_listener")
session = StringSession()
# message is telethon.types.Message

async def start_telethon(api_id, api_hash, channels, raw_queue, session_name="session"):
    while True:
        client = None
        try:
            client = TelegramClient(session_name, api_id, api_hash)
            await client.start()
            print(f" 2 {client.is_connected()}")
            @client.on(events.NewMessage(chats=channels))
            async def handler(event):
                try:
                    text = (event.raw_text or "").strip()
                    print(f'1: {event}')
                    # make a simple object
                    if "Alerts" in text:
                        raw = {
                            "text": text,
                            "sender_id": getattr(event.sender, "id", None),
                            "date": event.date.isoformat(),
                            "channel": event.chat.username if hasattr(event.chat, "username") else str(getattr(event.chat, "id", None)),
                            "side": True,
                        }
                    else:
                        raw = {
                            "text": text,
                            "sender_id": getattr(event.sender, "id", None),
                            "date": event.date.isoformat(),
                            "channel": event.chat.username if hasattr(event.chat, "username") else str(
                                getattr(event.chat, "id", None)),
                            "side": False,
                        }
                    await raw_queue.put(raw)
                    # logger.info(f"Pushed raw message from {raw['channel']}: {text[:50]}")
                except Exception as e:
                    logger.exception("Error handling telethon event: %s", e)

            logger.info("Telethon started and listening to channels: %s", channels)
            await client.run_until_disconnected()
        except (ConnectionError, SessionPasswordNeededError) as e:
            if client:
                await client.disconnect()
            logger.error(f"Telethon error: {e}, reconnecting in 60 seconds...")
            await asyncio.sleep(60)
        except Exception as e:
            if client:
                await client.disconnect()
            logger.exception(f"Unexpected error: {e}")
            await asyncio.sleep(60)
