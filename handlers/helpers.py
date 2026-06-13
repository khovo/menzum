"""
handlers/helpers.py
-------------------
Shared constants and low-level helpers used across all handler modules.

Holds:
  - Constants: BOT_USERNAME, WELCOME_TEXT, _ADMIN_KB_TEXTS
  - Predicates: _is_admin(), _normalize_text()
  - HTML/keyboard helpers: _get_main_menu_kb_local(), _send_html_message(),
    _edit_html_message(), _react_to_message()
  - Composite senders: _send_menu(), _deliver_playlist(), _channel_mgmt_menu_text()

This module is a leaf: it imports only from config / db / utils, never from the
other handler modules, so it can be safely imported everywhere.
"""
import os
import logging

from config import BOT_TOKEN, ADMIN_ID
from db import save_last_menu_msg_id, increment_playlist_plays, get_force_channels, is_co_admin
from utils import send_message, send_audio, send_media_group

logger = logging.getLogger(__name__)

BOT_USERNAME = os.environ.get("BOT_USERNAME", "Almadihbot")

WELCOME_TEXT = (
    "<tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji> አሰላሙ አለይኩም! ወደ Al-Madih ቦት እንኳን በደህና መጡ። <tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji>\n\n"
    "<tg-emoji emoji-id=\"5337110598926766115\">⭐️</tg-emoji> የሚፈልጉትን መንዙማ ወይም ነሺዳ ርዕስ አሁኑኑ ጽፈው ይላኩ። <tg-emoji emoji-id=\"5384110834068783570\">💬</tg-emoji>\n\n"
    "<tg-emoji emoji-id=\"5384111778961588478\">⚡️</tg-emoji> ፈልግ (Search)\n"
    "<tg-emoji emoji-id=\"5384485342332093352\">⚡️</tg-emoji> ማውጫ (Catalog)\n"
    "<tg-emoji emoji-id=\"4904882772637648609\">⏰</tg-emoji> ፕሌይሊስት (Playlist)\n"
    "<tg-emoji emoji-id=\"5116368680279606270\">♥️</tg-emoji> ተወዳጆች (Favorites)"
)

_ADMIN_KB_TEXTS = {
    "📊 Statistics",
    "📅 Daily Stats",
    "📢 Broadcast",
    "📂 Total Files",
    "🔧 Manage Channels",
}


def _is_admin(user_id) -> bool:
    """Root admin only (synchronous, ADMIN_ID env)."""
    return str(user_id) == str(ADMIN_ID)


async def is_admin(db, user_id) -> bool:
    """True for the root admin (ADMIN_ID) OR any co-admin in the admins
    collection. Use this for all admin gating so co-admins get full access."""
    if _is_admin(user_id):
        return True
    return await is_co_admin(db, user_id)


def _normalize_text(text: str) -> str:
    return text.replace("️", "").replace("︎", "")


# ─────────────────────────────────────────────────────────────────────────────
#  CUSTOM LOCAL HELPERS FOR HTML TEXT & REACTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _get_main_menu_kb_local() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "🌐 Open Al-Madih", "web_app": {"url": "https://almadih.vercel.app/"}}],
            [
                {"text": "🔍 ፈልግ (Search)", "switch_inline_query_current_chat": ""},
                {"text": "📂 ማውጫ (Catalog)", "callback_data": "pg_1"},
            ],
            [
                {"text": "🎧 ፕሌይሊስት (Playlist)", "callback_data": "pl_start"},
                {"text": "❤️ ተወዳጆች (Favorites)", "switch_inline_query_current_chat": "#favorites"},
            ]
        ]
    }


async def _send_html_message(session, chat_id, text: str, reply_markup=None) -> dict | None:
    if not BOT_TOKEN: return None
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload) as resp:
            return await resp.json()
    except Exception:
        return None


async def _edit_html_message(session, chat_id, message_id: int, text: str, reply_markup=None) -> dict | None:
    if not BOT_TOKEN: return None
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json=payload) as resp:
            return await resp.json()
    except Exception:
        return None


async def _react_to_message(session, chat_id: int, message_id: int, emoji: str):
    if not BOT_TOKEN: return
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}]
    }
    try:
        async with session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction", json=payload) as resp:
            await resp.read()
    except Exception as e:
        print(f"Failed to set reaction: {e}")


async def _channel_mgmt_menu_text(db) -> str:
    channels = await get_force_channels(db)
    text = "📢 *Channel Management*\n\n"
    if channels:
        text += "\n".join(f"• `@{ch['username']}`" for ch in channels) + "\n"
    else:
        text += "No channels configured. Bot is in open access mode.\n"
    return text + "\nWhat would you like to do?"


async def _send_menu(session, db, chat_id, user_id: int, user_data: dict | None) -> None:
    result  = await _send_html_message(session, chat_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
    if result and result.get("ok"):
        await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])


async def _deliver_playlist(session, db, chat_id, playlist: dict) -> None:
    tracks = playlist.get("tracks", [])
    if not tracks:
        await send_message(session, chat_id, "⚠️ ፕሌይሊስቱ ባዶ ነው! ቢያንስ አንድ መንዙማ ያክሉ።")
        return

    playlist_id = playlist["_id"]
    creator_id  = playlist.get("creator_id", "")

    if len(tracks) == 1:
        t  = tracks[0]
        kb = {"inline_keyboard": [[{"text": "❤️ Fav", "switch_inline_query_current_chat": t["name"][:30]}]]}
        res = await send_audio(
            session, chat_id, t["file_id"],
            f"🎵 {t['name']}\n\n📋 Playlist by user {creator_id}\n@{BOT_USERNAME}",
            reply_markup=kb,
        )
        if res and res.get("ok"):
            await _react_to_message(session, chat_id, res["result"]["message_id"], "🥰")
    else:
        media = []
        for i, t in enumerate(tracks):
            item = {"type": "audio", "media": t["file_id"]}
            if i == 0:
                item["caption"]    = (
                    f"🎧 *Playlist* — {len(tracks)} tracks\n"
                    f"📋 Shared via @{BOT_USERNAME}"
                )
                item["parse_mode"] = "Markdown"
            media.append(item)
        res = await send_media_group(session, chat_id, media)
        if res and res.get("ok") and isinstance(res.get("result"), list) and len(res["result"]) > 0:
            await _react_to_message(session, chat_id, res["result"][0]["message_id"], "🥰")

    await increment_playlist_plays(db, playlist_id)
