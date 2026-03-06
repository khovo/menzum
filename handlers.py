"""
handlers.py
-----------
Pure business logic. Reads config, calls db/utils, makes decisions.
Zero direct HTTP or DB calls.

CHANGES FROM v1:
  - Removed dead import of FORCE_CHANNEL_URL (moved to DB).
  - All three handler functions now accept `channels: list[dict]` threaded
    from process_telegram_update (loaded once per webhook, channels-cached).
  - Admin bypass: admin_id never hits the subscription gate.
  - Smart fuzzy search: on AND-match miss, run OR-search and show suggestion
    buttons; only show hard "not found" if OR-search also returns nothing.
  - Dynamic Admin Channel UI: full state machine via callbacks + reply keyboard.
    States: admin_add_channel_wait.
    Callbacks: admin_ch_menu / admin_ch_add / admin_ch_list /
               admin_ch_del_{username} / admin_ch_close.
  - New `play_{doc_id}` callback: fuzzy suggestion buttons trigger audio
    delivery without a second round-trip text message.
  - Dead `re` import kept — still needed for audio-upload name sanitisation.
"""
import asyncio
import logging
import re
from bson import ObjectId
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient

from config import BOT_TOKEN, MONGO_URL, DB_NAME, ADMIN_ID
from db import (
    track_user,
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
    edit_message_text,
    answer_callback_query,
    answer_inline_query,
    copy_message,
    get_inline_empty_cache,
    set_inline_empty_cache,
    get_main_menu_kb,
    get_not_found_kb,
    get_fuzzy_suggestions_kb,
    get_subscription_kb,
    get_channel_mgmt_kb,
)

logger = logging.getLogger(__name__)


# ── Shared Helpers ────────────────────────────────────────────────────────────

def _is_admin(user_id) -> bool:
    return str(user_id) == str(ADMIN_ID)


async def _channel_mgmt_menu_text(db) -> str:
    """Build the text for the channel management inline menu."""
    channels = await get_force_channels(db)
    text = "📢 **Channel Management**\n\n"
    if channels:
        text += "\n".join(f"• @{ch['username']}" for ch in channels)
        text += "\n"
    else:
        text += "_No channels configured. Bot is in open-access mode._\n"
    text += "\nWhat would you like to do?"
    return text


# ── Callback Query Handler ────────────────────────────────────────────────────

