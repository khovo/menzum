"""
handlers/message_handler.py
---------------------------
handle_message() — all text / audio / document message routing.

Order of dispatch:
  1. Resolve admin status (root or co-admin)
  2. Non-admin gates: banned → ignore; maintenance → notice; force-join
  3. /start (+ deep-link playlist resume)
  4. /list and "📂 Catalog (List)"
  5. "🔧 Manage Channels" (admin)
  6. playlist_builder state search
  7. admin slash-commands  → admin_commands.handle_admin_command
  8. admin panel / ingestion / states → admin_handlers.handle_admin_message
  9. generic audio search
"""
import logging

from db import (
    track_and_get_user,
    save_last_menu_msg_id,
    save_pending_start,
    build_search_query,
    get_fuzzy_suggestions,
    get_catalog_page,
    get_playlist,
    link_login_nonce,
    is_banned,
    get_maintenance,
)
from utils import (
    check_membership,
    send_message,
    send_audio,
    delete_message,
    get_not_found_kb,
    get_fuzzy_suggestions_kb,
    get_playlist_fuzzy_kb,
    get_subscription_kb,
)
from .helpers import (
    is_admin,
    _normalize_text,
    _react_to_message,
    _send_html_message,
    _get_main_menu_kb_local,
    _deliver_playlist,
    WELCOME_TEXT,
    BOT_USERNAME,
    _ADMIN_KB_TEXTS,
)
from .admin_handlers import handle_admin_message, show_channel_management
from .admin_commands import handle_admin_command

logger = logging.getLogger(__name__)

_MAINTENANCE_MSG = "🔧 ይቅርታ! Al-Madih አሁን በጥገና ላይ ነው። እባክዎ ቆይተው እንደገና ይሞክሩ።"


