5from flask import Flask, request
from pymongo import MongoClient 
from bson import ObjectId
import os
import asyncio
import logging
import aiohttp 
import re
from datetime import datetime

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID = os.environ.get("ADMIN_ID")
FORCE_CHANNEL_USERNAME = "Al_madih" 
FORCE_CHANNEL_URL = "https://t.me/Al_madih"
ITEMS_PER_PAGE = 50 

# --- Database Connection (PyMongo) ---
try:
    mongo_client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = mongo_client["MenzumaDB"]
    mongo_client.server_info()
    logger.info("✅ Database Connected")
except Exception as e:
    logger.error(f"❌ Database Error: {e}")
    db = None

# --- Async Helper ---
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def telegram_request(method, payload=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except: return None

# --- Logic Helpers ---
async def check_membership(user_id):
    res = await telegram_request("getChatMember", {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id})
    if res and res.get("ok"):
        return res["result"]["status"] in ["creator", "administrator", "member"]
    return True 

def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    if query_text.startswith("#"): return {} 
    
    # Text Search (Regex)
    if len(query_text) == 1:
        return {"display_name": {"$regex": re.escape(query_text), "$options": "i"}}
    
    words = query_text.split()
    regex_pattern = ""
    for word in words:
        regex_pattern += f"(?=.*{re.escape(word)})"
    return {"display_name": {"$regex": f"^{regex_pattern}", "$options": "i"}}

# --- Main Processor ---
async def process_update(data):
    if not BOT_TOKEN: return

    try:
        # 1. Inline Query (Infinite Scroll Fixed)
        if "inline_query" in data:
            iq = data["inline_query"]
            query_id = iq["id"]
            user_id = iq.get("from", {}).get("id")
            query = iq.get("query", "").strip()
            offset = iq.get("offset", "") # Offset መቀበል

            if not await check_membership(user_id):
                 await telegram_request("answerInlineQuery", {
                    "inline_query_id": query_id, 
                    "results": [], 
                    "switch_pm_text": "⚠️ Join Channel First", 
                    "switch_pm_parameter": "start", 
                    "cache_time": 5
                })
                 return

            # Pagination Logic
            skip = int(offset) if offset and offset.isdigit() else 0
            limit = ITEMS_PER_PAGE
            
            cursor = None
            
            # --- Search Logic ---
            if query.startswith("#"):
                 if query.startswith("#new"):
                     cursor = db.files.find({"file_id": {"$exists": True}}).sort("_id", -1).skip(skip).limit(limit)
                 elif query.startswith("#trending"):
                     cursor = db.files.find({"file_id": {"$exists": True}}).sort([("views", -1), ("_id", -1)]).skip(skip).limit(limit)
                 elif query.startswith("#random"):
                     cursor = db.files.aggregate([{"$match": {"file_id": {"$exists": True}}}, {"$sample": {"size": limit}}])
                 elif query.startswith("#favorites"):
                     user = db.users.find_one({"_id": user_id})
                     if user and user.get("favorites"):
                         cursor = db.files.find({"file_id": {"$in": user["favorites"]}}).skip(skip).limit(limit)
            else:
                search_filter = {"file_id": {"$exists": True}}
                if query:
                    search_filter["display_name"] = {"$regex": re.escape(query), "$options": "i"}
                
                # 🔥 ባዶ ከሆነ ሁሉንም ያመጣል (Show All)
                cursor = db.files.find(search_filter).sort("_id", -1).skip(skip).limit(limit)

            results = []
            if cursor:
                # PyMongoን ቀጥታ መጠቀም (Cursor to List)
                docs = list(cursor) 
                for doc in docs:
                    if doc.get('file_id'):
                        results.append({
                            "type": "audio",
                            "id": str(doc["_id"]),
                            "audio_file_id": doc["file_id"],
                            "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                            "title": doc.get('display_name', 'Menzuma Audio') 
                        })

            # 🔥 Next Offset ማስላት (Scroll እንዲያደርግ)
            next_offset = str(skip + limit) if len(results) >= limit else ""

            await telegram_request("answerInlineQuery", {
                "inline_query_id": query_id,
                "results": results,
                "next_offset": next_offset, # ይሄ ነው ወሳኙ!
                "cache_time": 0, 
                "is_personal": True
            })
            return

        # 2. Callback & Message Handling
        if "callback_query" in data:
            cb = data["callback_query"]
            data_str = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            
            await telegram_request("answerCallbackQuery", {"callback_query_id": cb["id"]})
            
            if data_str.startswith("fav_"):
                 doc_id = data_str.split("fav_")[1]
                 try:
                    file_doc = db.files.find_one({"_id": ObjectId(doc_id)})
                    if file_doc:
                        file_id = file_doc['file_id']
                        user = db.users.find_one({"_id": cb["from"]["id"]})
                        favs = user.get("favorites", []) if user else []
                        if file_id in favs:
                            db.users.update_one({"_id": cb["from"]["id"]}, {"$pull": {"favorites": file_id}})
                        else:
                            db.users.update_one({"_id": cb["from"]["id"]}, {"$addToSet": {"favorites": file_id}}, upsert=True)
                 except: pass

        if "message" in data:
            msg = data["message"]
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "")

            if text == "/start":
                kb = {
                    "inline_keyboard": [
                        [{"text": "🔥 Trending", "switch_inline_query_current_chat": "#trending"}, {"text": "🆕 New", "switch_inline_query_current_chat": "#new"}],
                        [{"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"}, {"text": "🔍 Search", "switch_inline_query_current_chat": ""}]
                    ]
                }
                await telegram_request("sendMessage", {"chat_id": chat_id, "text": "🌙 **አል-ማዲህ ቦት**\n\nከ 1,200 በላይ መንዙማዎች!", "parse_mode": "Markdown", "reply_markup": kb})

            elif text and not text.startswith("/"):
                doc = db.files.find_one({"display_name": {"$regex": re.escape(text.strip()), "$options": "i"}, "file_id": {"$exists": True}})
                if doc:
                     kb = {"inline_keyboard": [[{"text": "❤️ Add", "callback_data": f"fav_{doc['_id']}"}], [{"text": "↗️ Share", "switch_inline_query": ""}]]}
                     await telegram_request("sendAudio", {"chat_id": chat_id, "audio": doc['file_id'], "caption": f"{doc.get('display_name')}\n\n@Almadihbot", "reply_markup": kb})
                else:
                     await telegram_request("sendMessage", {"chat_id": chat_id, "text": "😔 አልተገኘም።"})

    except Exception as e:
        logger.error(f"Err: {e}")

@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        run_async(process_update(request.get_json()))
        return 'ok'
    return 'Bot Running 🚀'

if __name__ == '__main__':
    app.run(debug=True)
