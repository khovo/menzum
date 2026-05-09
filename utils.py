"""
utils.py
--------
1. Telegram API wrappers  — thin async functions using a shared aiohttp session.
2. Cache helpers          — in-memory dicts; survive across warm Vercel invocations.
3. Async runner           — bridges Flask's sync WSGI world with async business logic.
4. UI keyboard builders   — reusable dict builders; keeps handlers.py free of raw dicts.

CHANGES FROM v2:
  - Added delete_message(): silent best-effort delete used by chat-cleanup logic.
  - Added send_media_group(): sends up to 10 audio files as a single Telegram
    media group — one API call, no sleep loops, Vercel-safe playlist delivery.
  - Updated get_main_menu_kb(): added "🎧 Create Playlist" button.
  - Added get_playlist_builder_kb(): control panel shown while building a playlist.
  - Added get_playlist_fuzzy_kb(): like get_fuzzy_suggestions_kb but buttons use
    `pl_add_` prefix so tapping a suggestion directly adds it to the playlist.
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
    """Wipe all cached membership results (call after channel list changes)."""
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
    """
    Returns True only if the user is a member of ALL configured channels.
    Fail-open: network errors or bad API responses count as "is member"
    so a misconfigured channel never locks everyone out.

    PERFORMANCE: previously used a serial for-loop — one HTTP round-trip per
    channel, sequential.  Now uses asyncio.gather to fire ALL getChatMember
    requests in parallel.  With N channels the wall-clock cost is now
    max(single_request_latency) instead of N * single_request_latency.
    """
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
        """True = member/ok/fail-open.  False = definitely not a member."""
        try:
            async with session.get(url, params={"chat_id": f"@{username}", "user_id": user_id}) as resp:
                res = await resp.json()
                if not res.get("ok"):
                    return True   # fail-open: bad response → let through
                return res["result"]["status"] in ("creator", "administrator", "member")
        except Exception:
            return True           # fail-open: network error → let through

    # Fire all channel checks concurrently — wall-clock = slowest single call
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
    """
    Send 2–10 media items (audio/photo/video/document) as a single grouped message.

    WHY this exists: Playlist delivery.  Sending 10 audio files via 10 separate
    sendAudio calls + asyncio.sleep() between each would risk Vercel's 10–30 s
    function timeout.  sendMediaGroup batches all tracks into ONE API round-trip,
    eliminating the timeout risk entirely.

    `media` format (InputMediaAudio):
      [{"type": "audio", "media": "file_id", "caption": "optional", "parse_mode": "Markdown"}, ...]

    Telegram requires 2–10 items.  Callers must validate length before calling.
    """
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
    """
    Best-effort message deletion.  Silently swallows all errors because:
      - The message may already be deleted (double-tap on /start)
      - Telegram only allows deleting messages < 48 hours old
      - A failed delete must NEVER crash the main handler flow

    Call with fire-and-forget confidence.
    """
    if not BOT_TOKEN or not message_id:
        return
    try:
        async with session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
        ) as resp:
            await resp.read()  # drain response, don't parse — we don't care
    except Exception:
        pass  # intentional: see docstring


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

def get_main_menu_kb() -> dict:
    """Main menu. WebApp button added alongside Playlist."""
    return {
        "inline_keyboard": [
            [
                {"text": "🌐 Open Al-Madih", "web_app": {"url": "https://almadih.vercel.app/"}}
            ],
            [
                {"text": "❤️ Favorites",      "switch_inline_query_current_chat": "#favorites"},
                {"text": "📂 Catalog (List)",  "callback_data": "pg_1"},
            ],
            [
                {"text": "🎧 Create Playlist", "callback_data": "pl_start"},
            ],
            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}],
        ]
    }


def get_not_found_kb() -> dict:
    """Hard not-found fallback: point user to the catalog."""
    return {"inline_keyboard": [[{"text": "📂 ሙሉ ዝርዝር (Catalog)", "callback_data": "pg_1"}]]}


def get_fuzzy_suggestions_kb(suggestions: list[dict]) -> dict:
    """
    One 🎵 tap-to-play button per fuzzy match, plus Catalog fallback.
    Used in normal (non-playlist) search mode.
    """
    buttons = [
        [{"text": f"🎵 {doc.get('display_name', 'Unknown')[:50]}", "callback_data": f"play_{str(doc['_id'])}"}]
        for doc in suggestions
    ]
    buttons.append([{"text": "📂 ሙሉ ዝርዝር (Catalog)", "callback_data": "pg_1"}])
    return {"inline_keyboard": buttons}


def get_playlist_fuzzy_kb(suggestions: list[dict]) -> dict:
    """
    Same layout as get_fuzzy_suggestions_kb but buttons use `pl_add_` prefix,
    so tapping a suggestion ADDS the track directly to the playlist under construction.
    Used only when state == 'playlist_builder'.
    """
    buttons = [
        [{"text": f"➕ {doc.get('display_name', 'Unknown')[:48]}", "callback_data": f"pl_add_{str(doc['_id'])}"}]
        for doc in suggestions
    ]
    buttons.append([{"text": "📂 ሙሉ ዝርዝር (Catalog)", "callback_data": "pg_1"}])
    return {"inline_keyboard": buttons}


def get_playlist_builder_kb(count: int) -> dict:
    """
    Control panel keyboard shown as an edited message while the user builds a playlist.
    count: current number of tracks added (0–10).
    """
    done_label = f"✅ Save Playlist ({count}/10)"
    return {
        "inline_keyboard": [
            [{"text": done_label,   "callback_data": "pl_done"}],
            [{"text": "❌ Cancel",  "callback_data": "pl_cancel"}],
        ]
    }


def get_subscription_kb(channels: list[dict]) -> dict:
    """One Join button per channel, then a Verify button."""
    buttons = [
        [{"text": f"📢 Join @{ch['username']}", "url": ch.get("url", f"https://t.me/{ch['username']}")}]
        for ch in channels
    ]
    buttons.append([{"text": "✅ ተቀላቅያለሁ (Verify)", "callback_data": "check_subscription"}])
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
