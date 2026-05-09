"""
utils.py
--------
1. Telegram API wrappers  — thin async functions using a shared aiohttp session.
2. Cache helpers          — in-memory dicts; survive across warm Vercel invocations.
3. Async runner           — bridges Flask's sync WSGI world with async business logic.
4. UI keyboard builders   — reusable dict builders; keeps handlers.py free of raw dicts.
"""
import asyncio
import time
import logging
from typing import Any

from config import (
    BOT_TOKEN,
    MEMBERSHIP_CACHE_TTL,
    INLINE_EMPTY_CACHE_TTL,
    CHANNELS_CACHE_TTL,
)

logger = logging.getLogger(__name__)

# ── Async Runner ──────────────────────────────────────────────────────────────

def run_async(coro) -> Any:
    """
    Execute an async coroutine from synchronous Flask land.
    Creates a fresh event loop per request — intentional for Vercel safety.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── In-Memory Caches ──────────────────────────────────────────────────────────

MEMBERSHIP_CACHE: dict[int, tuple[bool, float]] = {}
_INLINE_EMPTY_CACHE: dict = {"data": [], "time": 0.0}
_CHANNELS_CACHE: dict = {"data": None, "time": 0.0}


def get_inline_empty_cache() -> list | None:
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


def invalidate_all_membership_cache() -> None:
    MEMBERSHIP_CACHE.clear()


def get_channels_cache() -> list | None:
    if _CHANNELS_CACHE["data"] is not None and (
        time.time() - _CHANNELS_CACHE["time"] < CHANNELS_CACHE_TTL
    ):
        return _CHANNELS_CACHE["data"]
    return None


def set_channels_cache(channels: list) -> None:
    _CHANNELS_CACHE["data"] = channels
    _CHANNELS_CACHE["time"] = time.time()


def invalidate_channels_cache() -> None:
    _CHANNELS_CACHE["data"] = None


# ── Telegram API Helpers ──────────────────────────────────────────────────────

async def check_membership(session, user_id: int, channels: list[dict]) -> bool:
    if not BOT_TOKEN or not channels:
        return True

    now    = time.time()
    cached = MEMBERSHIP_CACHE.get(user_id)
    if cached:
        is_member, ts = cached
        if now - ts < MEMBERSHIP_CACHE_TTL:
            return is_member

    url      = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    usernames = [ch.get("username", "").strip() for ch in channels if ch.get("username", "").strip()]

    if not usernames:
        MEMBERSHIP_CACHE[user_id] = (True, now)
        return True

    async def _check_one(username: str) -> bool:
        try:
            async with session.get(url, params={"chat_id": f"@{username}", "user_id": user_id}) as resp:
                res = await resp.json()
                if not res.get("ok"):
                    return True
                return res["result"]["status"] in ("creator", "administrator", "member")
        except Exception:
            return True

    results = await asyncio.gather(*[_check_one(u) for u in usernames])

    is_member = all(results)
    MEMBERSHIP_CACHE[user_id] = (is_member, now)
    return is_member


async def send_message(session, chat_id, text: str, reply_markup=None) -> dict | None:
    if not BOT_TOKEN:
        return None
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload
        ) as resp:
            return await resp.json()
    except Exception:
        logger.exception("send_message failed chat_id=%s", chat_id)
        return None


async def send_audio(
    session, chat_id, audio_file_id: str, caption: str, reply_markup=None
) -> dict | None:
    if not BOT_TOKEN:
        return None
    payload = {
        "chat_id": chat_id, "audio": audio_file_id,
        "caption": caption,  "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio", json=payload
        ) as resp:
            return await resp.json()
    except Exception:
        logger.exception("send_audio failed chat_id=%s", chat_id)
        return None


async def send_document(
    session, chat_id, document_file_id: str, caption: str = "", reply_markup=None
) -> dict | None:
    if not BOT_TOKEN:
        return None
    payload = {"chat_id": chat_id, "document": document_file_id}
    if caption:
        payload["caption"]    = caption
        payload["parse_mode"] = "Markdown"
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", json=payload
        ) as resp:
            return await resp.json()
    except Exception:
        logger.exception("send_document failed chat_id=%s", chat_id)
        return None


async def send_media_group(session, chat_id, media: list) -> dict | None:
    if not BOT_TOKEN:
        return None
    payload = {"chat_id": chat_id, "media": media}
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup", json=payload
        ) as resp:
            return await resp.json()
    except Exception:
        logger.exception("send_media_group failed chat_id=%s", chat_id)
        return None


async def edit_message_text(
    session, chat_id, message_id: int, text: str, reply_markup=None
) -> dict | None:
    if not BOT_TOKEN:
        return None
    payload = {
        "chat_id": chat_id, "message_id": message_id,
        "text": text, "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json=payload
        ) as resp:
            return await resp.json()
    except Exception:
        logger.exception("edit_message_text failed chat_id=%s", chat_id)
        return None


async def delete_message(session, chat_id, message_id: int) -> None:
    if not BOT_TOKEN or not message_id:
        return
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
        ) as resp:
            await resp.read()
    except Exception:
        pass


async def answer_callback_query(
    session, callback_query_id: str, text: str | None = None, show_alert: bool = False
) -> dict | None:
    if not BOT_TOKEN:
        return None
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json=payload
        ) as resp:
            return await resp.json()
    except Exception:
        logger.exception("answer_callback_query failed id=%s", callback_query_id)
        return None


async def answer_inline_query(
    session, query_id: str, results: list,
    switch_pm_text: str | None = None, switch_pm_param: str | None = None,
    cache_time: int = 300,
) -> dict | None:
    if not BOT_TOKEN:
        return None
    payload = {
        "inline_query_id": query_id, "results": results,
        "cache_time": cache_time, "is_personal": True,
    }
    if switch_pm_text:
        payload["switch_pm_text"]      = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery", json=payload
        ) as resp:
            return await resp.json()
    except Exception:
        logger.exception("answer_inline_query failed id=%s", query_id)
        return None


async def copy_message(
    session, chat_id, from_chat_id, message_id: int, reply_markup=None
) -> dict | None:
    if not BOT_TOKEN:
        return None
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage", json=payload
        ) as resp:
            return await resp.json()
    except Exception:
        logger.exception("copy_message failed chat_id=%s", chat_id)
        return None


# ── UI / Keyboard Builders ────────────────────────────────────────────────────

def get_main_menu_kb(lang: str = "am") -> dict:
    return {
        "inline_keyboard": [
            [{"text": get_text(lang, "BTN_OPEN_APP"), "web_app": {"url": "https://almadih.vercel.app/"}}],
            [
                {"text": get_text(lang, "BTN_SEARCH"), "switch_inline_query_current_chat": ""},
                {"text": get_text(lang, "BTN_CATALOG"), "callback_data": "pg_1"},
            ],
            [
                {"text": get_text(lang, "BTN_PLAYLIST"), "callback_data": "pl_start"},
                {"text": get_text(lang, "BTN_FAV"), "switch_inline_query_current_chat": "#favorites"},
            ]
        ]
    }


def get_not_found_kb(lang: str = "am") -> dict:
    return {"inline_keyboard": [[{"text": get_text(lang, "BTN_CATALOG"), "callback_data": "pg_1"}]]}


def get_fuzzy_suggestions_kb(lang: str, suggestions: list[dict]) -> dict:
    buttons = [
        [{"text": f"🎵 {doc.get('display_name', 'Unknown')[:50]}", "callback_data": f"play_{str(doc['_id'])}"}]
        for doc in suggestions
    ]
    buttons.append([{"text": get_text(lang, "BTN_CATALOG"), "callback_data": "pg_1"}])
    return {"inline_keyboard": buttons}


def get_playlist_fuzzy_kb(lang: str, suggestions: list[dict]) -> dict:
    buttons = [
        [{"text": f"➕ {doc.get('display_name', 'Unknown')[:48]}", "callback_data": f"pl_add_{str(doc['_id'])}"}]
        for doc in suggestions
    ]
    buttons.append([{"text": get_text(lang, "BTN_CATALOG"), "callback_data": "pg_1"}])
    return {"inline_keyboard": buttons}


def get_playlist_builder_kb(lang: str, count: int) -> dict:
    done_label = f"✅ Save ({count}/10)"
    return {
        "inline_keyboard": [
            [{"text": done_label,   "callback_data": "pl_done"}],
            [{"text": "❌ Cancel",  "callback_data": "pl_cancel"}],
        ]
    }


def get_subscription_kb(lang: str, channels: list[dict]) -> dict:
    buttons = [
        [{"text": f"📢 {ch['username']}", "url": ch.get("url", f"https://t.me/{ch['username']}")}]
        for ch in channels
    ]
    buttons.append([{"text": get_text(lang, "BTN_VERIFY"), "callback_data": "check_subscription"}])
    return {"inline_keyboard": buttons}


def get_channel_mgmt_kb() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "➕ Add Channel",    "callback_data": "admin_ch_add"},
                {"text": "🗑 Remove Channel", "callback_data": "admin_ch_list"},
            ],
            [{"text": "❌ Close", "callback_data": "admin_ch_close"}],
        ]
    }


