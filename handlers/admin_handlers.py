"""
handlers/admin_handlers.py
--------------------------
Admin-only message-side logic, extracted from the message router.

Holds:
  - show_channel_management() — the "🔧 Manage Channels" text command body
  - handle_admin_message()    — the admin message block (content ingestion,
    channel-add state, broadcast content/markup states, /admin panel commands,
    statistics, daily stats, total files, audio/voice upload)

handle_admin_message() returns True when it fully handled the message (the
original code path `return`ed), or False when the admin message fell through
to the generic search handler — preserving the original control flow exactly.
"""
import os
import re
import logging

from db import (
    get_daily_stats,
    add_force_channel,
    get_user_data,
    set_user_state,
)
from utils import (
    send_message,
    copy_message,
    get_channel_mgmt_kb,
    invalidate_channels_cache,
    invalidate_all_membership_cache,
)
from .helpers import _channel_mgmt_menu_text, _ADMIN_KB_TEXTS
from .broadcast_engine import _parse_bml, _bml_syntax_guide

logger = logging.getLogger(__name__)


async def show_channel_management(session, db, chat_id) -> None:
    mgmt_text = await _channel_mgmt_menu_text(db)
    result = await send_message(session, chat_id, mgmt_text, reply_markup=get_channel_mgmt_kb())
    if not result or result.get("ok") is not True:
        await send_message(session, chat_id, "API Error showing menu: " + str(result)[:200])


async def handle_admin_message(session, db, message, chat_id, user_id, text, msg_id, state) -> bool:
    if "document" in message:
        doc = message.get("document")
        fname = doc.get("file_name", "")

        if fname.lower().endswith((".pdf", ".txt", ".doc", ".docx", ".epub")):
            cap = message.get("caption", "").split("\n")[0].strip()
            clean_fname = os.path.splitext(fname)[0].strip()
            title = cap if cap else clean_fname

            try:
                await db.pdfs.update_one(
                    {"title": {"$regex": re.escape(title), "$options": "i"}},
                    {"$set": {"file_id": doc["file_id"], "title": title, "download_count": 0}},
                    upsert=True,
                )
                await send_message(session, chat_id, f"✅ Document Saved to DB:\n📄 `{title}`")
            except Exception as db_err:
                logger.error("db.pdfs.update_one failed: %s", db_err)
                await send_message(session, chat_id, f"❌ DB error saving Document `{title}`. Please retry.")
            return True

    if state == "admin_add_channel_wait":
        if text and not text.startswith("/"):
            username = text.lstrip("@").strip()
            added    = await add_force_channel(db, username)
            invalidate_channels_cache()
            invalidate_all_membership_cache()
            result_text = f"✅ `@{username}` added!" if added else f"⚠️ `@{username}` already exists."
            await send_message(
                session, chat_id, result_text,
                reply_markup={"inline_keyboard": [[{"text": "📢 Manage Channels", "callback_data": "admin_ch_menu"}]]},
            )
            await set_user_state(db, user_id, "idle")
        else:
            await send_message(session, chat_id, "⚠️ Please send a plain username, e.g. `Al_madih`.")
        return True

    if state == "broadcast_wait" and text not in _ADMIN_KB_TEXTS and msg_id:
        await set_user_state(
            db, user_id, "broadcast_markup_wait",
            {"broadcast_msg_id": msg_id},
        )
        await send_message(session, chat_id, _bml_syntax_guide())
        return True

    if state == "broadcast_markup_wait" and text not in _ADMIN_KB_TEXTS:
        admin_data = await get_user_data(db, user_id)
        bc_msg_id  = (admin_data or {}).get("broadcast_msg_id")

        if not bc_msg_id:
            await send_message(session, chat_id, "⚠️ Session lost. Please start over with 📢 Broadcast.")
            await set_user_state(db, user_id, "idle")
            return True

        skip_markup = text.strip().lower() in ("/skip", "skip")
        resolved_keyboard = None
        parse_errors: list[str] = []

        if not skip_markup:
            resolved_keyboard, parse_errors = await _parse_bml(db, text)

        reply_markup = {"inline_keyboard": resolved_keyboard} if resolved_keyboard else None

        await set_user_state(
            db, user_id, "broadcast_preview",
            {"broadcast_markup": reply_markup},
        )

        if parse_errors:
            warn_text = "⚠️ *Parse warnings (buttons with errors were skipped):*\n" + "\n".join(f"• {e}" for e in parse_errors)
            await send_message(session, chat_id, warn_text)

        await send_message(session, chat_id, "👁 *Live preview — this is exactly what users will receive:*")
        await copy_message(session, chat_id, chat_id, bc_msg_id, reply_markup=reply_markup)

        button_note = f"\n✅ *{sum(len(r) for r in resolved_keyboard)} button(s) attached across {len(resolved_keyboard)} row(s).*" if resolved_keyboard else "\n_(No buttons attached)_"

        await send_message(
            session, chat_id,
            f"Ready to broadcast to all users?{button_note}",
            reply_markup={
                "inline_keyboard": [
                    [{"text": "✅ Send to everyone", "callback_data": "broadcast_confirm"}, {"text": "✏️ Edit buttons", "callback_data": "broadcast_edit_markup"}],
                    [{"text": "❌ Cancel", "callback_data": "broadcast_cancel"}],
                ]
            },
        )
        return True

    if text == "/admin":
        await send_message(
            session, chat_id, "⚙️ *Admin Panel*",
            reply_markup={
                "keyboard": [[{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}], [{"text": "📢 Broadcast"}, {"text": "📂 Total Files"}], [{"text": "🔧 Manage Channels"}]],
                "resize_keyboard": True,
            },
        )
        return True

    if text == "📊 Statistics":
        u = await db.users.count_documents({})
        f = await db.files.count_documents({})
        await send_message(session, chat_id, f"👥 Users: `{u}`\n📂 Files: `{f}`")
        return True

    if text == "📅 Daily Stats":
        await send_message(session, chat_id, await get_daily_stats(db))
        return True

    if text == "📢 Broadcast":
        await set_user_state(db, user_id, "broadcast_wait")
        await send_message(
            session, chat_id,
            "📢 *Step 1 of 2 — Broadcast Content*\n\n"
            "Send the message you want to broadcast.\n"
            "Supported: text, photo, video, document, audio — anything Telegram supports.\n\n"
            "_After sending your content, I'll ask you to attach buttons (optional)._",
        )
        return True

    if text == "📂 Total Files":
        f_count = await db.files.count_documents({})
        await send_message(session, chat_id, f"📂 Total Files in DB: `{f_count}`")
        return True

    if "audio" in message or "voice" in message:
        f    = message.get("audio") or message.get("voice")
        cap  = message.get("caption", "").split("\n")[0].strip()
        name = cap if cap else f.get("file_name", "Unknown")
        if len(name) > 3:
            thumb_file_id = (message.get("audio", {}).get("thumbnail", {}).get("file_id") or message.get("audio", {}).get("thumb", {}).get("file_id"))
            update_fields = {"file_id": f["file_id"], "display_name": name}
            if thumb_file_id: update_fields["thumb_file_id"] = thumb_file_id
            try:
                await db.files.update_one({"display_name": {"$regex": re.escape(name), "$options": "i"}}, {"$set": update_fields}, upsert=True)
                thumb_status = " 🖼" if thumb_file_id else ""
                await send_message(session, chat_id, f"✅ Saved: `{name}`{thumb_status}")
            except Exception as db_err:
                logger.error("db.files.update_one failed: %s", db_err)
                await send_message(session, chat_id, f"❌ DB error saving `{name}`. Please retry.")
        return True

    return False
