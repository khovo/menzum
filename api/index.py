from flask import Flask, request
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
import asyncio
import logging
import aiohttp 
import re
import time
from datetime import datetime, timedelta

# Logging
logging.basicConfig(level=logging.ERROR) # Only log errors for speed
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID = os.environ.get("ADMIN_ID")

FORCE_CHANNEL_USERNAME = "Al_madih" 
FORCE_CHANNEL_URL = "https://t.me/Al_madih"

ITEMS_PER_PAGE = 10 

# --- OPTIMIZATION: GLOBAL DB CONNECTION ---
# Establish connection once, reuse across requests
try:
    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]
except:
    db_client = None
    db = None

# --- IN-MEMORY CACHES (THE SPEED BOOSTERS) ---
MEMBERSHIP_CACHE = {}  # {user_id: timestamp} - Don't check TG API every time
USER_UPDATE_CACHE = {} # {user_id: timestamp} - Don't write to DB every time
CACHED_EMPTY_RESULT = {"data": [], "time": 0} # Cache for empty @almadihbot query
CACHE_TTL = 300 # 5 Minutes

# --- Helpers ---
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def send_request(method, payload):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp: return await resp.json()
        except: return None

async def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    return await send_request("sendMessage", payload)

async def send_audio(chat_id, audio_file_id, caption, reply_markup=None):
    payload = {"chat_id": chat_id, "audio": audio_file_id, "caption": caption, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    return await send_request("sendAudio", payload)

async def edit_message_text(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    return await send_request("editMessageText", payload)

async def answer_callback_query(callback_query_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    if show_alert: payload["show_alert"] = True
    return await send_request("answerCallbackQuery", payload)

async def answer_inline_query(query_id, results, cache_time=300):
    # switch_pm options removed to make it faster/simpler
    payload = {"inline_query_id": query_id, "results": results, "cache_time": cache_time}
    return await send_request("answerInlineQuery", payload)

# --- OPTIMIZED MEMBERSHIP CHECK ---
async def check_membership(user_id):
    if not BOT_TOKEN: return True
    
    # 1. Check Cache (Fastest)
    current_time = time.time()
    if user_id in MEMBERSHIP_CACHE:
        if current_time - MEMBERSHIP_CACHE[user_id] < 300: # Valid for 5 mins
            return True
    
    # 2. Check API (Slower)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                res = await resp.json()
                if not res.get("ok"): return True 
                status = res["result"]["status"]
                is_member = status in ["creator", "administrator", "member"]
                if is_member:
                    MEMBERSHIP_CACHE[user_id] = current_time # Cache it!
                return is_member
        except: return True

# --- OPTIMIZED USER TRACKING ---
async def track_user(user_id, first_name):
    # Only update DB once per hour per user to save resources
    current_time = time.time()
    if user_id in USER_UPDATE_CACHE:
        if current_time - USER_UPDATE_CACHE[user_id] < 3600: # 1 Hour
            return # Skip DB write
            
    try:
        now = datetime.now()
        await db.users.update_one(
            {"_id": int(user_id)},
            {"$set": {"first_name": first_name, "last_active": now}, "$setOnInsert": {"joined_at": now}},
            upsert=True
        )
        USER_UPDATE_CACHE[user_id] = current_time
    except: pass

async def toggle_favorite(user_id, file_id):
    try:
        # Optimistic update - assume Int ID mostly
        res = await db.users.update_one({"_id": int(user_id)}, {"$addToSet": {"favorites": file_id}})
        if res.modified_count > 0: return True # Added
        
        # If not modified, maybe it was already there? Try remove
        res = await db.users.update_one({"_id": int(user_id)}, {"$pull": {"favorites": file_id}})
        if res.modified_count > 0: return False # Removed
        
        # If user not found (rare case if track_user works), try legacy string ID
        res = await db.users.update_one({"_id": str(user_id)}, {"$addToSet": {"favorites": file_id}})
        return True
    except: return False

def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    if len(query_text) == 1:
        return {"display_name": {"$regex": f"^{re.escape(query_text)}", "$options": "i"}}
    words = query_text.split()
    conditions = [{"display_name": {"$regex": re.escape(word), "$options": "i"}} for word in words]
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}

async def get_catalog_page(page):
    skip = (page - 1) * ITEMS_PER_PAGE
    # Only fetch needed fields
    cursor = db.files.find({"file_id": {"$exists": True}}, {"display_name": 1}).sort("_id", -1).skip(skip).limit(ITEMS_PER_PAGE)
    
    # Estimate count to avoid heavy count_documents query on every page
    total_docs = 1400 # Hardcoded estimate for speed or cache this count later
    total_pages = (total_docs + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    msg_text = f"📂 **የመንዙማዎች ዝርዝር (ገጽ {page})**\n\n💡 _ስሙን ሲነኩት ኮፒ ይሆናል፣ ከዛ ለቦቱ ይላኩት።_\n\n"
    idx = skip + 1
    async for doc in cursor:
        clean_name = doc.get("display_name", "Unknown").replace("`", "") 
        msg_text += f"{idx}. `{clean_name}`\n"
        idx += 1
    
    buttons = []
    nav_row = []
    if page > 1: nav_row.append({"text": "⬅️ Back", "callback_data": f"pg_{page-1}"})
    nav_row.append({"text": "❌ ዝጋ", "callback_data": "pg_close"})
    nav_row.append({"text": "Next ➡️", "callback_data": f"pg_{page+1}"})
    buttons.append(nav_row)
    return msg_text, {"inline_keyboard": buttons}

def get_main_menu_kb():
    return {
        "inline_keyboard": [
            [
                {"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"},
                {"text": "📂 Catalog (List)", "callback_data": "pg_1"}
            ],
            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}]
        ]
    }

# --- Main Logic ---
async def process_telegram_update(data):
    if not db: return # DB down? Exit fast.

    try:
        # 1. Callback Query (Buttons) - Handles FAST
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            message_id = cb["message"]["message_id"]
            
            # Simple answer first to stop loading animation
            # await answer_callback_query(cb_id) 

            if data_str == "check_subscription":
                if await check_membership(user_id):
                    await answer_callback_query(cb_id, "✅ ተቀላቅለዋል!")
                    await edit_message_text(chat_id, message_id, "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*", reply_markup=get_main_menu_kb())
                else:
                    await answer_callback_query(cb_id, "❌ አሁንም አልተቀላቀሉም!", show_alert=True)
                return

            if data_str.startswith("fav_"):
                doc_id = data_str.split("fav_")[1]
                # We assume doc_id passed is file_id for speed in some contexts, but here it's likely ObjectId
                # Or we can just toggle. 
                # Optimization: Don't check file existence in DB, just toggle ID. 
                # If ID is bad, it just won't show up in list.
                # However, to be safe, let's just toggle.
                # If doc_id len is 24, it's objectId. If longer, it's file_id.
                
                # Fetch only if needed to get file_id from ObjectId
                target_file_id = doc_id
                if len(doc_id) == 24:
                    f = await db.files.find_one({"_id": ObjectId(doc_id)}, {"file_id": 1})
                    if f: target_file_id = f['file_id']
                
                is_fav = await toggle_favorite(user_id, target_file_id)
                text = "❤️ Saved" if is_fav else "💔 Removed"
                await answer_callback_query(cb_id, text)
            
            elif data_str.startswith("pg_"):
                 if data_str == "pg_close":
                    await edit_message_text(chat_id, message_id, "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*", reply_markup=get_main_menu_kb())
                 else:
                    new_page = int(data_str.split("_")[1])
                    text, kb = await get_catalog_page(new_page)
                    await edit_message_text(chat_id, message_id, text, reply_markup=kb)
                 await answer_callback_query(cb_id)

            elif data_str.startswith("report_"):
                await answer_callback_query(cb_id, "✅ ሪፖርት ተልኳል!", show_alert=True)
                # Fire and forget report to admin to save time
                asyncio.create_task(send_message(ADMIN_ID, f"Report: {data_str} by {user_id}"))

            return

        # 2. Message Handling
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            first_name = message.get("from", {}).get("first_name", "User")
            text = message.get("text", "")
            
            # Fire and forget tracking
            asyncio.create_task(track_user(user_id, first_name))

            if text == "/start":
                # FASTEST RESPONSE
                await send_message(chat_id, "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*", reply_markup=get_main_menu_kb())
                return

            if not await check_membership(user_id):
                kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}], [{"text": "✅ ተቀላቅያለሁ (Verify)", "callback_data": "check_subscription"}]]}
                await send_message(chat_id, "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**", reply_markup=kb)
                return

            if text == "/list" or text == "📂 Catalog (List)":
                msg, kb = await get_catalog_page(1)
                await send_message(chat_id, msg, reply_markup=kb)
                return

            # Admin & File Upload Logic (Simplified)
            if str(user_id) == str(ADMIN_ID):
                if text == "/admin":
                    await send_message(chat_id, "Admin: `/stats`")
                elif text == "/stats":
                    u = await db.users.count_documents({})
                    f = await db.files.count_documents({})
                    await send_message(chat_id, f"Users: {u}, Files: {f}")
                
                if "audio" in message or "voice" in message:
                    file_obj = message.get("audio") or message.get("voice")
                    clean_name = (message.get("caption") or file_obj.get("file_name", "Audio")).split('\n')[0].strip()
                    clean_search = clean_name.replace("@Almadihbot", "").strip()
                    if len(clean_search) > 2:
                        await db.files.update_one(
                            {"display_name": {"$regex": re.escape(clean_search), "$options": "i"}},
                            {"$set": {"file_id": file_obj.get("file_id"), "display_name": clean_name}},
                            upsert=True
                        )
                        await send_message(chat_id, "✅ Saved")
                return

            # Text Search
            if text and not text.startswith("/"):
                query = build_search_query(text)
                doc = await db.files.find_one(query, {"file_id": 1, "display_name": 1})
                if doc:
                    kb = {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }], [{"text": "↗️ Share", "switch_inline_query": ""}, {"text": "⚠️ Report", "callback_data": f"report_{str(doc['_id'])}" }]]}
                    await send_audio(chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot", kb)
                    # Don't wait for increment view
                    asyncio.create_task(db.files.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}}))
                else:
                    await send_message(chat_id, "😔 አልተገኘም።")

        # 3. Inline Query (OPTIMIZED)
        elif "inline_query" in data:
            iq = data["inline_query"]
            query_id = iq["id"]
            user_id = iq.get("from", {}).get("id")
            query = iq.get("query", "").strip().lower()

            # Membership check first (Cached)
            if not await check_membership(user_id):
                await answer_inline_query(query_id, [], cache_time=300)
                return

            results = []

            # A. Favorites
            if query.startswith("#favorites"):
                user = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
                # Fallback to string if int failed
                if not user: user = await db.users.find_one({"_id": str(user_id)}, {"favorites": 1})
                
                fav_ids = user.get("favorites", []) if user else []
                if fav_ids:
                    # Fetch only needed fields
                    cursor = db.files.find({"file_id": {"$in": fav_ids}}, {"file_id": 1, "display_name": 1}).limit(50)
                    docs = await cursor.to_list(length=50)
                    for doc in docs:
                        results.append({
                            "type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"],
                            "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                            "reply_markup": {"inline_keyboard": [[{"text": "💔 Remove", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                        })
                else:
                     results.append({"type": "article", "id": "404", "title": "No Favorites", "input_message_content": {"message_text": "No favorites yet."}})

            # B. Empty Query (Global List)
            elif not query:
                # Check Cache
                if CACHED_EMPTY_RESULT["data"] and (time.time() - CACHED_EMPTY_RESULT["time"] < CACHE_TTL):
                    await answer_inline_query(query_id, CACHED_EMPTY_RESULT["data"], cache_time=300)
                    return
                
                # Fetch fresh (Sort by ID desc = Newest)
                cursor = db.files.find({"file_id": {"$exists": True}}, {"file_id": 1, "display_name": 1}).sort("_id", -1).limit(20)
                docs = await cursor.to_list(length=20)
                for doc in docs:
                     results.append({
                        "type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"],
                        "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                         "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                    })
                
                # Update Cache
                if results:
                    CACHED_EMPTY_RESULT["data"] = results
                    CACHED_EMPTY_RESULT["time"] = time.time()

            # C. Search Query
            else:
                mongo_query = build_search_query(query)
                mongo_query["file_id"] = {"$exists": True}
                
                # No Sort for search = FAST
                cursor = db.files.find(mongo_query, {"file_id": 1, "display_name": 1}).limit(20)
                docs = await cursor.to_list(length=20)
                for doc in docs:
                     results.append({
                        "type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"],
                        "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                         "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                    })

            await answer_inline_query(query_id, results, cache_time=300)

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        pass # Client is global now

@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            run_async(process_telegram_update(data))
            return 'ok'
        except: return 'error', 500
    return 'Al-Madih Bot Running (Ultra Fast Mode) 🚀'

if __name__ == '__main__':
    app.run(debug=True)
