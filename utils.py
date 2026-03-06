"""
utils.py
--------
Two responsibilities:

1. Telegram API wrappers  — thin async functions, each accepting a shared
   aiohttp.ClientSession.  One session per webhook invocation = fewer TCP
   handshakes = faster responses under Vercel's cold-start penalty.

2. Caching helpers        — in-memory dicts that survive between requests on
   the same Vercel instance (warm invocations).

3. Async runner           — run_async() bridges Flask's synchronous WSGI world
   with our async business logic without blowing up Vercel's runtime.

4. UI helpers             — reusable keyboard builders so handlers.py stays
   clean of raw dict literals.
"""
import asyncio
import time
import logging
from typing import Any

from config import (
    BOT_TOKEN,
    FORCE_CHANNEL_USERNAME,
    MEMBERSHIP_CACHE_TTL,
    INLINE_EMPTY_CACHE_TTL,
)

logger = logging.getLogger(__name__)


# ── Async Runner ──────────────────────────────────────────────────────────────

def run_async(coro) -> Any:
    """
    Execute an async coroutine from synchronous Flask land.

    Creates a brand-new event loop per request.  This is intentional:
    Vercel serverless functions share memory between warm invocations but
    do NOT share threads, so reusing a loop from a previous request can
    cause 'Event loop is closed' crashes.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── In-Memory Caches ──────────────────────────────────────────────────────────

# { user_id: (is_member: bool, timestamp: float) }
MEMBERSHIP_CACHE: dict[int, tuple[bool, float]] = {}

# Cached results for empty inline queries (most common case)
_INLINE_EMPTY_CACHE: dict = {"data": [], "time": 0.0}


def get_inline_empty_cache() -> list | None:
    """Return cached empty-query results if still fresh, else None."""
    if _INLINE_EMPTY_CACHE["data"] and (
        time.time() - _INLINE_EMPTY_CACHE["time"] < INLINE_EMPTY_CACHE_TTL
    ):
        return _INLINE_EMPTY_CACHE["data"]
    return None


def set_inline_empty_cache(results: list) -> None:
    _INLINE_EMPTY_CACHE["data"] = results
    _INLINE_EMPTY_CACHE["time"] = time.time()


def invalidate_membership_cache(user_id: int) -> None:
    MEMBERSHIP_CACHE.pop(user_id, None)


# ── Telegram API Helpers ──────────────────────────────────────────────────────

async def check_membership(session, user_id: int) -> bool:
    """
    Returns True if the user is a member of FORCE_CHANNEL.
    Results are cached for MEMBERSHIP_CACHE_TTL seconds to avoid rate-limiting
    Telegram's getChatMember endpoint on every single message.

    Fail-open: if Telegram returns an error (bot not in channel, network blip),
    we return True so legitimate users are not accidentally blocked.
    """
    if not BOT_TOKEN:
        return True

    now = time.time()
    cached = MEMBERSHIP_CACHE.get(user_id)
    if cached:
        is_member, ts = cached
        if now - ts < MEMBERSHIP_CACHE_TTL:
            return is_member

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    try:
        async with session.get(url, params=params) as resp:
            res = await resp.json()
            if not res.get("ok"):
                return True  # fail-open
            status = res["result"]["status"]
            is_member = status in ("creator", "administrator", "member")
            MEMBERSHIP_CACHE[user_id] = (is_member, now)
            return is_member
    except Exception:
        return True  # fail-open on network error


async def send_message(
    session, chat_id, text: str, reply_markup=None
) -> dict | None:
    if not BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except Exception:
        logger.exception("send_message failed chat_id=%s", chat_id)
        return None


async def send_audio(
    session, chat_id, audio_file_id: str, caption: str, reply_markup=None
) -> dict | None:
    if not BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    payload: dict = {
        "chat_id": chat_id,
        "audio": audio_file_id,
        "caption": caption,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except Exception:
        logger.exception("send_audio failed chat_id=%s", chat_id)
        return None


async def edit_message_text(
    session, chat_id, message_id: int, text: str, reply_markup=None
) -> dict | None:
    if not BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload: dict = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except Exception:
        logger.exception("edit_message_text failed chat_id=%s", chat_id)
        return None


async def answer_callback_query(
    session, callback_query_id: str, text: str | None = None, show_alert: bool = False
) -> dict | None:
    if not BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except Exception:
        logger.exception("answer_callback_query failed id=%s", callback_query_id)
        return None


async def answer_inline_query(
    session,
    query_id: str,
    results: list,
    switch_pm_text: str | None = None,
    switch_pm_param: str | None = None,
    cache_time: int = 300,
) -> dict | None:
    if not BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    payload: dict = {
        "inline_query_id": query_id,
        "results": results,
        "cache_time": cache_time,
        "is_personal": True,
    }
    if switch_pm_text:
        payload["switch_pm_text"]      = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except Exception:
        logger.exception("answer_inline_query failed id=%s", query_id)
        return None


async def copy_message(
    session, chat_id, from_chat_id, message_id: int, reply_markup=None
) -> dict | None:
    if not BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    payload: dict = {
        "chat_id": chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except Exception:
        logger.exception("copy_message failed chat_id=%s", chat_id)
        return None


# ── UI / Keyboard Builders ────────────────────────────────────────────────────

def get_main_menu_kb() -> dict:
    """The persistent main menu shown after /start and after closing sub-flows."""
    return {
        "inline_keyboard": [
            [
                {
                    "text": "❤️ Favorites",
                    "switch_inline_query_current_chat": "#favorites",
                },
                {"text": "📂 Catalog (List)", "callback_data": "pg_1"},
            ],
            [
                {
                    "text": "📞 አስተያየት ለመስጠት (Support)",
                    "callback_data": "support_start",
                }
            ],
            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}],
        ]
    }


def get_not_found_kb() -> dict:
    """
    BUG FIX — 'Not Found' UX:
    Instead of a dead-end text reply, offer the user a direct path to the
    catalog so they can browse and copy-paste the correct name themselves.
    """
    return {
        "inline_keyboard": [
            [{"text": "📂 ሙሉ ዝርዝር (Catalog)", "callback_data": "pg_1"}]
        ]
    }


def get_subscription_kb(channel_url: str) -> dict:
    """Force-join keyboard shown to users who haven't subscribed yet."""
    return {
        "inline_keyboard": [
            [{"text": "Join Channel 📢", "url": channel_url}],
            [{"text": "✅ ተቀላቅያለሁ (Verify)", "callback_data": "check_subscription"}],
        ]
    }
