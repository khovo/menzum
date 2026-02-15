import os
import re
import time
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# --- CONFIGURATION & SETUP ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("AlMadihBot")

app = Flask(__name__)

# Load Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID = os.environ.get("ADMIN_ID") 

# Channel Config
FORCE_CHANNEL_USERNAME = "Al_madih" 
FORCE_CHANNEL_URL = "https://t.me/Al_madih"
STORAGE_CHANNEL_ID = -1003561085933  # Your private storage channel
ITEMS_PER_PAGE = 10 

# Cache System (In-Memory)
MEMBERSHIP_CACHE = {} 
CACHED_EMPTY_RESULT = {"data": [], "time": 0}
CACHE_TTL = 60  # Cache duration in seconds

# --- ASYNC HELPER FOR FLASK ---
def run_async(coro):
    """Helper to run async code in Sync Flask environment"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    if loop.is_running():
        # If we are in an environment where the loop is already running (rare for sync flask)
        return asyncio.ensure_future(coro)
    return loop.run_until_complete(coro)

# --- TELEGRAM API HELPERS ---
async def telegram_request(session, method, payload=None):
    """Generic wrapper for Telegram API calls"""
    if not BOT_TOKEN: return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        async with session.post(url, json=payload or {}) as resp:
            return await resp.json()
    except Exception as e:
        logger.error(f"API Error ({method}): {e}")
        return None

async def send_message(session, chat_id, text, reply_markup=None):
    return await telegram_request(session, "sendMessage", {
        "chat_id": chat_id, 
        "text": text, 
        "parse_mode": "Markdown", 
        "reply_markup": reply_markup
    })

async def send_audio(session, chat_id, audio_file_id, caption, reply_markup=None):
    return await telegram_request(session, "sendAudio", {
        "chat_id": chat_id, 
        "audio": audio_file_id, 
        "caption": caption, 
        "parse_mode": "Markdown", 
        "reply_markup": reply_markup
    })

async def edit_message_text(session, chat_id, message_id, text, reply_markup=None):
    return await telegram_request(session, "editMessageText", {
        "chat_id": chat_id, 
        "message_id": message_id, 
        "text": text, 
        "parse_mode": "Markdown", 
        "disable_web_page_preview": True,
        "reply_markup": reply_markup
    })

async def answer_callback_query(session, callback_query_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    if show_alert: payload["show_alert"] = True
    return await telegram_request(session, "answerCallbackQuery", payload)

async def copy_message(session, chat_id, from_chat_id, message_id, reply_markup=None):
    payload = {
        "chat_id": chat_id, 
        "from_chat_id": from_chat_id, 
        "message_id": message_id
    }
    if reply_markup: payload["reply_markup"] = reply_markup
    return await telegram_request(session, "copyMessage", payload)

async def answer_inline_query(session, query_id, results, switch_pm_text=None, switch_pm_param=None, cache_time=300):
    payload = {
        "inline_query_id": query_id, 
        "results": results, 
        "cache_time": cache_time, 
        "is_personal": True
    }
    if switch_pm_text:
        payload["switch_pm_text"] = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    return await telegram_request(session, "answerInlineQuery", payload)

async def check_membership(session, user_id):
    """Optimized membership check with caching"""
    if not BOT_TOKEN: return True
    
    current_time = time.time()
    
    # 1. Check Cache
    if user_id in MEMBERSHIP_CACHE:
        is_member, timestamp = MEMBERSHIP_CACHE[user_id]
        if current_time - timestamp < CACHE_TTL:
            return is_member

    # 2. Check API
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    try:
        async with session.get(url, params=params) as resp:
            res = await resp.json()
            if not res.get("ok"): return True  # Fail open if error
            
            status = res["result"]["status"]
            is_member = status in ["creator", "administrator", "member"]
            
            # Update Cache
            MEMBERSHIP_CACHE[user_id] = (is_member, current_time)
            return is_member
    except:
        return True

# --- DATABASE HELPERS ---
async def track_user(db, user_id, first_name):
    try:
        now = datetime.now()
        await db.users.update_one(
            {"_id": int(user_id)},
            {"$set": {"first_name": first_name, "last_active": now}, "$setOnInsert": {"joined_at": now}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Track User Error: {e}")

async def toggle_favorite(db, user_id, file_id):
    try:
        # Normalize ID to int, handle legacy string IDs
        user_query = {"$or": [{"_id": int(user_id)}, {"_id": str(user_id)}]}
        user = await db.users.find_one(user_query, {"favorites": 1, "_id": 1})
        
        target_id = user["_id"] if user else int(user_id)
        favorites = user.get("favorites", []) if user else []
        
        if file_id in favorites:
            await db.users.update_one({"_id": target_id}, {"$pull": {"favorites": file_id}})
            return False
        else:
            await db.users.update_one({"_id": target_id}, {"$addToSet": {"favorites": file_id}})
            return True
    except: return False

async def get_catalog_page(db, page):
    limit = ITEMS_PER_PAGE
    skip = (page - 1) * limit
    
    total_docs = await db.files.count_documents({"file_id": {"$exists": True}})
    total_pages = (total_docs + limit - 1) // limit
    
    cursor = db.files.find(
        {"file_id": {"$exists": True}},
        {"display_name": 1}
    ).sort("_id", -1).skip(skip).limit(limit)
    
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

def get_main_menu_kb():
    return {
        "inline_keyboard": [
            [
                {"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"},
                {"text": "📂 Catalog (List)", "callback_data": "pg_1"}
            ],
            [{"text": "📞 አስተያየት ለመስጠት (Support)", "callback_data": "support_start"}],
            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}]
        ]
    }

def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    # Simple regex search
    return {"display_name": {"$regex": re.escape(query_text), "$options": "i"}}

# --- MAIN LOGIC ENGINE ---
async def process_telegram_update(data):
    if not MONGO_URL or not BOT_TOKEN:
        logger.error("Missing ENV Variables")
        return

    # Create DB Connection (Efficient for Vercel/Serverless per request)
    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]

    # Create Client Session
    async with aiohttp.ClientSession() as session:
        try:
            # 1. CALLBACK QUERIES (BUTTON CLICKS)
            if "callback_query" in data:
                cb = data["callback_query"]
                user_id = cb["from"]["id"]
                cb_id = cb["id"]
                data_str = cb.get("data", "")
                message = cb.get("message")
                chat_id = message["chat"]["id"] if message else user_id
                message_id = message["message_id"] if message else None

                # Security: Membership Check (except for join verification)
                if data_str != "check_subscription":
                    if not await check_membership(session, user_id):
                        await answer_callback_query(session, cb_id, "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!", show_alert=True)
                        return 

                # Handle Subcription Check
                if data_str == "check_subscription":
                    # Force clear cache to re-check real status
                    if user_id in MEMBERSHIP_CACHE: del MEMBERSHIP_CACHE[user_id]
                    
                    if await check_membership(session, user_id):
                        await answer_callback_query(session, cb_id, "✅ እንኳን ደህና መጡ!")
                        welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                        await edit_message_text(session, chat_id, message_id, welcome, reply_markup=get_main_menu_kb())
                    else:
                        await answer_callback_query(session, cb_id, "❌ አሁንም አልተቀላቀሉም! ቻናሉን Join ይበሉ", show_alert=True)
                
                # Catalog Pagination
                elif data_str.startswith("pg_"):
                    if data_str == "pg_close":
                        welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                        await edit_message_text(session, chat_id, message_id, welcome, reply_markup=get_main_menu_kb())
                    else:
                        page = int(data_str.split("_")[1])
                        text, kb = await get_catalog_page(db, page)
                        await edit_message_text(session, chat_id, message_id, text, reply_markup=kb)
                    await answer_callback_query(session, cb_id)

                # Support System
                elif data_str == "support_start":
                    await db.users.update_one({"_id": int(user_id)}, {"$set": {"state": "support_wait"}}, upsert=True)
                    kb = {"inline_keyboard": [[{"text": "🔙 ተመለስ", "callback_data": "support_cancel"}]]}
                    await edit_message_text(session, chat_id, message_id, "📝 **ሀሳቦን እዚህ ጋር ይጻፉ ወይም 'ተመለስ' የሚለውን በተን ይጫኑ።**", reply_markup=kb)
                    await answer_callback_query(session, cb_id)
                
                elif data_str == "support_cancel":
                    await db.users.update_one({"_id": int(user_id)}, {"$set": {"state": "idle"}})
                    welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                    await edit_message_text(session, chat_id, message_id, welcome, reply_markup=get_main_menu_kb())
                    await answer_callback_query(session, cb_id)

                # Admin Reply Setup
                elif data_str.startswith("reply_") and str(user_id) == str(ADMIN_ID):
                    target_user_id = data_str.split("_")[1]
                    await db.users.update_one({"_id": int(user_id)}, {"$set": {"state": "admin_reply_wait", "reply_target": target_user_id}}, upsert=True)
                    await send_message(session, chat_id, f"📝 **መልስ ለተጠቃሚ {target_user_id} እየጻፉ ነው:**")
                    await answer_callback_query(session, cb_id)

                # Favorites Toggle
                elif data_str.startswith("fav_"):
                    doc_id = data_str.split("fav_")[1]
                    try:
                        file_doc = await db.files.find_one({"_id": ObjectId(doc_id)}, {"file_id": 1})
                        if file_doc:
                            is_fav = await toggle_favorite(db, user_id, file_doc['file_id'])
                            await answer_callback_query(session, cb_id, "❤️ Saved" if is_fav else "💔 Removed")
                        else:
                            await answer_callback_query(session, cb_id, "⚠️ File not found")
                    except:
                        await answer_callback_query(session, cb_id, "❌ Error")

            # 2. MESSAGE HANDLING
            elif "message" in data:
                message = data["message"]
                chat_id = message["chat"]["id"]
                user_id = message["from"]["id"]
                text = message.get("text", "")

                # Membership Check
                if not await check_membership(session, user_id):
                    msg = "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**"
                    kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}], [{"text": "✅ ተቀላቅያለሁ (Verify)", "callback_data": "check_subscription"}]]}
                    await send_message(session, chat_id, msg, reply_markup=kb)
                    return

                # Start Command
                if text == "/start":
                    first_name = message["from"].get("first_name", "User")
                    await track_user(db, user_id, first_name)
                    welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                    await send_message(session, chat_id, welcome, reply_markup=get_main_menu_kb())
                    return

                # List Command
                if text == "/list" or text == "📂 Catalog (List)":
                    msg, kb = await get_catalog_page(db, 1)
                    await send_message(session, chat_id, msg, reply_markup=kb)
                    return

                # Get User State
                user_data = await db.users.find_one({"_id": int(user_id)})
                state = user_data.get("state") if user_data else None

                # Support Logic
                if state == "support_wait":
                    sender_name = message["from"].get("first_name", "User")
                    kb = {"inline_keyboard": [[{"text": "↩️ መልስ ለመስጠት (Reply)", "callback_data": f"reply_{user_id}"}]]}
                    
                    # Forward to Admin
                    await send_message(session, ADMIN_ID, f"📩 **Support Message from:** {sender_name} (`{user_id}`)", reply_markup=kb)
                    await copy_message(session, ADMIN_ID, chat_id, message["message_id"])
                    
                    # Confirm to User
                    await send_message(session, chat_id, "✅ **መልእክትዎ ተልኳል! እናመሰግናለን።**", reply_markup=get_main_menu_kb())
                    await db.users.update_one({"_id": int(user_id)}, {"$set": {"state": "idle"}})
                    return

                # Admin Logic
                if str(user_id) == str(ADMIN_ID):
                    # Admin Reply Logic
                    if state == "admin_reply_wait":
                        target = user_data.get("reply_target")
                        if target:
                            await send_message(session, target, "🔔 **ከአድሚኑ የተሰጠ መልስ:**")
                            await copy_message(session, target, chat_id, message["message_id"])
                            await send_message(session, chat_id, "✅ ተልኳል!")
                            await db.users.update_one({"_id": int(user_id)}, {"$set": {"state": "idle"}})
                        return
                    
                    # Admin: Save Audio
                    if "audio" in message:
                        audio = message["audio"]
                        # Use caption as name, or filename
                        name = message.get("caption", "").split('\n')[0].strip() or audio.get("file_name", "Unknown Audio")
                        
                        await db.files.update_one(
                            {"display_name": name}, # Avoid duplicates by name
                            {
                                "$set": {
                                    "file_id": audio["file_id"], 
                                    "display_name": name,
                                    "uploaded_at": datetime.now()
                                }
                            },
                            upsert=True
                        )
                        await send_message(session, chat_id, f"✅ **Saved:** `{name}`")
                        return

                # General Search (Text Message)
                if text and not text.startswith("/"):
                    query = build_search_query(text)
                    doc = await db.files.find_one(query)
                    if doc:
                        kb = {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }], [{"text": "↗️ Share", "switch_inline_query": text}]]}
                        await send_audio(session, chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot", kb)
                    else:
                        await send_message(session, chat_id, "😔 አልተገኘም።")

            # 3. INLINE QUERY (SEARCH ANYWHERE)
            elif "inline_query" in data:
                iq = data["inline_query"]
                query = iq["query"].strip().lower()
                query_id = iq["id"]
                iq_user_id = iq["from"]["id"]
                results = []

                # A. Favorites
                if query.startswith("#favorites") or query == "fav":
                    user = await db.users.find_one({"$or": [{"_id": int(iq_user_id)}, {"_id": str(iq_user_id)}]}, {"favorites": 1})
                    fav_ids = user.get("favorites", []) if user else []
                    
                    if fav_ids:
                        cursor = db.files.find({"file_id": {"$in": fav_ids}}).limit(50)
                        docs = await cursor.to_list(length=50)
                        for doc in docs:
                            results.append({
                                "type": "audio",
                                "id": str(doc["_id"]),
                                "audio_file_id": doc["file_id"],
                                "caption": f"{doc.get('display_name')}\n\n@Almadihbot"
                            })

                # B. Normal Search / Recent
                else:
                    mongo_query = build_search_query(query) if query else {"file_id": {"$exists": True}}
                    
                    # Optimize Empty Query with Cache
                    current_time = time.time()
                    if not query and CACHED_EMPTY_RESULT["data"] and (current_time - CACHED_EMPTY_RESULT["time"] < CACHE_TTL):
                        results = CACHED_EMPTY_RESULT["data"]
                    else:
                        cursor = db.files.find(mongo_query).sort("_id", -1).limit(50)
                        docs = await cursor.to_list(length=50)
                        
                        temp_results = []
                        for doc in docs:
                            temp_results.append({
                                "type": "audio",
                                "id": str(doc["_id"]),
                                "audio_file_id": doc["file_id"],
                                "caption": f"{doc.get('display_name')}\n\n@Almadihbot"
                            })
                        results = temp_results
                        
                        # Update cache only for empty query
                        if not query:
                            CACHED_EMPTY_RESULT["data"] = results
                            CACHED_EMPTY_RESULT["time"] = current_time

                await answer_inline_query(session, query_id, results)

        except Exception as e:
            logger.error(f"Update Error: {e}")
        finally:
            db_client.close() # Important for serverless connections

# --- FLASK ROUTES ---
@app.route('/', methods=['GET'])
def index():
    return jsonify({"status": "Al-Madih Bot is Running 🚀", "mode": "Async/Webhook"}), 200

@app.route('/api/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        # Fire and forget async task
        run_async(process_telegram_update(data))
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return "Error", 500

if __name__ == '__main__':
    app.run(debug=True, port=3000)

