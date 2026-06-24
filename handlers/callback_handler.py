"""
handlers/callback_handler.py
----------------------------
handle_callback() — all callback_data prefix routing for the bot.

Routes: play_, pdf_dl_, check_subscription, pl_start / pl_add_ / pl_done /
pl_cancel, pg_*, fav_, report_, broadcast_*, admin_ch_*.

Calls into broadcast_engine (broadcast confirm/edit) and helpers (HTML/menu
senders, playlist delivery, reactions).
"""
import os
import logging
from bson import ObjectId
from bson.errors import InvalidId

from config import ADMIN_ID
from db import (
    track_and_get_user,
    save_last_menu_msg_id,
    save_pending_start,
    toggle_favorite,
    get_user_data,
    set_user_state,
    get_catalog_page,
    get_force_channels,
    remove_force_channel,
    add_track_to_building_playlist,
    create_playlist,
    get_playlist,
    is_banned,
    get_maintenance,
)
from utils import (
    check_membership,
    invalidate_membership_cache,
    invalidate_all_membership_cache,
    invalidate_channels_cache,
    send_message,
    send_audio,
    edit_message_text,
    answer_callback_query,
    get_subscription_kb,
    get_channel_mgmt_kb,
    get_playlist_builder_kb,
)
from .helpers import (
    is_admin,
    _react_to_message,
    _send_html_message,
    _edit_html_message,
    _get_main_menu_kb_local,
    _deliver_playlist,
    _channel_mgmt_menu_text,
    WELCOME_TEXT,
    BOT_USERNAME,
)
from .broadcast_engine import _execute_broadcast, _bml_syntax_guide
from .admin_commands import handle_admin_delete_callback

logger = logging.getLogger(__name__)


