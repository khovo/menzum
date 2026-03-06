"""
utils.py
--------
1. Telegram API wrappers  — thin async functions using a shared aiohttp session.
2. Cache helpers          — in-memory dicts; survive across warm Vercel invocations.
3. Async runner           — bridges Flask's sync WSGI world with async business logic.
4. UI keyboard builders   — reusable dict builders; keeps handlers.py free of raw dicts.

CHANGES FROM v1:
  - REMOVED dead import of FORCE_CHANNEL_USERNAME (constant deleted from config).
  - check_membership() now accepts `channels: list[dict]` instead of reading a
    hardcoded config constant.  User must be a member of ALL listed channels.
    Admin (_id == ADMIN_ID) is bypassed at the gate in handlers.py before this
    function is even called, so no admin-lockout risk.
  - Added channels-list cache (get/set/invalidate_channels_cache) and
    invalidate_all_membership_cache() for when the channel list changes.
  - get_subscription_kb() now accepts a list of channels and renders one
    Join button per channel, so multi-channel gates work out of the box.
  - Added get_fuzzy_suggestions_kb(): inline keyboard with one 🎵 button per
    fuzzy match, plus a fallback Catalog button at the bottom.
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
    Reusing a loop from a prior invocation causes 'Event loop is closed' crashes.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── In-Memory Caches ──────────────────────────────────────────────────────────

# Per-user membership result: { user_id: (is_member: bool, timestamp: float) }
MEMBERSHIP_CACHE: dict[int, tuple[bool, float]] = {}

# Latest-20 inline results for empty query
_INLINE_EMPTY_CACHE: dict = {"data": [], "time": 0.0}

# Force-join channel list from DB (refreshed every CHANNELS_CACHE_TTL seconds)
_CHANNELS_CACHE: dict = {"data": None, "time": 0.0}


# ── Inline Empty Cache ───────────────────────────────────────────────────────

def get_inline_empty_cache() -> list | None:
    """Return cached empty-query inline results if still fresh, else None."""
    if _INLINE_EMPTY_CACHE["data"] and (
        time.time() - _INLINE_EMPTY_CACHE["time"] < INLINE_EMPTY_CACHE_TTL
    ):
        return _INLINE_EMPTY_CACHE["data"]
    return None


def set_inline_empty_cache(results: list) -> None:
    _INLINE_EMPTY_CACHE["data"] = results
    _INLINE_EMPTY_CACHE["time"] = time.time()


# ── Membership Cache ─────────────────────────────────────────────────────────

def invalidate_membership_cache(user_id: int) -> None:
    """Evict a single user's cached membership result (used on verify button)."""
    MEMBERSHIP_CACHE.pop(user_id, None)


def invalidate_all_membership_cache() -> None:
    """
    Wipe ALL cached membership results.
    Must be called whenever the channel list changes (add / remove) so that
    users are re-evaluated against the new set of channels on their next request.
    """
    MEMBERSHIP_CACHE.clear()


# ── Channels List Cache ───────────────────────────────────────────────────────

def get_channels_cache() -> list | None:
    """Return the cached channel list if still fresh, else None."""
    if _CHANNELS_CACHE["data"] is not None and (
        time.time() - _CHANNELS_CACHE["time"] < CHANNELS_CACHE_TTL
    ):
        return _CHANNELS_CACHE["data"]
    return None


def set_channels_cache(channels: list) -> None:
    _CHANNELS_CACHE["data"] = channels
    _CHANNELS_CACHE["time"] = time.time()


def invalidate_channels_cache() -> None:
    """Force the next request to re-fetch channels from DB."""
    _CHANNELS_CACHE["data"] = None


# ── Telegram API Helpers ──────────────────────────────────────────────────────