async def handle_message(session, db, message: dict, channels: list[dict]) -> None:
    chat_id    = message.get("chat", {}).get("id")
    user_info  = message.get("from", {})
    user_id    = user_info.get("id")
    text       = _normalize_text(message.get("text", ""))
    msg_id     = message.get("message_id")
    first_name = user_info.get("first_name", "User")

    user_data = await track_and_get_user(db, user_id, first_name)
    state     = user_data.get("state")

    # ── Mobile "Login with Telegram": /start login_<nonce> ──────────────────────
    # Handled before the gates so app login is never blocked. Links the nonce to
    # this Telegram user; the app's auth poll then issues a JWT.
    if text and text.startswith("/start login_"):
        nonce = text.split("login_", 1)[1].strip()
        await delete_message(session, chat_id, msg_id)
        linked = await link_login_nonce(db, nonce, user_id, first_name, user_info.get("username"))
        if linked:
            await send_message(session, chat_id, "✅ *Login successful!* ወደ Al-Madih መተግበሪያ (app) ይመለሱ።")
        else:
            await send_message(session, chat_id, "⚠️ This login link is invalid or has expired. Please start again from the app.")
        return

    admin = await is_admin(db, user_id)

    # ── Non-admin gates: ban, maintenance, then force-join ──────────────────────
    if not admin:
        if await is_banned(db, user_id):
            return  # banned users are silently ignored
        if await get_maintenance(db):
            await send_message(session, chat_id, _MAINTENANCE_MSG)
            return
        if not await check_membership(session, user_id, channels):
            parts       = text.split(" ", 1) if text.startswith("/start") else []
            start_param = parts[1].strip() if len(parts) > 1 else None
            if start_param:
                await save_pending_start(db, user_id, start_param)
            await send_message(
                session, chat_id,
                "**⚠️ አሰላሙ አለይኩም! ቦቱን ለመጠቀም እባክዎ መጀመሪያ ቻናላችንን ይቀላቀሉ።**",
                reply_markup=get_subscription_kb(channels),
            )
            return

    if text and (text == "/start" or text.startswith("/start ")):
        await delete_message(session, chat_id, msg_id)
        old_menu_id = user_data.get("last_menu_msg_id")
        if old_menu_id:
            await delete_message(session, chat_id, old_menu_id)

        parts       = text.split(" ", 1)
        start_param = parts[1].strip() if len(parts) > 1 else None
        if start_param and start_param.startswith("pl_"):
            playlist = await get_playlist(db, start_param)
            if playlist:
                await send_message(session, chat_id, f"🎧 *Playing playlist* `{start_param}` — {len(playlist.get('tracks', []))} tracks\n\n@{BOT_USERNAME}")
                await _deliver_playlist(session, db, chat_id, playlist)
                result = await _send_html_message(session, chat_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
                if result and result.get("ok"):
                    await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
                return

        result = await _send_html_message(session, chat_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
        if result and result.get("ok"):
            await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
        return

    if text in ("/list", "📂 Catalog (List)"):
        await delete_message(session, chat_id, msg_id)
        old_menu_id = (user_data or {}).get("last_menu_msg_id")
        if old_menu_id:
            await delete_message(session, chat_id, old_menu_id)
        msg_text, kb = await get_catalog_page(db, 1)
        result = await send_message(session, chat_id, msg_text, reply_markup=kb)
        if result and result.get("ok"):
            await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
        return

    if text == "🔧 Manage Channels" and admin:
        await show_channel_management(session, db, chat_id)
        return

    if state == "playlist_builder" and text and not text.startswith("/") and not (admin and text in _ADMIN_KB_TEXTS):
        await _react_to_message(session, chat_id, msg_id, "👀")
        sq  = build_search_query(text)
        doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})
        if doc:
            kb = {"inline_keyboard": [[{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{str(doc['_id'])}"}], [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}
            res = await send_audio(session, chat_id, doc["file_id"], f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", reply_markup=kb)
            if res and res.get("ok"):
                await _react_to_message(session, chat_id, res["result"]["message_id"], "🥰")
        else:
            suggestions = await get_fuzzy_suggestions(db, text, limit=5)
            if suggestions:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ በቀጥታ አልተገኘም።\n\n_ወደ ፕሌይሊስትዎ ለመጨመር ➕ ይጫኑ፦_", reply_markup=get_playlist_fuzzy_kb(suggestions))
            else:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ አልተገኘም።\nእባክዎ የተለየ ቃል ጽፈው ይሞክሩ።", reply_markup=get_not_found_kb())
        return

    if admin:
        if await handle_admin_command(session, db, message, chat_id, user_id, text, msg_id):
            return
        if await handle_admin_message(session, db, message, chat_id, user_id, text, msg_id, state):
            return

    if text and not text.startswith("/"):
        await _react_to_message(session, chat_id, msg_id, "👀")
        sq  = build_search_query(text)
        doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})

        if doc:
            matched_file_name = doc.get('display_name', 'Unknown')
            if not admin and not await check_membership(session, user_id, channels):
                hostage_msg = (
                    f"🎵 *{matched_file_name}* ተገኝቷል!\n\n"
                    "የፈለጉት መንዙማ ወይም PDF ፋይል ለማግኘት በመጀመሪያ ስለ ቦቱ አጠቃቀም መረጃ ሚለቀቅበት channel ይቀላቀሉ!"
                )
                await _send_html_message(session, chat_id, hostage_msg, reply_markup=get_subscription_kb(channels))
            else:
                kb = {"inline_keyboard": [[{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{str(doc['_id'])}"}], [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}
                res = await send_audio(session, chat_id, doc["file_id"], f"{matched_file_name}\n\n@{BOT_USERNAME}", reply_markup=kb)
                if res and res.get("ok"):
                    await _react_to_message(session, chat_id, res["result"]["message_id"], "🥰")
        else:
            suggestions = await get_fuzzy_suggestions(db, text, limit=5)
            if suggestions:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ በቀጥታ አልተገኘም።\n\n_ምናልባት ከታች ያሉት ሊሆኑ ይችላሉ? አንዱን ይምረጡ፦_", reply_markup=get_fuzzy_suggestions_kb(suggestions))
            else:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ አልተገኘም።\nእባክዎ የተለየ ቃል ጽፈው ይሞክሩ ወይም 'ሙሉ ዝርዝር' የሚለውን ይጫኑ።", reply_markup=get_not_found_kb())
