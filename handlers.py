"""
handlers.py
-----------
Pure business logic.
"""
import asyncio
import logging
import os
import re
from bson import ObjectId
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient

from config import BOT_TOKEN, MONGO_URL, DB_NAME, ADMIN_ID
from db import (
    track_and_get_user,
    save_last_menu_msg_id,
    save_pending_start,
    toggle_favorite,
    get_user_data,
    set_user_state,
    build_search_query,
    get_fuzzy_suggestions,
    get_catalog_page,
    get_daily_stats,
    get_force_channels,
    add_force_channel,
    remove_force_channel,
    add_track_to_building_playlist,
    create_playlist,
    get_playlist,
    increment_playlist_plays,
)
from utils import (
    check_membership,
    invalidate_membership_cache,
    invalidate_all_membership_cache,
    get_channels_cache,
    set_channels_cache,
    invalidate_channels_cache,
    send_message,
    send_audio,
    send_media_group,
    edit_message_text,
    delete_message,
    answer_callback_query,
    answer_inline_query,
    copy_message,
    get_inline_empty_cache,
    set_inline_empty_cache,
    get_main_menu_kb,
    get_not_found_kb,
    get_fuzzy_suggestions_kb,
    get_playlist_fuzzy_kb,
    get_playlist_builder_kb,
    get_subscription_kb,
    get_channel_mgmt_kb,
)

logger = logging.getLogger(__name__)

# Bot username for deep links.  Set BOT_USERNAME in Vercel env vars.
BOT_USERNAME = os.environ.get("BOT_USERNAME", "Almadihbot")

WELCOME_TEXT = (
    "*🌙 አሰላሙ አለይኩም ወረህመቱላሂ ወበረካትሁ! 🌙*\n\n"
    "እንኳን ወደ **አል-ማዲህ (Al-Madih)** የቴሌግራም ቦት በደህና መጡ! 🕌\n\n"
    "ይህ ቦት ምርጥ ምርጥ መንዙማዎችን እና ነሺዳዎችን በቀላሉ የሚያገኙበት ትልቅ ማህደር ነው።\n\n"
    "💡 *እንዴት መጠቀም ይችላሉ?*\n"
    "🔍 **ፈልግ (Search):** የሚፈልጉትን መንዙማ ርዕስ በቀጥታ ይጻፉ。\n"
    "📂 **ሙሉ ዝርዝር (Catalog):** ሁሉንም መንዙማዎች በገጽ እየገለጡ ለማየት。\n"
    "🎧 **ፕሌይሊስት (Playlist):** የራስዎን ተወዳጅ ስብስብ ፈጥረው ለወዳጅዎ ለማጋራት。\n"
    "❤️ **የምወዳቸው (Favorites):** ወደፊት ቶሎ ለማግኘት የሚወዷቸውን ነጥለው ለማስቀመጥ。\n\n"
    "_መንዙማ ለማግኘት አሁኑኑ ስም ጽፈው ይላኩ!_ 📿"
)

def _is_admin(user_id) -> bool:
    return str(user_id) == str(ADMIN_ID)

def _normalize_text(text: str) -> str:
    return text.replace("️", "").replace("︎", "")

_ADMIN_KB_TEXTS = {
    "📊 Statistics",
    "📅 Daily Stats",
    "📢 Broadcast",
    "📂 Total Files",
    "🔧 Manage Channels",
}

async def _channel_mgmt_menu_text(db) -> str:
    channels = await get_force_channels(db)
    text = "📢 *Channel Management*\n\n"
    if channels:
        # Wrapped in backticks to prevent markdown errors from underscores in usernames
        text += "\n".join(f"• `@{ch['username']}`" for ch in channels) + "\n"
    else:
        text += "No channels configured. Bot is in open access mode.\n"
    return text + "\nWhat would you like to do?"

