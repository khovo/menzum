"""
handlers package
----------------
Public surface of the bot's business logic.

api/index.py imports exactly one thing from here:

    from handlers import process_telegram_update

process_telegram_update() opens a fresh Motor client + aiohttp session per
invocation (Vercel-safe), resolves the force-join channel list (cached), and
dispatches the update to the right sub-handler:

    callback_query → callback_handler.handle_callback
    message        → message_handler.handle_message
    inline_query   → inline_handler.handle_inline_query
"""
import logging
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient

from config import BOT_TOKEN, MONGO_URL, DB_NAME
from db import get_force_channels
from utils import get_channels_cache, set_channels_cache

from .callback_handler import handle_callback
from .message_handler import handle_message
from .inline_handler import handle_inline_query

logger = logging.getLogger(__name__)


async def process_telegram_update(data: dict) -> None:
    if not MONGO_URL or not BOT_TOKEN:
        logger.error("MONGO_URL or BOT_TOKEN not set — aborting.")
        return

    db_client = AsyncIOMotorClient(MONGO_URL)
    db        = db_client[DB_NAME]

    async with aiohttp.ClientSession() as session:
        try:
            channels = get_channels_cache()
            if channels is None:
                channels = await get_force_channels(db)
                set_channels_cache(channels)

            if "callback_query" in data:
                await handle_callback(session, db, data["callback_query"], channels)
            elif "message" in data:
                await handle_message(session, db, data["message"], channels)
            elif "inline_query" in data:
                await handle_inline_query(session, db, data["inline_query"], channels)

        except Exception:
            logger.exception("Unhandled error in process_telegram_update")
        finally:
            db_client.close()


__all__ = ["process_telegram_update"]
