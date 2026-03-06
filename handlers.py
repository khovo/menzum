"""
handlers.py
-----------
Pure business logic.  This module:
  - Reads config values from config.py
  - Calls DB helpers from db.py
  - Calls Telegram API helpers / cache from utils.py
  - Makes ZERO HTTP calls or DB calls directly (clean separation of concerns)

Entry point: process_telegram_update(data: dict)
Called once per incoming Telegram webhook payload.
"""
import asyncio
import logging
import re
from bson import ObjectId
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient

from config import (
    BOT_TOKEN,
    MONGO_URL,
    DB_NAME,
    ADMIN_ID,
    FORCE_CHANNEL_URL,
)
from db import (
    track_user,
    toggle_favorite,
    get_user_data,
    set_user_state,
    build_search_query,
    get_catalog_page,
    get_daily_stats,
)
from utils import (
    check_membership,
    invalidate_membership_cache,
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
    get_subscription_kb,
)

logger = logging.getLogger(__name__)


# ── Callback Query Handler ────────────────────────────────────────────────────

async def handle_callback(session, db, cb: dict) -> None:
    user      = cb["from"]
    user_id   = user["id"]
    cb_id     = cb["id"]
    data_str  = cb.get("data", "")
    chat_id   = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]

    first_name = user.get("first_name", "User")

    # BUG FIX #1 — track every interacting user, not just /start senders
    await track_user(db, user_id, first_name)

    # ── Subscription Gate ─────────────────────────────────────────────────────
    # The check_subscription callback is exempt — it IS the verification step.
    if data_str != "check_subscription":
        if not await check_membership(session, user_id):
            await answer_callback_query(
                session, cb_id, "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!", show_alert=True
            )
            return

    # ── check_subscription ───────────────────────────────────────────────────
    if data_str == "check_subscription":
        invalidate_membership_cache(user_id)
        if await check_membership(session, user_id):
            await answer_callback_query(session, cb_id, "✅ እንኳን ደህና መጡ!")
            welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
            await edit_message_text(
                session, chat_id, message_id, welcome,
                reply_markup=get_main_menu_kb(),
            )
        else:
            await answer_callback_query(
                session, cb_id,
                "❌ አሁንም አልተቀላቀሉም! ቻናሉን Join ይበሉ",
                show_alert=True,
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

    # ── Admin: Reply to a user ────────────────────────────────────────────────
    if data_str.startswith("reply_") and str(user_id) == str(ADMIN_ID):
        target_user_id = data_str.split("_")[1]
        await set_user_state(
            db, user_id, "admin_reply_wait",
            {"target_user_id": target_user_id},
        )
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
            if len(doc_id) == 24:
                file_doc = await db.files.find_one(
                    {"_id": ObjectId(doc_id)}, {"_id": 1, "file_id": 1}
                )
                if file_doc:
                    added = await toggle_favorite(db, user_id, file_doc["file_id"])
                    await answer_callback_query(
                        session, cb_id, "❤️ Saved" if added else "💔 Removed"
                    )
                else:
                    await answer_callback_query(session, cb_id, "⚠️ Missing")
            else:
                await answer_callback_query(session, cb_id, "⚠️ Invalid ID")
        except Exception:
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    # ── Report ────────────────────────────────────────────────────────────────
    if data_str.startswith("report_"):
        doc_id = data_str.split("report_")[1]
        try:
            file_doc = await db.files.find_one(
                {"_id": ObjectId(doc_id)}, {"display_name": 1}
            )
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
    if data_str.startswith("broadcast_") and str(user_id) == str(ADMIN_ID):
        if data_str == "broadcast_confirm":
            admin_data = await get_user_data(db, user_id)
            msg_id = (admin_data or {}).get("broadcast_msg_id")
            markup = (admin_data or {}).get("broadcast_markup")
            if msg_id:
                await edit_message_text(session, chat_id, message_id, "🚀 Sending...")
                count = 0
                async for u in db.users.find({}, {"_id": 1}):
                    try:
                        await copy_message(session, u["_id"], chat_id, msg_id, reply_markup=markup)
                        count += 1
                        await asyncio.sleep(0.05)  # Telegram rate limit
                    except Exception:
                        pass
                await send_message(session, chat_id, f"✅ Sent to {count} users.")
                await set_user_state(db, user_id, "idle")
        elif data_str == "broadcast_cancel":
            await edit_message_text(session, chat_id, message_id, "❌ Broadcast cancelled.")
            await set_user_state(db, user_id, "idle")
        await answer_callback_query(session, cb_id)
        return


# ── Message Handler ───────────────────────────────────────────────────────────

async def handle_message(session, db, message: dict) -> None:
    chat_id   = message.get("chat", {}).get("id")
    user_info = message.get("from", {})
    user_id   = user_info.get("id")
    text      = message.get("text", "")
    first_name = user_info.get("first_name", "User")

    # BUG FIX #1 — track every interacting user, not just /start senders
    await track_user(db, user_id, first_name)

    # ── Subscription Gate ─────────────────────────────────────────────────────
    if not await check_membership(session, user_id):
        msg = "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**"
        await send_message(
            session, chat_id, msg,
            reply_markup=get_subscription_kb(FORCE_CHANNEL_URL),
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

    # ── Stateful Flow: Support & Admin ────────────────────────────────────────
    user_data = await get_user_data(db, user_id)
    state     = (user_data or {}).get("state")

    if state == "support_wait":
        if text == "/start":
            await set_user_state(db, user_id, "idle")
            await send_message(
                session, chat_id, "🏠 ወደ ዋናው ገጽ ተመልሰዋል።",
                reply_markup=get_main_menu_kb(),
            )
            return

        sender_name = first_name
        kb = {
            "inline_keyboard": [
                [{"text": "↩️ መልስ ለመስጠት (Reply)", "callback_data": f"reply_{user_id}"}]
            ]
        }
        await send_message(
            session, ADMIN_ID,
            f"📩 **New Feedback from:** {sender_name} (`{user_id}`)",
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
    if str(user_id) == str(ADMIN_ID):
        # Admin commands
        if text == "/admin":
            kb = {
                "keyboard": [
                    [{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}],
                    [{"text": "📢 Broadcast"},  {"text": "📂 Total Files"}],
                ],
                "resize_keyboard": True,
            }
            await send_message(session, chat_id, "⚙️ Admin Panel", reply_markup=kb)
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

        # Admin stateful: reply to a user
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

        # Admin stateful: confirm a broadcast
        if (
            state == "broadcast_wait"
            and text != "🔙 Back"
            and "message_id" in message
        ):
            await set_user_state(
                db, user_id, "broadcast_confirm",
                {
                    "broadcast_msg_id": message["message_id"],
                    "broadcast_markup": message.get("reply_markup"),
                },
            )
            await copy_message(
                session, chat_id, chat_id, message["message_id"],
                reply_markup=message.get("reply_markup"),
            )
            kb = {
                "inline_keyboard": [
                    [{"text": "✅ Post",     "callback_data": "broadcast_confirm"}],
                    [{"text": "❌ Cancel",   "callback_data": "broadcast_cancel"}],
                ]
            }
            await send_message(session, chat_id, "Confirm broadcast?", reply_markup=kb)
            return

        # Admin uploads audio/voice → save to DB
        if "audio" in message or "voice" in message:
            f = message.get("audio") or message.get("voice")
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

    # ── Regular User: Free-text Search ───────────────────────────────────────
    if text and not text.startswith("/"):
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
            # BUG FIX #2 — 'Not Found' UX
            # No dead-end. Give the user a direct path to the catalog.
            await send_message(
                session, chat_id,
                "😔 በቀጥታ አልተገኘም።\nእባክዎ ከታች ባለው ቁልፍ ሙሉ ዝርዝሩ ውስጥ ይፈልጉ!",
                reply_markup=get_not_found_kb(),
            )


# ── Inline Query Handler ──────────────────────────────────────────────────────

async def handle_inline_query(session, db, iq: dict) -> None:
    query_id   = iq["id"]
    query      = iq.get("query", "").strip().lower()
    user_info  = iq.get("from", {})
    user_id    = user_info.get("id")
    first_name = user_info.get("first_name", "User")

    # BUG FIX #1 — track inline users too
    await track_user(db, user_id, first_name)

    results: list = []

    # ── #favorites ────────────────────────────────────────────────────────────
    if query.startswith("#favorites"):
        user = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
        fav_ids = user.get("favorites", []) if user else []
        if fav_ids:
            docs = await db.files.find(
                {"file_id": {"$in": fav_ids}}, {"file_id": 1, "display_name": 1}
            ).limit(50).to_list(length=50)
            for doc in docs:
                results.append({
                    "type": "audio",
                    "id": str(doc["_id"]),
                    "audio_file_id": doc["file_id"],
                    "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "💔 Remove", "callback_data": f"fav_{str(doc['_id'])}"}]
                        ]
                    },
                })
        else:
            results.append({
                "type": "article",
                "id": "no_favorites",
                "title": "No Favorites Yet",
                "input_message_content": {"message_text": "No favorites saved yet."},
            })

    # ── Empty query → show latest 20 (cached) ────────────────────────────────
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
                "type": "audio",
                "id": str(doc["_id"]),
                "audio_file_id": doc["file_id"],
                "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]
                    ]
                },
            })
        set_inline_empty_cache(results)

    # ── Free-text search ──────────────────────────────────────────────────────
    else:
        sq   = build_search_query(query)
        docs = await db.files.find(sq, {"file_id": 1, "display_name": 1}).limit(20).to_list(length=20)
        for doc in docs:
            results.append({
                "type": "audio",
                "id": str(doc["_id"]),
                "audio_file_id": doc["file_id"],
                "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]
                    ]
                },
            })

    await answer_inline_query(session, query_id, results, cache_time=300)


# ── Main Dispatcher ───────────────────────────────────────────────────────────

async def process_telegram_update(data: dict) -> None:
    """
    Top-level coroutine called once per Telegram webhook payload.

    Owns the DB connection and aiohttp session lifetimes — both are opened
    here and guaranteed to be closed in the finally block, which is critical
    for Vercel's serverless environment where connections must not leak.
    """
    if not MONGO_URL or not BOT_TOKEN:
        logger.error("MONGO_URL or BOT_TOKEN not set — aborting.")
        return

    db_client = AsyncIOMotorClient(MONGO_URL)
    db        = db_client[DB_NAME]

    async with aiohttp.ClientSession() as session:
        try:
            if "callback_query" in data:
                await handle_callback(session, db, data["callback_query"])

            elif "message" in data:
                await handle_message(session, db, data["message"])

            elif "inline_query" in data:
                await handle_inline_query(session, db, data["inline_query"])

        except Exception:
            logger.exception("Unhandled error in process_telegram_update")
        finally:
            db_client.close()