async def _send_menu(session, db, chat_id, user_id: int, user_data: dict | None) -> None:
    result  = await send_message(session, chat_id, WELCOME_TEXT, reply_markup=get_main_menu_kb())
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
        await send_audio(
            session, chat_id, t["file_id"],
            f"🎵 {t['name']}\n\n📋 Playlist by user {creator_id}\n@{BOT_USERNAME}",
            reply_markup=kb,
        )
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
        await send_media_group(session, chat_id, media)

    await increment_playlist_plays(db, playlist_id)

async def handle_callback(session, db, cb: dict, channels: list[dict]) -> None:
    user       = cb["from"]
    user_id    = user["id"]
    cb_id      = cb["id"]
    data_str   = cb.get("data", "")
    chat_id    = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    first_name = user.get("first_name", "User")

    user_data  = await track_and_get_user(db, user_id, first_name)

    if data_str != "check_subscription" and not _is_admin(user_id):
        if not await check_membership(session, user_id, channels):
            await answer_callback_query(session, cb_id, "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!", show_alert=True)
            return

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
                    result = await send_message(session, chat_id, WELCOME_TEXT, reply_markup=get_main_menu_kb())
                    if result and result.get("ok"):
                        await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
                    return
            await edit_message_text(session, chat_id, message_id, WELCOME_TEXT, reply_markup=get_main_menu_kb())
        else:
            await answer_callback_query(session, cb_id, "❌ አሁንም አልተቀላቀሉም! ቻናሉን Join ይበሉ", show_alert=True)
        return

    if data_str == "support_start":
        await set_user_state(db, user_id, "support_wait")
        await edit_message_text(
            session, chat_id, message_id,
            "📝 **አስተያየትዎን ወይም ጥያቄዎን እዚህ ይጻፉ...**\n_(ወደ ዋናው ገጽ ለመመለስ 'ተመለስ' የሚለውን ይጫኑ)_",
            reply_markup={"inline_keyboard": [[{"text": "🔙 ተመለስ", "callback_data": "support_cancel"}]]},
        )
        await answer_callback_query(session, cb_id)
        return

    if data_str == "support_cancel":
        await set_user_state(db, user_id, "idle")
        await edit_message_text(session, chat_id, message_id, WELCOME_TEXT, reply_markup=get_main_menu_kb())
        await answer_callback_query(session, cb_id)
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
            await edit_message_text(session, chat_id, message_id, "❌ Failed to save playlist.", reply_markup=get_main_menu_kb())
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
        await edit_message_text(session, chat_id, message_id, WELCOME_TEXT, reply_markup=get_main_menu_kb())
        await answer_callback_query(session, cb_id, "❌ Playlist cancelled.")
        return

    if data_str.startswith("play_"):
        doc_id = data_str.split("play_")[1]
        try:
            file_doc = await db.files.find_one({"_id": ObjectId(doc_id)}, {"file_id": 1, "display_name": 1}) if len(doc_id) == 24 else None
            if file_doc:
                kb = {"inline_keyboard": [[{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{doc_id}"}], [{"text": "❤️ Fav", "callback_data": f"fav_{doc_id}"}]]}
                await send_audio(session, chat_id, file_doc["file_id"], f"{file_doc.get('display_name')}\n\n@{BOT_USERNAME}", reply_markup=kb)
                await answer_callback_query(session, cb_id)
            else:
                await answer_callback_query(session, cb_id, "⚠️ File not found", show_alert=True)
        except Exception:
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    if data_str.startswith("reply_") and _is_admin(user_id):
        target_user_id = data_str.split("_")[1]
        await set_user_state(db, user_id, "admin_reply_wait", {"target_user_id": target_user_id})
        await send_message(session, chat_id, f"📝 **መልስ ለተጠቃሚ {target_user_id} እየጻፉ ነው:**\n\nመልእክቱን ይጻፉ (Text, Voice, Photo...).")
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("pg_"):
        if data_str == "pg_close":
            await edit_message_text(session, chat_id, message_id, WELCOME_TEXT, reply_markup=get_main_menu_kb())
        else:
            new_page = int(data_str.split("_")[1])
            text, kb = await get_catalog_page(db, new_page)
            await edit_message_text(session, chat_id, message_id, text, reply_markup=kb)
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("fav_"):
        doc_id = data_str.split("fav_")[1]
        try:
            file_doc = await db.files.find_one({"_id": ObjectId(doc_id)}, {"_id": 1, "file_id": 1}) if len(doc_id) == 24 else None
            if file_doc:
                added = await toggle_favorite(db, user_id, file_doc["file_id"])
                await answer_callback_query(session, cb_id, "❤️ Saved" if added else "💔 Removed")
            else:
                await answer_callback_query(session, cb_id, "⚠️ Missing")
        except Exception:
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    if data_str.startswith("report_"):
        doc_id = data_str.split("report_")[1]
        try:
            file_doc = await db.files.find_one({"_id": ObjectId(doc_id)}, {"display_name": 1})
            if file_doc:
                await send_message(session, ADMIN_ID, f"🚨 Report: `{file_doc.get('display_name')}`\nID: `{doc_id}`")
                await answer_callback_query(session, cb_id, "✅ Reported!", show_alert=True)
        except Exception:
            pass
        return

    if data_str.startswith("broadcast_") and _is_admin(user_id):
        if data_str == "broadcast_confirm":
            admin_data = await get_user_data(db, user_id)
            msg_id     = (admin_data or {}).get("broadcast_msg_id")
            markup     = (admin_data or {}).get("broadcast_markup")
            if msg_id:
                await edit_message_text(session, chat_id, message_id, "🚀 Sending...")
                count = 0
                async for u in db.users.find({}, {"_id": 1}):
                    try:
                        await copy_message(session, u["_id"], chat_id, msg_id, reply_markup=markup)
                        count += 1
                        await asyncio.sleep(0.05)
                    except Exception:
                        pass
                await send_message(session, chat_id, f"✅ Sent to {count} users.")
                await set_user_state(db, user_id, "idle")
        elif data_str == "broadcast_cancel":
            await edit_message_text(session, chat_id, message_id, "❌ Broadcast cancelled.")
            await set_user_state(db, user_id, "idle")
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("admin_ch_") and _is_admin(user_id):
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
                result = await send_message(session, chat_id, WELCOME_TEXT, reply_markup=get_main_menu_kb())
                if result and result.get("ok"):
                    await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
                return

        result = await send_message(session, chat_id, WELCOME_TEXT, reply_markup=get_main_menu_kb())
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
        mgmt_text = await _channel_mgmt_menu_text(db)
        result = await send_message(session, chat_id, mgmt_text, reply_markup=get_channel_mgmt_kb())
        # Safe error checker with NO markdown
        if not result or result.get("ok") is not True:
            await send_message(session, chat_id, "API Error showing menu: " + str(result)[:200])
        return

    if state == "support_wait":
        if text == "/start":
            await set_user_state(db, user_id, "idle")
            await send_message(session, chat_id, "🏠 ወደ ዋናው ገጽ ተመልሰዋል።", reply_markup=get_main_menu_kb())
            return
        kb = {"inline_keyboard": [[{"text": "↩️ መልስ ለመስጠት (Reply)", "callback_data": f"reply_{user_id}"}]]}
        await send_message(session, ADMIN_ID, f"📩 **New Feedback from:** {first_name} (`{user_id}`)", reply_markup=kb)
        await copy_message(session, ADMIN_ID, chat_id, msg_id)
        await send_message(session, chat_id, "✅ **መልእክትዎ ደርሶናል!** ጀዛኩሙላሁ ኸይረን!\n\n_ወደ ዋናው ገጽ ተመልሰዋል።_", reply_markup=get_main_menu_kb())
        await set_user_state(db, user_id, "idle")
        return

    if state == "playlist_builder" and text and not text.startswith("/") and not (_is_admin(user_id) and text in _ADMIN_KB_TEXTS):
        sq  = build_search_query(text)
        doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})
        if doc:
            kb = {"inline_keyboard": [[{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{str(doc['_id'])}"}], [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}
            await send_audio(session, chat_id, doc["file_id"], f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", reply_markup=kb)
        else:
            suggestions = await get_fuzzy_suggestions(db, text, limit=5)
            if suggestions:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ በቀጥታ አልተገኘም።\n\n_ወደ ፕሌይሊስትዎ ለመጨመር ➕ ይጫኑ፦_", reply_markup=get_playlist_fuzzy_kb(suggestions))
            else:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ አልተገኘም።\nእባክዎ የተለየ ቃል ጽፈው ይሞክሩ።", reply_markup=get_not_found_kb())
        return

    if _is_admin(user_id):
        if state == "admin_add_channel_wait":
            if text and not text.startswith("/"):
                username = text.lstrip("@").strip()
                added    = await add_force_channel(db, username)
                invalidate_channels_cache()
                invalidate_all_membership_cache()
                # Wrapped in backticks to protect from markdown errors
                result_text = f"✅ `@{username}` added!" if added else f"⚠️ `@{username}` already exists."
                await send_message(
                    session, chat_id, result_text,
                    reply_markup={"inline_keyboard": [[{"text": "📢 Manage Channels", "callback_data": "admin_ch_menu"}]]},
                )
                await set_user_state(db, user_id, "idle")
            else:
                await send_message(session, chat_id, "⚠️ Please send a plain username, e.g. `Al_madih`.")
            return

        if state == "admin_reply_wait" and text not in _ADMIN_KB_TEXTS:
            target_user = (user_data or {}).get("target_user_id")
            if target_user:
                try:
                    await send_message(session, target_user, "🔔 **ከአድሚኑ የተሰጠ መልስ:**")
                    await copy_message(session, target_user, chat_id, msg_id)
                    await send_message(session, chat_id, "✅ መልሱ ተልኳል!")
                except Exception as e:
                    await send_message(session, chat_id, f"❌ አልተላከም: {e}")
                await set_user_state(db, user_id, "idle")
            return

        if state == "broadcast_wait" and text != "🔙 Back" and text not in _ADMIN_KB_TEXTS and msg_id:
            await set_user_state(
                db, user_id, "broadcast_confirm",
                {"broadcast_msg_id": msg_id, "broadcast_markup": message.get("reply_markup")},
            )
            await copy_message(session, chat_id, chat_id, msg_id, reply_markup=message.get("reply_markup"))
            await send_message(
                session, chat_id, "Confirm broadcast?",
                reply_markup={"inline_keyboard": [[{"text": "✅ Post", "callback_data": "broadcast_confirm"}], [{"text": "❌ Cancel", "callback_data": "broadcast_cancel"}]]},
            )
            return

        if text == "/admin":
            await send_message(
                session, chat_id, "⚙️ *Admin Panel*",
                reply_markup={
                    "keyboard": [[{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}], [{"text": "📢 Broadcast"}, {"text": "📂 Total Files"}], [{"text": "🔧 Manage Channels"}]],
                    "resize_keyboard": True,
                },
            )
            return

        if text == "📊 Statistics":
            u = await db.users.count_documents({})
            f = await db.files.count_documents({})
            await send_message(session, chat_id, f"👥 Users: `{u}`\n📂 Files: `{f}`")
            return

        if text == "📅 Daily Stats":
            await send_message(session, chat_id, await get_daily_stats(db))
            return

        if text == "📢 Broadcast":
            await set_user_state(db, user_id, "broadcast_wait")
            await send_message(session, chat_id, "📢 Send the message you want to broadcast.")
            return

        if text == "📂 Total Files":
            f_count = await db.files.count_documents({})
            await send_message(session, chat_id, f"📂 Total Files in DB: `{f_count}`")
            return

        if "audio" in message or "voice" in message:
            f    = message.get("audio") or message.get("voice")
            cap  = message.get("caption", "").split("\n")[0].strip()
            name = cap if cap else f.get("file_name", "Unknown")
            if len(name) > 3:
                # ── Safe thumbnail extraction ────────────────────────────────
                # Telegram audio objects MAY carry a thumbnail (PhotoSize).
                # Voice messages never do. We use chained .get() so a missing
                # key at any level silently produces None — never a KeyError.
                # The DB write happens whether or not a thumbnail exists.
                thumb_file_id = (
                    message.get("audio", {})
                           .get("thumbnail", {})
                           .get("file_id")
                    or
                    message.get("audio", {})
                           .get("thumb", {})   # legacy field name, still sent by some clients
                           .get("file_id")
                )  # None if audio has no thumbnail, or if message is a voice note

                # Build the update payload — include thumb_file_id only when present
                update_fields = {"file_id": f["file_id"], "display_name": name}
                if thumb_file_id:
                    update_fields["thumb_file_id"] = thumb_file_id

                try:
                    await db.files.update_one(
                        {"display_name": {"$regex": re.escape(name), "$options": "i"}},
                        {"$set": update_fields},
                        upsert=True,
                    )
                    thumb_status = " 🖼" if thumb_file_id else ""
                    await send_message(session, chat_id, f"✅ Saved: `{name}`{thumb_status}")
                except Exception as db_err:
                    logger.error("db.files.update_one failed: %s", db_err)
                    await send_message(session, chat_id, f"❌ DB error saving `{name}`. Please retry.")
            return

    if text and not text.startswith("/"):
        sq  = build_search_query(text)
        doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})

        if doc:
            kb = {"inline_keyboard": [[{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{str(doc['_id'])}"}], [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}
            await send_audio(session, chat_id, doc["file_id"], f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", reply_markup=kb)
        else:
            suggestions = await get_fuzzy_suggestions(db, text, limit=5)
            if suggestions:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ በቀጥታ አልተገኘም።\n\n_ምናልባት ከታች ያሉት ሊሆኑ ይችላሉ? አንዱን ይምረጡ፦_", reply_markup=get_fuzzy_suggestions_kb(suggestions))
            else:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ አልተገኘም።\nእባክዎ የተለየ ቃል ጽፈው ይሞክሩ ወይም 'ሙሉ ዝርዝር' የሚለውን ይጫኑ።", reply_markup=get_not_found_kb())


async def handle_inline_query(session, db, iq: dict, channels: list[dict]) -> None:
    query_id   = iq["id"]
    query      = iq.get("query", "").strip().lower()
    user_info  = iq.get("from", {})
    user_id    = user_info.get("id")
    first_name = user_info.get("first_name", "User")

    await track_and_get_user(db, user_id, first_name)
    results: list = []

    if query.startswith("#favorites"):
        user    = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
        fav_ids = (user or {}).get("favorites", [])
        if fav_ids:
            docs = await db.files.find({"file_id": {"$in": fav_ids}}, {"file_id": 1, "display_name": 1}).limit(50).to_list(length=50)
            for doc in docs:
                results.append({"type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"], "caption": f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", "reply_markup": {"inline_keyboard": [[{"text": "💔 Remove", "callback_data": f"fav_{str(doc['_id'])}"}]]}})
        else:
            results.append({"type": "article", "id": "no_favorites", "title": "No Favorites Yet", "input_message_content": {"message_text": "No favorites saved yet."}})
    elif not query:
        cached = get_inline_empty_cache()
        if cached is not None:
            await answer_inline_query(session, query_id, cached, cache_time=300)
            return
        docs = await db.files.find({"file_id": {"$exists": True}}, {"file_id": 1, "display_name": 1}).sort("_id", -1).limit(20).to_list(length=20)
        for doc in docs:
            results.append({"type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"], "caption": f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}})
        set_inline_empty_cache(results)
    else:
        sq   = build_search_query(query)
        docs = await db.files.find(sq, {"file_id": 1, "display_name": 1}).limit(20).to_list(length=20)
        for doc in docs:
            results.append({"type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"], "caption": f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}})

    await answer_inline_query(session, query_id, results, cache_time=300)


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


