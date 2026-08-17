import asyncio
import functools
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# ccxt/aiogram/telethon очень шумные на DEBUG/INFO — приглушаем
for noisy in ("ccxt", "aiogram", "telethon", "asyncio", "aiohttp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("bot")


def now_ts():
    """Unix-время в секундах (int) — ключ дедупликации в storage.json."""
    return int(time.time())


def retry_sleep(tries=3, delay=1.0, backoff=2.0):
    """Декоратор для async-функций: повторяет вызов при исключении.

    Пауза между попытками растёт: delay, delay*backoff, delay*backoff**2...
    После последней неудачной попытки исключение пробрасывается наружу —
    вызывающий код в filters.py ловит его сам.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            wait = delay
            last_exc = None
            for attempt in range(1, tries + 1):
                try:
                    return await func(*args, **kwargs)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    last_exc = e
                    if attempt == tries:
                        break
                    logger.debug(
                        "%s: попытка %s/%s не удалась (%s), повтор через %.1fс",
                        func.__name__, attempt, tries, e, wait,
                    )
                    await asyncio.sleep(wait)
                    wait *= backoff
            raise last_exc

        return wrapper

    return decorator
