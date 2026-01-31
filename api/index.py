from flask import Flask, request, jsonify
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
import asyncio
import logging
import traceback
import aiohttp
import re
import threading
import time
from datetime import datetime, timedelta

# --- Logging Config ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID = os.environ.get("ADMIN_ID")

FORCE_CHANNEL_USERNAME = "Al_madih"
FORCE_CHANNEL_URL = "https://t.me/Al_madih"

ITEMS_PER_PAGE = 10

# --- Simple In-Memory Cache for Membership (Speed Boost) ---
# Format: {user_id: {"status": True/False, "time": timestamp}}
MEMBERSHIP_CACHE = {}
CACHE_DURATION = 300  # 5 Minutes

# --- Async Helper for Flask ---
def run_async(coro):
    """Helper to run async code in Flask's sync environment."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

# --- Telegram API Wrapper ---
async def make_request(method, payload):
    if not BOT_TOKEN: return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                res = await resp.json()
                if resp.status == 429:
                    retry_after = res.get('parameters', {}).get('retry_after', 5)
                    logger.warning(f"FloodWait: Sleeping {retry_after}s")
                    await asyncio.sleep(retry_after)
                    return await make_request(method, payload)
                return res
        except Exception as e:
            logger.error(f"API Error ({method}): {e}")
            return None

async def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    return await make_request("sendMessage", payload)

async def send_audio(chat_id, audio_file_id, caption, reply_markup=None):
    payload = {"chat_id": chat_id, "audio": audio_file_id, "caption": caption, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    res = await make_request("sendAudio", payload)
    
    if res and not res.get("ok") and "BUTTON_DATA_INVALID" in str(res):
        payload.pop("reply_markup")
        await make_request("sendAudio", payload)
    elif res and not res.get("ok"):
        await send_message(chat_id, "⚠️ ፋይሉን መላክ አልተቻለም (File deleted or restricted).")
    return res

async def edit_message_text(chat_id, message_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id, 
        "message_id": message_id, 
        "text": text, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup: payload["reply_markup"] = reply_markup
    return await make_request("editMessageText", payload)

async def edit_message_reply_markup(chat_id, message_id, reply_markup):
    payload = {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup}
    return await make_request("editMessageReplyMarkup", payload)

async def answer_callback_query(callback_query_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    if show_alert: payload["show_alert"] = True
    return await make_request("answerCallbackQuery", payload)

async def answer_inline_query(query_id, results, switch_pm_text=None, switch_pm_param=None, cache_time=0):
    payload = {"inline_query_id": query_id, "results": results, "cache_time": cache_time, "is_personal": True}
    if switch_pm_text:
        payload["switch_pm_text"] = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    return await make_request("answerInlineQuery", payload)

async def copy_message(chat_id, from_chat_id, message_id, reply_markup=None):
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    if reply_markup: payload["reply_markup"] = reply_markup
    return await make_request("copyMessage", payload)

async def check_membership(user_id):
    if not BOT_TOKEN: return True
    
    # 1. Check Cache (Speed Optimization)
    current_time = time.time()
    if user_id in MEMBERSHIP_CACHE:
        cached_data = MEMBERSHIP_CACHE[user_id]
        if current_time - cached_data["time"] < CACHE_DURATION:
            return cached_data["status"]

    # 2. If not in cache, check API
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    
    is_member = True # Default to True on error
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                res = await resp.json()
                if res.get("ok"):
                    status = res["result"]["status"]
                    is_member = status in ["creator", "administrator", "member"]
        except: pass
    
    # 3. Update Cache
    MEMBERSHIP_CACHE[user_id] = {"status": is_member, "time": current_time}
    return is_member

# --- DB Helpers ---
async def track_user(db, user_id, first_name):
    try:
        now = datetime.now()
        await db.users.update_one(
            {"_id": user_id},
            {
                "$set": {"first_name": first_name, "last_active": now},
                "$setOnInsert": {"joined_at": now}
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"Track User Error: {e}")

async def increment_view(db, file_id):
    try:
        await db.files.update_one({"file_id": file_id}, {"$inc": {"views": 1}})
    except: pass

async def toggle_favorite(db, user_id, file_id):
    try:
        user = await db.users.find_one({"_id": user_id})
        favorites = user.get("favorites", []) if user else []
        if file_id in favorites:
            await db.users.update_one({"_id": user_id}, {"$pull": {"favorites": file_id}})
            return False
        else:
            await db.users.update_one({"_id": user_id}, {"$addToSet": {"favorites": file_id}})
            return True
    except: return False

async def set_user_state(db, user_id, state, meta=None):
    update = {"$set": {"state": state}}
    if meta: update["$set"].update(meta)
    await db.users.update_one({"_id": user_id}, update, upsert=True)

async def get_user_data(db, user_id):
    return await db.users.find_one({"_id": user_id})

def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    if query_text.startswith("#"): return {} 
    
    escaped_query = re.escape(query_text)
    
    if len(query_text) == 1:
        return {"display_name": {"$regex": f"^{escaped_query}", "$options": "i"}}
    
    words = query_text.split()
    regex_pattern = ""
    for word in words:
        regex_pattern += f"(?=.*{re.escape(word)})"
    return {"display_name": {"$regex": f"^{regex_pattern}", "$options": "i"}}

async def get_daily_stats(db):
    try:
        now = datetime.now()
        last_24h = now - timedelta(hours=24)
        new_users = await db.users.count_documents({"joined_at": {"$gte": last_24h}})
        active_users = await db.users.count_documents({"last_active": {"$gte": last_24h}})
        total_users = await db.users.count_documents({})
        total_files = await db.files.count_documents({})
        return (f"📅 **Daily Statistics (24h)**\n\n"
                f"🆕 New Users: `{new_users}`\n"
                f"⚡ Active Users: `{active_users}`\n\n"
                f"👥 Total Users: `{total_users}`\n"
                f"📂 Total Files: `{total_files}`")
    except: return "Error fetching stats."

async def get_catalog_page(db, page):
    limit = ITEMS_PER_PAGE
    skip = (page - 1) * limit
    
    # Speed Optimization: Avoid full count if possible or cache it
    # For now, we keep it simple but ensure indexing is recommended
    total_docs = await db.files.count_documents({"file_id": {"$exists": True}})
    total_pages = (total_docs + limit - 1) // limit
    
    if total_docs == 0:
        return "📂 ምንም ፋይሎች አልተገኙም።", None

    cursor = db.files.find({"file_id": {"$exists": True}}).sort("_id", -1).skip(skip).limit(limit)
    msg_text = f"📂 **የመንዙማዎች ዝርዝር (ገጽ {page}/{total_pages})**\n\n💡 _ስሙን ሲነኩት ኮፒ ይሆናል፣ ከዛ ለቦቱ ይላኩት።_\n\n"
    
    idx = skip + 1
    async for doc in cursor:
        clean_name = doc.get("display_name", "Unknown").replace("`", "") 
        msg_text += f"{idx}. `{clean_name}`\n"
        idx += 1
        
    buttons = []
    nav_row = []
    if page > 1: nav_row.append({"text": "⬅️ Back", "callback_data": f"pg_{page-1}"})
    nav_row.append({"text": "❌ ዝጋ", "callback_data": "pg_close"})
    if page < total_pages: nav_row.append({"text": "Next ➡️", "callback_data": f"pg_{page+1}"})
    buttons.append(nav_row)
    
    return msg_text, {"inline_keyboard": buttons}

# --- Background Broadcasting ---
def start_broadcast_background(admin_id, msg_id, markup):
    threading.Thread(target=run_broadcast_logic, args=(admin_id, msg_id, markup)).start()

def run_broadcast_logic(admin_id, msg_id, markup):
    async def _broadcast():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client["MenzumaDB"]
        users_cursor = db.users.find({})
        count = 0
        blocked = 0
        try:
            await send_message(admin_id, "🚀 **Broadcast started in background...**")
            async for user in users_cursor:
                try:
                    res = await copy_message(user["_id"], admin_id, msg_id, reply_markup=markup)
                    if res and res.get("ok"): count += 1
                    else: blocked += 1
                    await asyncio.sleep(0.05)
                except: blocked += 1
            await send_message(admin_id, f"✅ **Broadcast Completed!**\n\n📢 Sent: `{count}`\n🚫 Failed/Blocked: `{blocked}`")
        except Exception as e:
            logger.error(f"Broadcast Error: {e}")
            await send_message(admin_id, f"⚠️ Broadcast stopped due to error: {e}")
        finally:
            client.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_broadcast())
    loop.close()

# --- Main Logic ---
async def process_telegram_update(data):
    if not MONGO_URL or not BOT_TOKEN: return
    
    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]

    try:
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            message = cb.get("message")
            
            if not message:
                await answer_callback_query(cb_id, "⚠️ Message too old.")
                return

            chat_id = message["chat"]["id"]
            message_id = message["message_id"]
            
            if data_str == "check_subscription":
                # With caching, this is now much faster
                if await check_membership(user_id):
                    await answer_callback_query(cb_id, "✅ ተቀላቅለዋል! እንኳን ደህና መጡ።")
                    welcome = (
                        "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*\n\n"
                        "ከ 1,200 በላይ መንዙማዎችን እዚህ ያገኛሉ።\n\n"
                        "👇 **አጠቃቀም:**\n"
                        "• ዝም ብለው ስም ይጻፉ (Direct).\n"
                        "• `/list` ብለው ሙሉ ዝርዝር በገጽ ማየት ይችላሉ።"
                    )
                    kb = {
                        "inline_keyboard": [
                            [
                                {"text": "🔥 Trending", "switch_inline_query_current_chat": "#trending"},
                                {"text": "🆕 New", "switch_inline_query_current_chat": "#new"}
                            ],
                            [
                                {"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"},
                                {"text": "📂 Catalog (List)", "callback_data": "pg_1"}
                            ],
                            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}]
                        ]
                    }
                    await edit_message_text(chat_id, message_id, welcome, reply_markup=kb)
                else:
                    await answer_callback_query(cb_id, "❌ አሁንም አልተቀላቀሉም! መጀመሪያ Join ይበሉ።", show_alert=True)
                return

            if data_str.startswith("report_"):
                doc_id = data_str.split("report_")[1]
                try:
                    file_doc = await db.files.find_one({"_id": ObjectId(doc_id)})
                    file_name = file_doc.get("display_name", "Unknown") if file_doc else "Unknown"
                    report_msg = (
                        f"🚨 **Broken File Report!** 🚨\n\n"
                        f"👤 Reported By: `{user_id}`\n"
                        f"📂 File: `{file_name}`\n"
                        f"🆔 Doc ID: `{doc_id}`"
                    )
                    if ADMIN_ID: await send_message(ADMIN_ID, report_msg)
                    await answer_callback_query(cb_id, "✅ ሪፖርት ተልኳል! እናስተካክለዋለን።", show_alert=True)
                except:
                    await answer_callback_query(cb_id, "Error reporting.")
                return

            if data_str == "broadcast_confirm":
                if str(user_id) != str(ADMIN_ID): return
                admin_data = await get_user_data(db, user_id)
                msg_id_to_copy = admin_data.get("broadcast_msg_id")
                markup_to_copy = admin_data.get("broadcast_markup")
                if not msg_id_to_copy:
                    await answer_callback_query(cb_id, "⚠️ Error.")
                    return
                start_broadcast_background(user_id, msg_id_to_copy, markup_to_copy)
                await edit_message_text(chat_id, message_id, "🚀 Broadcast process started in background...")
                await set_user_state(db, user_id, "idle")
                await answer_callback_query(cb_id)
                return

            elif data_str == "broadcast_cancel":
                if str(user_id) != str(ADMIN_ID): return
                await edit_message_text(chat_id, message_id, "❌ Broadcast cancelled.")
                await set_user_state(db, user_id, "idle")
                await answer_callback_query(cb_id)
                return

            if data_str.startswith("pg_"):
                if data_str == "pg_close":
                    await edit_message_text(chat_id, message_id, "❌ ዝርዝሩ ተዘግቷል። /list በማለት እንደገና መክፈት ይችላሉ።")
                else:
                    new_page = int(data_str.split("_")[1])
                    text, kb = await get_catalog_page(db, new_page)
                    await edit_message_text(chat_id, message_id, text, reply_markup=kb)
                await answer_callback_query(cb_id)
                
            elif data_str.startswith("fav_"):
                doc_id = data_str.split("fav_")[1]
                try:
                    file_doc = await db.files.find_one({"_id": ObjectId(doc_id)})
                    if file_doc:
                        file_id = file_doc['file_id']
                        is_fav = await toggle_favorite(db, user_id, file_id)
                        text = "❤️ Saved" if is_fav else "💔 Removed"
                        new_text = "💔 Remove" if is_fav else "❤️ Add to Favorite"
                        kb = {
                            "inline_keyboard": [
                                [{"text": new_text, "callback_data": f"fav_{doc_id}"}],
                                [{"text": "↗️ Share", "switch_inline_query": ""}, {"text": "⚠️ Report", "callback_data": f"report_{doc_id}"}]
                            ]
                        }
                        await answer_callback_query(cb_id, text)
                        await edit_message_reply_markup(chat_id, message_id, kb)
                    else:
                        await answer_callback_query(cb_id, "⚠️ File not found")
                except:
                    await answer_callback_query(cb_id, "Error")
            return

        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            first_name = message.get("from", {}).get("first_name", "User")
            text = message.get("text", "")
            
            await track_user(db, user_id, first_name)

            if str(user_id) == str(ADMIN_ID):
                admin_data = await get_user_data(db, user_id)
                state = admin_data.get("state") if admin_data else "idle"
                
                if state == "broadcast_wait":
                    if text == "🔙 Back":
                        await set_user_state(db, user_id, "idle")
                        await send_message(chat_id, "🔙 Back to Menu.")
                        return
                    broadcast_msg_id = message["message_id"]
                    original_markup = message.get("reply_markup")
                    await set_user_state(db, user_id, "broadcast_confirm", {"broadcast_msg_id": broadcast_msg_id, "broadcast_markup": original_markup})
                    await copy_message(chat_id, chat_id, broadcast_msg_id, reply_markup=original_markup)
                    kb = {"inline_keyboard": [[{"text": "✅ Post (አስተላልፍ)", "callback_data": "broadcast_confirm"}], [{"text": "❌ Cancel (ተው)", "callback_data": "broadcast_cancel"}]]}
                    await send_message(chat_id, "👆 **ይሄ መልዕክት (ከነ አዝራሮቹ) ለሁሉም ተጠቃሚዎች ይላክ?**\n\nConfirm to broadcast.", reply_markup=kb)
                    return

                if "audio" in message or "voice" in message:
                    file_obj = message.get("audio") or message.get("voice")
                    file_id = file_obj.get("file_id")
                    caption = message.get("caption") or ""
                    file_name = caption.split('\n')[0] if caption else (file_obj.get("file_name", "Unknown Audio"))
                    clean_name = file_name.strip()
                    clean_search = clean_name.replace("@Almadihbot", "").strip()
                    if len(clean_search) > 3:
                        await db.files.update_one(
                            {"display_name": {"$regex": re.escape(clean_search), "$options": "i"}},
                            {"$set": {"file_id": file_id, "display_name": clean_name}},
                            upsert=True
                        )
                        await send_message(chat_id, f"✅ **Admin Upload:** `{clean_name}` saved!")
                    return

            if not await check_membership(user_id):
                msg = "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**"
                kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}], [{"text": "✅ ተቀላቅያለሁ (Verify)", "callback_data": "check_subscription"}]]}
                await send_message(chat_id, msg, reply_markup=kb)
                return

            if str(user_id) == str(ADMIN_ID):
                if text == "/start" or text == "/admin" or text == "🔙 Back":
                    msg = "👋 **ሰላም አለቃ! (Admin Panel)**\n\nከታች ባሉት አዝራሮች ቦቱን ይቆጣጠሩ።"
                    admin_kb = {"keyboard": [[{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}], [{"text": "📢 Broadcast"}, {"text": "👥 User Count"}], [{"text": "📂 Total Files"}]], "resize_keyboard": True}
                    await send_message(chat_id, msg, reply_markup=admin_kb)
                    return 
                elif text == "📊 Statistics":
                    users = await db.users.count_documents({})
                    files = await db.files.count_documents({})
                    await send_message(chat_id, f"📊 **General Stats:**\n\n👥 Users: `{users}`\n📂 Files: `{files}`")
                    return
                elif text == "📅 Daily Stats":
                    stats_msg = await get_daily_stats(db)
                    await send_message(chat_id, stats_msg)
                    return
                elif text == "📢 Broadcast":
                    await set_user_state(db, user_id, "broadcast_wait")
                    await send_message(chat_id, "📢 **Broadcast Mode**\n\nለተጠቃሚዎች መላክ የሚፈልጉትን መልዕክት (ጽሁፍ፣ ፎቶ፣ ድምፅ) **አሁን ይላኩ**።\n\n(ለመተው '🔙 Back' ይበሉ)")
                    return
                elif text == "👥 User Count":
                    users = await db.users.count_documents({})
                    await send_message(chat_id, f"👥 አጠቃላይ ተጠቃሚዎች: `{users}`")
                    return
                elif text == "📂 Total Files":
                    files = await db.files.count_documents({})
                    await send_message(chat_id, f"📂 የተጫኑ መንዙማዎች: `{files}`")
                    return

            if text == "/start":
                welcome = ("*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*\n\nከ 1,200 በላይ መንዙማዎችን እዚህ ያገኛሉ።\n\n👇 **አጠቃቀም:**\n• ዝም ብለው ስም ይጻፉ (Direct).\n• `/list` ብለው ሙሉ ዝርዝር በገጽ ማየት ይችላሉ።")
                kb = {
                    "inline_keyboard": [
                        [{"text": "🔥 Trending", "switch_inline_query_current_chat": "#trending"}, {"text": "🆕 New", "switch_inline_query_current_chat": "#new"}],
                        [{"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"}, {"text": "📂 Catalog (List)", "callback_data": "pg_1"}],
                        [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}]
                    ]
                }
                await send_message(chat_id, welcome, reply_markup=kb)
            elif text == "/list" or text == "📂 Catalog (List)":
                msg_text, kb = await get_catalog_page(db, 1) 
                await send_message(chat_id, msg_text, reply_markup=kb)
            elif text and not text.startswith("/"):
                search_query = build_search_query(text)
                if not search_query:
                    await send_message(chat_id, "⚠️ እባክዎ ትክክለኛ ስም ያስገቡ።")
                    return
                doc = await db.files.find_one(search_query)
                if doc:
                    if 'file_id' in doc:
                        short_id = str(doc['_id'])
                        kb = {"inline_keyboard": [[{"text": "❤️ Add to Favorite", "callback_data": f"fav_{short_id}"}], [{"text": "↗️ Share", "switch_inline_query": ""}, {"text": "⚠️ Report", "callback_data": f"report_{short_id}"}]]}
                        await send_audio(chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot", kb)
                        await increment_view(db, doc['file_id'])
                    else:
                        await send_message(chat_id, "⚠️ ፋይሉ ተገኝቷል ግን ኦዲዮው ጠፍቷል።")
                else:
                    await send_message(chat_id, "😔 ይቅርታ፣ አልተገኘም።")

        elif "inline_query" in data:
            iq = data["inline_query"]
            query_id = iq["id"]
            user_id = iq.get("from", {}).get("id")
            first_name = iq.get("from", {}).get("first_name", "User")
            query = iq.get("query", "").strip().lower()

            await track_user(db, user_id, first_name)

            if not await check_membership(user_id):
                await answer_inline_query(query_id, [], "⚠️ Join Channel First", "start")
                return

            cursor = None
            results = []
            
            # --- FIX: Handle Empty Query Correctly ---
            if not query or query.startswith("#random"):
                 # If query is empty OR explicitly #random, show 50 random files (Variety!)
                 pipeline = [{"$match": {"file_id": {"$exists": True}}}, {"$sample": {"size": 50}}]
                 cursor = db.files.aggregate(pipeline)
            
            elif query.startswith("#trending"):
                filter_text = query.replace("#trending", "").strip()
                match_stage = {"file_id": {"$exists": True}}
                if filter_text:
                    match_stage["display_name"] = {"$regex": re.escape(filter_text), "$options": "i"}
                pipeline = [{"$match": match_stage}, {"$addFields": {"views_safe": {"$ifNull": ["$views", 0]}}}, {"$sort": {"views_safe": -1, "_id": -1}}, {"$limit": 50}]
                cursor = db.files.aggregate(pipeline)
            
            elif query.startswith("#new"):
                filter_text = query.replace("#new", "").strip()
                search_filter = {"file_id": {"$exists": True}}
                if filter_text: search_filter["display_name"] = {"$regex": re.escape(filter_text), "$options": "i"}
                cursor = db.files.find(search_filter).sort("_id", -1).limit(50)
            
            elif query.startswith("#favorites"):
                user = await db.users.find_one({"_id": user_id})
                fav_ids = user.get("favorites", []) if user else []
                if fav_ids:
                    filter_text = query.replace("#favorites", "").strip()
                    search_filter = {"file_id": {"$in": fav_ids}}
                    if filter_text: search_filter["display_name"] = {"$regex": re.escape(filter_text), "$options": "i"}
                    cursor = db.files.find(search_filter).limit(50)
            
            else:
                # Text Search - Force file_id check to avoid empty results
                search_criteria = build_search_query(query)
                search_criteria["file_id"] = {"$exists": True} # <--- CRITICAL FIX
                cursor = db.files.find(search_criteria).sort("_id", -1).limit(50)

            if cursor:
                docs = await cursor.to_list(length=50)
                for doc in docs:
                    if doc.get('file_id'):
                        results.append({
                            "type": "audio",
                            "id": str(doc["_id"]),
                            "audio_file_id": doc["file_id"],
                            "caption": f"{doc.get('display_name')}\n\n@Almadihbot"
                        })

            await answer_inline_query(query_id, results, cache_time=300)

    except Exception as e:
        logger.error(f"Logic Error: {e}")
        traceback.print_exc()
    finally:
        db_client.close()

# --- Webhook Routes ---
@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            run_async(process_telegram_update(data))
            return jsonify({"status": "ok"}), 200
        except Exception as e:
            logger.error(f"Webhook Error: {e}")
            return jsonify({"status": "error"}), 500
    return 'Al-Madih Bot Running (Cached & Optimized) 🚀'

if __name__ == '__main__':
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