async def handle_callback(session, db, cb: dict, channels: list[dict]) -> None:
    user       = cb["from"]
    user_id    = user["id"]
    cb_id      = cb["id"]
    data_str   = cb.get("data", "")
    # Messages chosen from inline mode arrive as callbacks WITHOUT a `message`
    # object (only `inline_message_id` + `from`). Fall back to the tapping
    # user's own chat so the ▶ Play / ❤️ Fav buttons on inline results still work.
    msg        = cb.get("message")
    chat_id    = msg["chat"]["id"] if msg else user_id
    message_id = msg["message_id"] if msg else None
    first_name = user.get("first_name", "User")

    user_data  = await track_and_get_user(db, user_id, first_name)

    admin = await is_admin(db, user_id)

    # ── Non-admin gates: banned → ignore; maintenance → blocked ─────────────────
    if not admin:
        if await is_banned(db, user_id):
            await answer_callback_query(session, cb_id)
            return
        if await get_maintenance(db):
            await answer_callback_query(session, cb_id, "🔧 ቦቱ አሁን በጥገና ላይ ነው።", show_alert=True)
            return

    # ── Admin delete confirmations (audio / pdf) ────────────────────────────────
    if data_str.startswith("del_audio_") or data_str.startswith("del_pdf_"):
        if admin:
            await handle_admin_delete_callback(session, db, data_str, chat_id, message_id, cb_id)
        else:
            await answer_callback_query(session, cb_id)
        return

    # ── Hook & Lock: Enforce join ONLY when trying to play audio or download PDF ──
    if data_str.startswith("play_") or data_str.startswith("pdf_dl_"):
        if not admin and not await check_membership(session, user_id, channels):
            await answer_callback_query(session, cb_id, "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!", show_alert=True)
            await send_message(
                session, chat_id,
                "የፈለጉት መንዙማ ወይም PDF ፋይል ለማግኘት በመጀመሪያ ስለ ቦቱ አጠቃቀም መረጃ ሚለቀቅበት channel ይቀላቀሉ!",
                reply_markup=get_subscription_kb(channels)
            )
            return

    if data_str != "check_subscription" and not admin:
        # We bypass global gatekeeper here, we only gatekeep specific actions like playback
        pass

    if data_str == "check_subscription":
        invalidate_membership_cache(user_id)
        if await check_membership(session, user_id, channels):
            await answer_callback_query(session, cb_id, "✅ እንኳን ደህና መጡ!")
            pending = user_data.get("pending_start")
            if pending and pending.startswith("pl_"):
                await save_pending_start(db, user_id, None)
                playlist = await get_playlist(db, pending)
                if playlist:
                    await edit_message_text(
                        session, chat_id, message_id,
                        f"🎧 *Playing playlist* `{pending}` — {len(playlist.get('tracks', []))} tracks\n\n@{BOT_USERNAME}",
                    )
                    await _deliver_playlist(session, db, chat_id, playlist)
                    result = await _send_html_message(session, chat_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
                    if result and result.get("ok"):
                        await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
                    return
            await _edit_html_message(session, chat_id, message_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
        else:
            await answer_callback_query(session, cb_id, "❌ አሁንም አልተቀላቀሉም! ቻናሉን Join ይበሉ", show_alert=True)
        return

    if data_str == "pl_start":
        await set_user_state(db, user_id, "playlist_builder", {"building_playlist": [], "pl_ctrl_msg_id": message_id})
        await edit_message_text(
            session, chat_id, message_id,
            "🎧 *የፕሌይሊስት ማዘጋጃ (Playlist Builder)* — 0/10\n\nየመንዙማውን ስም ይፈልጉ እና ➕ የሚለውን በመጫን ወደ ስብስብዎ ያክሉ።\n\n_እስከ 10 መንዙማ መምረጥ ይችላሉ። ሲጨርሱ ✅ Save የሚለውን ይጫኑ።_",
            reply_markup=get_playlist_builder_kb(0),
        )
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("pl_add_"):
        doc_id = data_str.split("pl_add_")[1]
        count  = await add_track_to_building_playlist(db, user_id, doc_id)
        if count == -2:
            await answer_callback_query(session, cb_id, "⚠️ Already in playlist!", show_alert=False)
            return
        if count == -1:
            await answer_callback_query(session, cb_id, "🎵 ከ 10 በላይ መንዙማ መጨመር አይቻልም!", show_alert=True)
            return

        await answer_callback_query(session, cb_id, f"➕ Added! ({count}/10)")
        user_data = await get_user_data(db, user_id)
        ctrl_msg_id = (user_data or {}).get("pl_ctrl_msg_id")
        if ctrl_msg_id:
            await edit_message_text(
                session, chat_id, ctrl_msg_id,
                f"🎧 *የፕሌይሊስት ማዘጋጃ (Playlist Builder)* — {count}/10\n\nየመንዙማውን ስም ይፈልጉ እና ➕ የሚለውን በመጫን ወደ ስብስብዎ ያክሉ።\n\n_እስከ 10 መንዙማ መምረጥ ይችላሉ። ሲጨርሱ ✅ Save የሚለውን ይጫኑ።_",
                reply_markup=get_playlist_builder_kb(count),
            )
        return

    if data_str == "pl_done":
        user_data   = await get_user_data(db, user_id)
        doc_ids     = (user_data or {}).get("building_playlist", [])
        if not doc_ids:
            await answer_callback_query(session, cb_id, "⚠️ ቢያንስ አንድ መንዙማ ያክሉ!", show_alert=True)
            return

        await answer_callback_query(session, cb_id, "⏳ Saving playlist...")
        playlist_id = await create_playlist(db, user_id, doc_ids)
        await set_user_state(db, user_id, "idle", {"building_playlist": [], "pl_ctrl_msg_id": None})

        if not playlist_id:
            await _edit_html_message(session, chat_id, message_id, "❌ Failed to save playlist.", reply_markup=_get_main_menu_kb_local())
            return

        deep_link = f"https://t.me/{BOT_USERNAME}?start={playlist_id}"
        share_text = f"✅ *Playlist Saved!*\n\n🔗 *Share this link:*\n`{deep_link}`\n\n_ይህን ሊንክ የሚጫን ማንኛውም ሰው ያዘጋጁትን Playlist ወዲያውኑ ማዳመጥ ይችላል!_"
        await edit_message_text(
            session, chat_id, message_id, share_text,
            reply_markup={"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "pg_close"}]]},
        )
        return

    if data_str == "pl_cancel":
        await set_user_state(db, user_id, "idle", {"building_playlist": [], "pl_ctrl_msg_id": None})
        await _edit_html_message(session, chat_id, message_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
        await answer_callback_query(session, cb_id, "❌ Playlist cancelled.")
        return

    if data_str.startswith("play_"):
        doc_id = data_str.split("play_")[1]
        try:
            file_doc = None
            if len(doc_id) == 24:
                try:
                    file_doc = await db.files.find_one(
                        {"_id": ObjectId(doc_id), "hidden": {"$ne": True}},
                        {"file_id": 1, "display_name": 1},
                    )
                except InvalidId:
                    file_doc = None

            if file_doc and file_doc.get("file_id"):
                kb = {
                    "inline_keyboard": [
                        [{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{doc_id}"}],
                        [{"text": "❤️ Fav", "callback_data": f"fav_{doc_id}"}],
                    ]
                }
                res = await send_audio(
                    session, chat_id, file_doc.get("file_id"),
                    f"🎵 {file_doc.get('display_name', 'Unknown')}\n\n@{BOT_USERNAME}",
                    reply_markup=kb,
                )
                if res and res.get("ok"):
                    await _react_to_message(session, chat_id, res["result"]["message_id"], "🥰")
                await answer_callback_query(session, cb_id)
            else:
                await answer_callback_query(session, cb_id, "⚠️ File not found", show_alert=True)
        except Exception:
            logger.exception("play_ callback failed for doc_id=%s", doc_id)
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    if data_str.startswith("pdf_dl_"):
        pdf_id = data_str.replace("pdf_dl_", "")
        try:
            pdf_doc = await db.pdfs.find_one({"_id": ObjectId(pdf_id), "hidden": {"$ne": True}})
            if pdf_doc and "file_id" in pdf_doc:
                bot_token = os.environ.get("BOT_TOKEN")
                url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                payload = {
                    "chat_id": chat_id,
                    "document": pdf_doc["file_id"],
                    "caption": f"📄 {pdf_doc.get('title', '')}\n\n✨ @{BOT_USERNAME}"
                }
                res_http = await session.post(url, json=payload)
                res_data = await res_http.json()
                if res_data and res_data.get("ok"):
                    await _react_to_message(session, chat_id, res_data["result"]["message_id"], "🥰")
                await db.pdfs.update_one({"_id": ObjectId(pdf_id)}, {"$inc": {"download_count": 1}})
            else:
                await answer_callback_query(session, cb_id, "❌ ይቅርታ፣ ፋይሉ አልተገኘም!", show_alert=True)
                return
        except Exception as e:
            logger.error(f"PDF DL Error: {e}")

        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("pg_"):
        if data_str == "pg_close":
            await _edit_html_message(session, chat_id, message_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
        else:
            new_page = int(data_str.split("_")[1])
            text, kb = await get_catalog_page(db, new_page)
            await edit_message_text(session, chat_id, message_id, text, reply_markup=kb)
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("fav_"):
        doc_id = data_str.split("fav_")[1]
        try:
            file_doc = None
            if len(doc_id) == 24:
                try:
                    file_doc = await db.files.find_one(
                        {"_id": ObjectId(doc_id), "hidden": {"$ne": True}},
                        {"_id": 1, "file_id": 1},
                    )
                except InvalidId:
                    file_doc = None

            if file_doc:
                added = await toggle_favorite(db, user_id, file_doc["file_id"])
                await answer_callback_query(session, cb_id, "❤️ Saved" if added else "💔 Removed")
            else:
                await answer_callback_query(session, cb_id, "⚠️ Missing")
        except Exception:
            logger.exception("fav_ callback failed for doc_id=%s", doc_id)
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    if data_str.startswith("report_"):
        doc_id = data_str.split("report_")[1]
        try:
            file_doc = await db.files.find_one({"_id": ObjectId(doc_id), "hidden": {"$ne": True}}, {"display_name": 1})
            if file_doc:
                await send_message(session, ADMIN_ID, f"🚨 Report: `{file_doc.get('display_name')}`\nID: `{doc_id}`")
                await answer_callback_query(session, cb_id, "✅ Reported!", show_alert=True)
        except Exception:
            pass
        return

    if data_str.startswith("broadcast_") and admin:
        if data_str == "broadcast_confirm":
            admin_data = await get_user_data(db, user_id)
            msg_id_bc  = (admin_data or {}).get("broadcast_msg_id")
            markup_bc  = (admin_data or {}).get("broadcast_markup")
            if msg_id_bc:
                await set_user_state(db, user_id, "idle")
                await edit_message_text(session, chat_id, message_id, "🚀 *Broadcasting…* please wait.")
                summary = await _execute_broadcast(session, db, chat_id, msg_id_bc, markup_bc)
                await send_message(session, chat_id, summary)

        elif data_str == "broadcast_cancel":
            await edit_message_text(session, chat_id, message_id, "❌ Broadcast cancelled.")
            await set_user_state(db, user_id, "idle")

        elif data_str == "broadcast_edit_markup":
            await set_user_state(db, user_id, "broadcast_markup_wait")
            await send_message(session, chat_id, _bml_syntax_guide())

        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("admin_ch_") and admin:
        if data_str == "admin_ch_menu":
            text = await _channel_mgmt_menu_text(db)
            await edit_message_text(session, chat_id, message_id, text, reply_markup=get_channel_mgmt_kb())
            await answer_callback_query(session, cb_id)
            return

        if data_str == "admin_ch_add":
            await set_user_state(db, user_id, "admin_add_channel_wait")
            await edit_message_text(
                session, chat_id, message_id,
                "📢 *Add Force-Join Channel*\n\nSend the channel username _(without @)_.\nExample: `Al_madih`",
                reply_markup={"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "admin_ch_menu"}]]},
            )
            await answer_callback_query(session, cb_id)
            return

        if data_str == "admin_ch_list":
            ch_list = await get_force_channels(db)
            if not ch_list:
                await answer_callback_query(session, cb_id, "No channels configured yet!", show_alert=True)
                return
            remove_buttons = [[{"text": f"❌ @{ch['username']}", "callback_data": f"admin_ch_del_{ch['username']}"}] for ch in ch_list]
            remove_buttons.append([{"text": "🔙 Back", "callback_data": "admin_ch_menu"}])
            await edit_message_text(
                session, chat_id, message_id,
                "🗑 *Remove a Channel*\nTap a channel to delete it from the force-join list.",
                reply_markup={"inline_keyboard": remove_buttons},
            )
            await answer_callback_query(session, cb_id)
            return

        if data_str.startswith("admin_ch_del_"):
            username = data_str.split("admin_ch_del_")[1]
            deleted  = await remove_force_channel(db, username)
            invalidate_channels_cache()
            invalidate_all_membership_cache()
            await answer_callback_query(session, cb_id, f"✅ @{username} removed." if deleted else f"⚠️ @{username} not found.")
            ch_list = await get_force_channels(db)
            if ch_list:
                remove_buttons = [[{"text": f"❌ @{ch['username']}", "callback_data": f"admin_ch_del_{ch['username']}"}] for ch in ch_list]
                remove_buttons.append([{"text": "🔙 Back", "callback_data": "admin_ch_menu"}])
                await edit_message_text(
                    session, chat_id, message_id,
                    "🗑 *Remove a Channel*\nTap a channel to delete it.",
                    reply_markup={"inline_keyboard": remove_buttons},
                )
            else:
                await edit_message_text(session, chat_id, message_id, await _channel_mgmt_menu_text(db), reply_markup=get_channel_mgmt_kb())
            return

        if data_str == "admin_ch_close":
            await edit_message_text(session, chat_id, message_id, "✅ Channel management closed.")
            await answer_callback_query(session, cb_id)
            return