async def handle_callback(session, db, cb: dict, channels: list[dict]) -> None:
    user       = cb["from"]
    user_id    = user["id"]
    cb_id      = cb["id"]
    data_str   = cb.get("data", "")
    chat_id    = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    first_name = user.get("first_name", "User")

    await track_user(db, user_id, first_name)

    # ── Subscription Gate ─────────────────────────────────────────────────────
    # Admin always bypasses.  check_subscription is exempt (it IS the gate).
    if data_str != "check_subscription" and not _is_admin(user_id):
        if not await check_membership(session, user_id, channels):
            await answer_callback_query(
                session, cb_id, "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!", show_alert=True
            )
            return

    # ── check_subscription ───────────────────────────────────────────────────
    if data_str == "check_subscription":
        invalidate_membership_cache(user_id)
        if await check_membership(session, user_id, channels):
            await answer_callback_query(session, cb_id, "✅ እንኳን ደህና መጡ!")
            welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
            await edit_message_text(
                session, chat_id, message_id, welcome,
                reply_markup=get_main_menu_kb(),
            )
        else:
            await answer_callback_query(
                session, cb_id, "❌ አሁንም አልተቀላቀሉም! ቻናሉን Join ይበሉ", show_alert=True
            )
        return

    # ── Support Flow ──────────────────────────────────────────────────────────
    if data_str == "support_start":
        await set_user_state(db, user_id, "support_wait")
        kb = {"inline_keyboard": [[{"text": "🔙 ተመለስ", "callback_data": "support_cancel"}]]}
        await edit_message_text(
            session, chat_id, message_id,
            "📝 **ሀሳቦን እዚህ ጋር ይጻፉ ወይም 'ተመለስ' የሚለውን በተን ይጫኑ።**",
            reply_markup=kb,
        )
        await answer_callback_query(session, cb_id)
        return

    if data_str == "support_cancel":
        await set_user_state(db, user_id, "idle")
        welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
        await edit_message_text(
            session, chat_id, message_id, welcome,
            reply_markup=get_main_menu_kb(),
        )
        await answer_callback_query(session, cb_id)
        return

    # ── Play (Fuzzy Suggestion Button) ────────────────────────────────────────
    # Triggered when a user taps a 🎵 suggestion button after a failed search.
    if data_str.startswith("play_"):
        doc_id = data_str.split("play_")[1]
        try:
            file_doc = await db.files.find_one(
                {"_id": ObjectId(doc_id)}, {"file_id": 1, "display_name": 1}
            ) if len(doc_id) == 24 else None

            if file_doc:
                kb = {
                    "inline_keyboard": [
                        [{"text": "❤️ Fav", "callback_data": f"fav_{doc_id}"}],
                        [
                            {"text": "↗️ Share",  "switch_inline_query": ""},
                            {"text": "⚠️ Report", "callback_data": f"report_{doc_id}"},
                        ],
                    ]
                }
                await send_audio(
                    session, chat_id, file_doc["file_id"],
                    f"{file_doc.get('display_name')}\n\n@Almadihbot",
                    reply_markup=kb,
                )
                await answer_callback_query(session, cb_id)
            else:
                await answer_callback_query(session, cb_id, "⚠️ File not found", show_alert=True)
        except Exception:
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    # ── Admin: Reply to a user ────────────────────────────────────────────────
    if data_str.startswith("reply_") and _is_admin(user_id):
        target_user_id = data_str.split("_")[1]
        await set_user_state(db, user_id, "admin_reply_wait", {"target_user_id": target_user_id})
        await send_message(
            session, chat_id,
            f"📝 **መልስ ለተጠቃሚ {target_user_id} እየጻፉ ነው:**\n\nመልእክቱን ይጻፉ (Text, Voice, Photo...).",
        )
        await answer_callback_query(session, cb_id)
        return

    # ── Catalog Pagination ────────────────────────────────────────────────────
    if data_str.startswith("pg_"):
        if data_str == "pg_close":
            welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
            await edit_message_text(
                session, chat_id, message_id, welcome,
                reply_markup=get_main_menu_kb(),
            )
        else:
            new_page = int(data_str.split("_")[1])
            text, kb = await get_catalog_page(db, new_page)
            await edit_message_text(session, chat_id, message_id, text, reply_markup=kb)
        await answer_callback_query(session, cb_id)
        return

    # ── Favorites Toggle ──────────────────────────────────────────────────────
    if data_str.startswith("fav_"):
        doc_id = data_str.split("fav_")[1]
        try:
            file_doc = await db.files.find_one(
                {"_id": ObjectId(doc_id)}, {"_id": 1, "file_id": 1}
            ) if len(doc_id) == 24 else None
            if file_doc:
                added = await toggle_favorite(db, user_id, file_doc["file_id"])
                await answer_callback_query(session, cb_id, "❤️ Saved" if added else "💔 Removed")
            else:
                await answer_callback_query(session, cb_id, "⚠️ Missing")
        except Exception:
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    # ── Report ────────────────────────────────────────────────────────────────
    if data_str.startswith("report_"):
        doc_id = data_str.split("report_")[1]
        try:
            file_doc = await db.files.find_one({"_id": ObjectId(doc_id)}, {"display_name": 1})
            if file_doc:
                await send_message(
                    session, ADMIN_ID,
                    f"🚨 Report: `{file_doc.get('display_name')}`\nID: `{doc_id}`",
                )
                await answer_callback_query(session, cb_id, "✅ Reported!", show_alert=True)
        except Exception:
            pass
        return

    # ── Broadcast (Admin) ─────────────────────────────────────────────────────
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

    # ── Admin Channel Management (Callbacks) ──────────────────────────────────
    #
    # Flow:
    #   admin panel keyboard → "🔧 Manage Channels" text
    #       → send message with get_channel_mgmt_kb()
    #   admin_ch_menu   → (re)render the top-level mgmt menu (edit in place)
    #   admin_ch_add    → set state admin_add_channel_wait, prompt for username
    #   admin_ch_list   → show channels with ❌ remove buttons
    #   admin_ch_del_X  → remove channel X, refresh list view, bust caches
    #   admin_ch_close  → dismiss the menu message

    if data_str.startswith("admin_ch_") and _is_admin(user_id):

        if data_str == "admin_ch_menu":
            text = await _channel_mgmt_menu_text(db)
            await edit_message_text(
                session, chat_id, message_id, text,
                reply_markup=get_channel_mgmt_kb(),
            )
            await answer_callback_query(session, cb_id)
            return

        if data_str == "admin_ch_add":
            await set_user_state(db, user_id, "admin_add_channel_wait")
            kb = {"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "admin_ch_menu"}]]}
            await edit_message_text(
                session, chat_id, message_id,
                "📢 **Add Force-Join Channel**\n\n"
                "Send the channel username _(without @)_.\n"
                "Example: `Al_madih`",
                reply_markup=kb,
            )
            await answer_callback_query(session, cb_id)
            return

        if data_str == "admin_ch_list":
            ch_list = await get_force_channels(db)
            if not ch_list:
                await answer_callback_query(
                    session, cb_id, "No channels configured yet!", show_alert=True
                )
                return
            remove_buttons = [
                [{"text": f"❌ @{ch['username']}", "callback_data": f"admin_ch_del_{ch['username']}"}]
                for ch in ch_list
            ]
            remove_buttons.append([{"text": "🔙 Back", "callback_data": "admin_ch_menu"}])
            await edit_message_text(
                session, chat_id, message_id,
                "🗑 **Remove a Channel**\nTap a channel to delete it from the force-join list.",
                reply_markup={"inline_keyboard": remove_buttons},
            )
            await answer_callback_query(session, cb_id)
            return

        if data_str.startswith("admin_ch_del_"):
            username = data_str.split("admin_ch_del_")[1]
            deleted  = await remove_force_channel(db, username)
            # Bust both caches so the change is reflected immediately
            invalidate_channels_cache()
            invalidate_all_membership_cache()

            toast = f"✅ @{username} removed." if deleted else f"⚠️ @{username} not found."
            await answer_callback_query(session, cb_id, toast)

            # Refresh the remove-list view (or fall back to main menu if empty)
            ch_list = await get_force_channels(db)
            if ch_list:
                remove_buttons = [
                    [{"text": f"❌ @{ch['username']}", "callback_data": f"admin_ch_del_{ch['username']}"}]
                    for ch in ch_list
                ]
                remove_buttons.append([{"text": "🔙 Back", "callback_data": "admin_ch_menu"}])
                await edit_message_text(
                    session, chat_id, message_id,
                    "🗑 **Remove a Channel**\nTap a channel to delete it.",
                    reply_markup={"inline_keyboard": remove_buttons},
                )
            else:
                text = await _channel_mgmt_menu_text(db)
                await edit_message_text(
                    session, chat_id, message_id, text,
                    reply_markup=get_channel_mgmt_kb(),
                )
            return

        if data_str == "admin_ch_close":
            await edit_message_text(session, chat_id, message_id, "✅ Channel management closed.")
            await answer_callback_query(session, cb_id)
            return


# ── Message Handler ───────────────────────────────────────────────────────────

async def handle_message(session, db, message: dict, channels: list[dict]) -> None:
    chat_id    = message.get("chat", {}).get("id")
    user_info  = message.get("from", {})
    user_id    = user_info.get("id")
    text       = message.get("text", "")
    first_name = user_info.get("first_name", "User")

    await track_user(db, user_id, first_name)

    # ── Subscription Gate (admin bypass) ─────────────────────────────────────
    if not _is_admin(user_id):
        if not await check_membership(session, user_id, channels):
            await send_message(
                session, chat_id,
                "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**",
                reply_markup=get_subscription_kb(channels),
            )
            return

    # ── /start ────────────────────────────────────────────────────────────────
    if text == "/start":
        welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
        await send_message(session, chat_id, welcome, reply_markup=get_main_menu_kb())
        return

    # ── Catalog shortcut ──────────────────────────────────────────────────────
    if text in ("/list", "📂 Catalog (List)"):
        msg_text, kb = await get_catalog_page(db, 1)
        await send_message(session, chat_id, msg_text, reply_markup=kb)
        return

    # ── Load State ────────────────────────────────────────────────────────────
    user_data = await get_user_data(db, user_id)
    state     = (user_data or {}).get("state")

    # ── Support: User sending feedback ───────────────────────────────────────
    if state == "support_wait":
        if text == "/start":
            await set_user_state(db, user_id, "idle")
            await send_message(
                session, chat_id, "🏠 ወደ ዋናው ገጽ ተመልሰዋል።",
                reply_markup=get_main_menu_kb(),
            )
            return
        kb = {"inline_keyboard": [[{"text": "↩️ መልስ ለመስጠት (Reply)", "callback_data": f"reply_{user_id}"}]]}
        await send_message(
            session, ADMIN_ID,
            f"📩 **New Feedback from:** {first_name} (`{user_id}`)",
            reply_markup=kb,
        )
        await copy_message(session, ADMIN_ID, chat_id, message.get("message_id"))
        await send_message(
            session, chat_id,
            "✅ **መልእክትዎ ተልኳል! እናመሰግናለን።**\n\nወደ ዋናው ገጽ ተመልሰዋል።",
            reply_markup=get_main_menu_kb(),
        )
        await set_user_state(db, user_id, "idle")
        return

    # ── Admin Panel ───────────────────────────────────────────────────────────
    if _is_admin(user_id):

        if text == "/admin":
            kb = {
                "keyboard": [
                    [{"text": "📊 Statistics"},   {"text": "📅 Daily Stats"}],
                    [{"text": "📢 Broadcast"},     {"text": "📂 Total Files"}],
                    [{"text": "🔧 Manage Channels"}],
                ],
                "resize_keyboard": True,
            }
            await send_message(session, chat_id, "⚙️ *Admin Panel*", reply_markup=kb)
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

        # ── Manage Channels: open the dynamic inline-keyboard UI ─────────────
        if text == "🔧 Manage Channels":
            mgmt_text = await _channel_mgmt_menu_text(db)
            await send_message(
                session, chat_id, mgmt_text,
                reply_markup=get_channel_mgmt_kb(),
            )
            return

        # ── Admin Add Channel: waiting for username text ──────────────────────
        if state == "admin_add_channel_wait":
            if text and not text.startswith("/"):
                username = text.lstrip("@").strip()
                added    = await add_force_channel(db, username)
                # Bust caches so new channel is enforced immediately
                invalidate_channels_cache()
                invalidate_all_membership_cache()
                result_text = f"✅ @{username} added!" if added else f"⚠️ @{username} already exists."
                kb = {"inline_keyboard": [[{"text": "📢 Manage Channels", "callback_data": "admin_ch_menu"}]]}
                await send_message(session, chat_id, result_text, reply_markup=kb)
                await set_user_state(db, user_id, "idle")
            else:
                await send_message(session, chat_id, "⚠️ Please send a plain text username (e.g. `Al_madih`).")
            return

        # ── Admin Reply to User ───────────────────────────────────────────────
        if state == "admin_reply_wait":
            target_user = (user_data or {}).get("target_user_id")
            if target_user:
                try:
                    await send_message(session, target_user, "🔔 **ከአድሚኑ የተሰጠ መልስ:**")
                    await copy_message(session, target_user, chat_id, message["message_id"])
                    await send_message(session, chat_id, "✅ መልሱ ተልኳል!")
                except Exception as e:
                    await send_message(session, chat_id, f"❌ አልተላከም: {e}")
                await set_user_state(db, user_id, "idle")
            return

        # ── Broadcast Confirmation ────────────────────────────────────────────
        if state == "broadcast_wait" and text != "🔙 Back" and "message_id" in message:
            await set_user_state(
                db, user_id, "broadcast_confirm",
                {"broadcast_msg_id": message["message_id"], "broadcast_markup": message.get("reply_markup")},
            )
            await copy_message(
                session, chat_id, chat_id, message["message_id"],
                reply_markup=message.get("reply_markup"),
            )
            kb = {
                "inline_keyboard": [
                    [{"text": "✅ Post",   "callback_data": "broadcast_confirm"}],
                    [{"text": "❌ Cancel", "callback_data": "broadcast_cancel"}],
                ]
            }
            await send_message(session, chat_id, "Confirm broadcast?", reply_markup=kb)
            return

        # ── Admin Audio Upload → Save to DB ──────────────────────────────────
        if "audio" in message or "voice" in message:
            f    = message.get("audio") or message.get("voice")
            cap  = message.get("caption", "").split("\n")[0].strip()
            name = cap if cap else f.get("file_name", "Unknown")
            if len(name) > 3:
                await db.files.update_one(
                    {"display_name": {"$regex": re.escape(name), "$options": "i"}},
                    {"$set": {"file_id": f["file_id"], "display_name": name}},
                    upsert=True,
                )
                await send_message(session, chat_id, f"✅ Saved: `{name}`")
            return

    # ── Regular User: Smart Search ────────────────────────────────────────────
    if text and not text.startswith("/"):
        # 1st pass: strict AND-search (all words must match)
        sq  = build_search_query(text)
        doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})

        if doc:
            kb = {
                "inline_keyboard": [
                    [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}],
                    [
                        {"text": "↗️ Share",  "switch_inline_query": ""},
                        {"text": "⚠️ Report", "callback_data": f"report_{str(doc['_id'])}"},
                    ],
                ]
            }
            await send_audio(
                session, chat_id, doc["file_id"],
                f"{doc.get('display_name')}\n\n@Almadihbot",
                reply_markup=kb,
            )
        else:
            # 2nd pass: broad OR-search → up to 5 fuzzy suggestions
            suggestions = await get_fuzzy_suggestions(db, text, limit=5)
            if suggestions:
                await send_message(
                    session, chat_id,
                    "😔 በቀጥታ አልተገኘም። ይህን ማለትዎ ነው?\n\n_ከታች ካሉት ዘፈኖች አንዱን ምረጡ:_",
                    reply_markup=get_fuzzy_suggestions_kb(suggestions),
                )
            else:
                # Nothing at all → send catalog fallback
                await send_message(
                    session, chat_id,
                    "😔 በቀጥታ አልተገኘም።\nእባክዎ ከታች ባለው ቁልፍ ሙሉ ዝርዝሩ ውስጥ ይፈልጉ!",
                    reply_markup=get_not_found_kb(),
                )


