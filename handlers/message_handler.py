"""
handlers/message_handler.py
---------------------------
handle_message() — all text / audio / document message routing.

Order of dispatch (unchanged from the original monolith):
  1. Non-admin force-join membership gate
  2. /start (+ deep-link playlist resume)
  3. /list and "📂 Catalog (List)"
  4. "🔧 Manage Channels" (admin)
  5. playlist_builder state search
  6. admin message block (delegated to admin_handlers.handle_admin_message)
  7. generic audio search
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
    _is_admin,
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

logger = logging.getLogger(__name__)


async def handle_message(session, db, message: dict, channels: list[dict]) -> None:
    chat_id    = message.get("chat", {}).get("id")
    user_info  = message.get("from", {})
    user_id    = user_info.get("id")
    text       = _normalize_text(message.get("text", ""))
    msg_id     = message.get("message_id")
    first_name = user_info.get("first_name", "User")

    user_data = await track_and_get_user(db, user_id, first_name)
    state     = user_data.get("state")

    if not _is_admin(user_id):
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

    if text == "🔧 Manage Channels" and _is_admin(user_id):
        await show_channel_management(session, db, chat_id)
        return

    if state == "playlist_builder" and text and not text.startswith("/") and not (_is_admin(user_id) and text in _ADMIN_KB_TEXTS):
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

    if _is_admin(user_id):
        if await handle_admin_message(session, db, message, chat_id, user_id, text, msg_id, state):
            return

    if text and not text.startswith("/"):
        await _react_to_message(session, chat_id, msg_id, "👀")
        sq  = build_search_query(text)
        doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})

        if doc:
            matched_file_name = doc.get('display_name', 'Unknown')
            if not _is_admin(user_id) and not await check_membership(session, user_id, channels):
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