async def check_membership(session, user_id: int, channels: list[dict]) -> bool:
    """
    Return True if `user_id` is a member of ALL channels in the list.

    Design decisions:
    - No channels configured → return True (open-access mode, fail-open).
    - Per-user result is cached for MEMBERSHIP_CACHE_TTL seconds to avoid
      hammering Telegram's getChatMember on every message.
    - Fail-open on any network error or Telegram API error for a specific
      channel, so a misconfigured channel doesn't lock out everyone.
    - User must be in ALL channels (AND logic), not just one.
    """
    if not BOT_TOKEN or not channels:
        return True

    now    = time.time()
    cached = MEMBERSHIP_CACHE.get(user_id)
    if cached:
        is_member, ts = cached
        if now - ts < MEMBERSHIP_CACHE_TTL:
            return is_member

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"

    for ch in channels:
        username = ch.get("username", "").strip()
        if not username:
            continue
        params = {"chat_id": f"@{username}", "user_id": user_id}
        try:
            async with session.get(url, params=params) as resp:
                res = await resp.json()
                if not res.get("ok"):
                    continue  # fail-open for this channel
                status = res["result"]["status"]
                if status not in ("creator", "administrator", "member"):
                    # User is NOT in this channel → cache False and short-circuit
                    MEMBERSHIP_CACHE[user_id] = (False, now)
                    return False
        except Exception:
            continue  # fail-open on network error

    # Passed all channels
    MEMBERSHIP_CACHE[user_id] = (True, now)
    return True


async def send_message(session, chat_id, text: str, reply_markup=None) -> dict | None:
    if not BOT_TOKEN:
        return None
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
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
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    payload = {
        "chat_id":       chat_id,
        "audio":         audio_file_id,
        "caption":       caption,
        "parse_mode":    "Markdown",
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
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id":                 chat_id,
        "message_id":              message_id,
        "text":                    text,
        "parse_mode":              "Markdown",
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
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
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
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    payload = {
        "inline_query_id": query_id,
        "results":         results,
        "cache_time":      cache_time,
        "is_personal":     True,
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
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
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
    return {
        "inline_keyboard": [
            [
                {"text": "❤️ Favorites",    "switch_inline_query_current_chat": "#favorites"},
                {"text": "📂 Catalog (List)", "callback_data": "pg_1"},
            ],
            [{"text": "📞 አስተያየት ለመስጠት (Support)", "callback_data": "support_start"}],
            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}],
        ]
    }


def get_not_found_kb() -> dict:
    """Last-resort fallback: no fuzzy results at all → point to catalog."""
    return {
        "inline_keyboard": [
            [{"text": "📂 ሙሉ ዝርዝር (Catalog)", "callback_data": "pg_1"}]
        ]
    }


def get_fuzzy_suggestions_kb(suggestions: list[dict]) -> dict:
    """
    Inline keyboard for smart search suggestions.
    Each suggestion becomes a 🎵 button whose callback triggers audio playback
    via the `play_{doc_id}` callback handler — no second text round-trip needed.
    A Catalog fallback button is always appended at the bottom.

    Display name is truncated to 50 chars to respect Telegram's 64-byte
    callback_data limit (ObjectId = 24 bytes; prefix = 5 bytes → 29 bytes used).
    """
    buttons = [
        [{
            "text":          f"🎵 {doc.get('display_name', 'Unknown')[:50]}",
            "callback_data": f"play_{str(doc['_id'])}",
        }]
        for doc in suggestions
    ]
    buttons.append([{"text": "📂 ሙሉ ዝርዝር (Catalog)", "callback_data": "pg_1"}])
    return {"inline_keyboard": buttons}


def get_subscription_kb(channels: list[dict]) -> dict:
    """
    Force-join keyboard.  One [Join …] button per channel, then a Verify button.
    Accepts the dynamic channel list loaded from DB.
    """
    buttons = [
        [{"text": f"📢 Join @{ch['username']}", "url": ch.get("url", f"https://t.me/{ch['username']}")}]
        for ch in channels
    ]
    buttons.append([{"text": "✅ ተቀላቅያለሁ (Verify)", "callback_data": "check_subscription"}])
    return {"inline_keyboard": buttons}


def get_channel_mgmt_kb() -> dict:
    """Top-level channel management menu (shown from admin panel)."""
    return {
        "inline_keyboard": [
            [
                {"text": "➕ Add Channel",      "callback_data": "admin_ch_add"},
                {"text": "🗑 Remove Channel",   "callback_data": "admin_ch_list"},
            ],
            [{"text": "❌ Close", "callback_data": "admin_ch_close"}],
        ]
    }