# ── Inline Query Handler ──────────────────────────────────────────────────────

async def handle_inline_query(session, db, iq: dict, channels: list[dict]) -> None:
    query_id   = iq["id"]
    query      = iq.get("query", "").strip().lower()
    user_info  = iq.get("from", {})
    user_id    = user_info.get("id")
    first_name = user_info.get("first_name", "User")

    await track_user(db, user_id, first_name)

    results: list = []

    # ── #favorites ────────────────────────────────────────────────────────────
    if query.startswith("#favorites"):
        user    = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
        fav_ids = user.get("favorites", []) if user else []
        if fav_ids:
            docs = await db.files.find(
                {"file_id": {"$in": fav_ids}}, {"file_id": 1, "display_name": 1}
            ).limit(50).to_list(length=50)
            for doc in docs:
                results.append({
                    "type":           "audio",
                    "id":             str(doc["_id"]),
                    "audio_file_id":  doc["file_id"],
                    "caption":        f"{doc.get('display_name')}\n\n@Almadihbot",
                    "reply_markup":   {
                        "inline_keyboard": [[{"text": "💔 Remove", "callback_data": f"fav_{str(doc['_id'])}"}]]
                    },
                })
        else:
            results.append({
                "type":  "article",
                "id":    "no_favorites",
                "title": "No Favorites Yet",
                "input_message_content": {"message_text": "No favorites saved yet."},
            })

    # ── Empty query → latest 20 (cached) ─────────────────────────────────────
    elif not query:
        cached = get_inline_empty_cache()
        if cached is not None:
            await answer_inline_query(session, query_id, cached, cache_time=300)
            return
        docs = await (
            db.files.find({"file_id": {"$exists": True}}, {"file_id": 1, "display_name": 1})
            .sort("_id", -1)
            .limit(20)
            .to_list(length=20)
        )
        for doc in docs:
            results.append({
                "type":          "audio",
                "id":            str(doc["_id"]),
                "audio_file_id": doc["file_id"],
                "caption":       f"{doc.get('display_name')}\n\n@Almadihbot",
                "reply_markup":  {
                    "inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]
                },
            })
        set_inline_empty_cache(results)

    # ── Free-text search ──────────────────────────────────────────────────────
    else:
        sq   = build_search_query(query)
        docs = await db.files.find(sq, {"file_id": 1, "display_name": 1}).limit(20).to_list(length=20)
        for doc in docs:
            results.append({
                "type":          "audio",
                "id":            str(doc["_id"]),
                "audio_file_id": doc["file_id"],
                "caption":       f"{doc.get('display_name')}\n\n@Almadihbot",
                "reply_markup":  {
                    "inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]
                },
            })

    await answer_inline_query(session, query_id, results, cache_time=300)


# ── Main Dispatcher ───────────────────────────────────────────────────────────

async def process_telegram_update(data: dict) -> None:
    """
    Top-level coroutine called once per Telegram webhook payload.

    Loads the force-join channel list ONCE per invocation (from in-memory
    cache if fresh, otherwise from DB).  Passes the list to every handler
    so membership checks never need a DB round-trip of their own.

    Both the DB client and aiohttp session are guaranteed to close in the
    finally block — critical for Vercel's serverless environment.
    """
    if not MONGO_URL or not BOT_TOKEN:
        logger.error("MONGO_URL or BOT_TOKEN not set — aborting.")
        return

    db_client = AsyncIOMotorClient(MONGO_URL)
    db        = db_client[DB_NAME]

    async with aiohttp.ClientSession() as session:
        try:
            # ── Load channels once (cached, ~30s TTL) ────────────────────────
            channels = get_channels_cache()
            if channels is None:
                channels = await get_force_channels(db)
                set_channels_cache(channels)

            # ── Dispatch ─────────────────────────────────────────────────────
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
