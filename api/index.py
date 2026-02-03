from flask import Flask, request
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
ITEMS_PER_PAGE = 10 

# --- Database Connection (PyMongo - Stable) ---
try:
    # Connect Timeout 5s
    mongo_client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = mongo_client["MenzumaDB"]
    # Check connection immediately
    mongo_client.server_info()
    logger.info("✅ Database Connected Successfully (PyMongo Mode)")
except Exception as e:
    logger.error(f"❌ Database Connection Failed: {e}")

# --- Async Helper for Telegram API ---
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
    
    # 1 ፊደል ሲሆን (Regex)
    if len(query_text) == 1:
        return {"display_name": {"$regex": re.escape(query_text), "$options": "i"}}
    
    # ቃላትን መነጣጠል (AND Logic)
    words = query_text.split()
    regex_pattern = ""
    for word in words:
        regex_pattern += f"(?=.*{re.escape(word)})"
    return {"display_name": {"$regex": f"^{regex_pattern}", "$options": "i"}}

def get_stats():
    users = db.users.count_documents({})
    files = db.files.count_documents({})
    return f"📊 **Stats:**\n👥 Users: `{users}`\n📂 Files: `{files}`"

# --- Main Logic ---
async def process_update(data):
    if not MONGO_URL or not BOT_TOKEN: return

    try:
        # 1. Callback Query
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]

            if data_str.startswith("pg_"):
                if "close" in data_str:
                    await telegram_request("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "❌ ዝርዝሩ ተዘግቷል።"})
                else:
                    page = int(data_str.split("_")[1])
                    total = db.files.count_documents({"file_id": {"$exists": True}})
                    limit = ITEMS_PER_PAGE
                    skip = (page - 1) * limit
                    
                    # PyMongo Direct Query
                    cursor = db.files.find({"file_id": {"$exists": True}}).sort("_id", -1).skip(skip).limit(limit)
                    
                    txt = f"📂 **መንዙማዎች (ገጽ {page})**\n\n"
                    idx = skip + 1
                    for doc in cursor:
                        name = doc.get('display_name', 'Unknown').replace('`','')
                        txt += f"{idx}. `{name}`\n"
                        idx += 1
                    
                    btns = []
                    row = []
                    if page > 1: row.append({"text": "⬅️", "callback_data": f"pg_{page-1}"})
                    row.append({"text": "❌", "callback_data": "pg_close"})
                    if (skip + limit) < total: row.append({"text": "➡️", "callback_data": f"pg_{page+1}"})
                    btns.append(row)
                    
                    await telegram_request("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": txt, "parse_mode": "Markdown", "reply_markup": {"inline_keyboard": btns}})
                await telegram_request("answerCallbackQuery", {"callback_query_id": cb_id})

            elif data_str.startswith("fav_"):
                doc_id = data_str.split("fav_")[1]
                fdoc = db.files.find_one({"_id": ObjectId(doc_id)})
                if fdoc:
                    fid = fdoc['file_id']
                    user = db.users.find_one({"_id": user_id})
                    favs = user.get("favorites", []) if user else []
                    
                    if fid in favs:
                        db.users.update_one({"_id": user_id}, {"$pull": {"favorites": fid}})
                        is_fav = False
                        msg = "💔 ተሰርዟል"
                    else:
                        db.users.update_one({"_id": user_id}, {"$addToSet": {"favorites": fid}}, upsert=True)
                        is_fav = True
                        msg = "❤️ ተመዝግቧል"
                    
                    new_txt = "💔 Remove" if is_fav else "❤️ Add"
                    kb = {"inline_keyboard": [[{"text": new_txt, "callback_data": f"fav_{doc_id}"}], [{"text": "↗️ Share", "switch_inline_query": ""}, {"text": "⚠️ Report", "callback_data": f"report_{doc_id}"}]]}
                    await telegram_request("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": msg_id, "reply_markup": kb})
                    await telegram_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": msg})
            
            elif data_str == "check_subscription":
                 if await check_membership(user_id):
                     await telegram_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "✅ ገብተዋል!"})
                     welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                     kb = {"inline_keyboard": [[{"text": "🔥 ተወዳጅ", "switch_inline_query_current_chat": "#trending"}, {"text": "🆕 አዳዲስ", "switch_inline_query_current_chat": "#new"}], [{"text": "❤️ የእኔ ምርጫ", "switch_inline_query_current_chat": "#favorites"}, {"text": "📚 ማህደር", "callback_data": "pg_1"}], [{"text": "🔍 መንዙማ ይፈልጉ", "switch_inline_query_current_chat": ""}]]}
                     await telegram_request("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": welcome, "parse_mode": "Markdown", "reply_markup": kb})
                 else:
                     await telegram_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "❌ አልገቡም!", "show_alert": True})

            elif data_str.startswith("report_"):
                doc_id = data_str.split("report_")[1]
                fdoc = db.files.find_one({"_id": ObjectId(doc_id)})
                fname = fdoc.get("display_name", "Unknown") if fdoc else "Unknown"
                await telegram_request("sendMessage", {"chat_id": ADMIN_ID, "text": f"🚨 **Report:**\n📂 {fname}\n🆔 {doc_id}"})
                await telegram_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "✅ ሪፖርት ተልኳል!", "show_alert": True})
            
            return

        # 2. Inline Query (Search)
        if "inline_query" in data:
            iq = data["inline_query"]
            query_id = iq["id"]
            user_id = iq.get("from", {}).get("id")
            first_name = iq.get("from", {}).get("first_name", "User")
            query = iq.get("query", "").strip()

            # Track user (Sync Update)
            db.users.update_one({"_id": user_id}, {"$set": {"first_name": first_name, "last_active": datetime.now()}}, upsert=True)

            if not await check_membership(user_id):
                 await telegram_request("answerInlineQuery", {
                    "inline_query_id": query_id, "results": [], "switch_pm_text": "⚠️ Join Channel First", "switch_pm_parameter": "start", "cache_time": 5
                })
                 return

            results = []
            cursor = None

            # --- PyMongo Search (Sync & Stable) ---
            if query.startswith("#"):
                 if query.startswith("#new"):
                     cursor = db.files.find({"file_id": {"$exists": True}}).sort("_id", -1).limit(50)
                 elif query.startswith("#trending"):
                     # Aggregation to sort by views, treat null as 0
                     pipeline = [
                         {"$match": {"file_id": {"$exists": True}}},
                         {"$addFields": {"views_safe": {"$ifNull": ["$views", 0]}}},
                         {"$sort": {"views_safe": -1, "_id": -1}},
                         {"$limit": 50}
                     ]
                     cursor = db.files.aggregate(list(pipeline))
                 elif query.startswith("#random"):
                     pipeline = [{"$match": {"file_id": {"$exists": True}}}, {"$sample": {"size": 50}}]
                     cursor = db.files.aggregate(list(pipeline))
                 elif query.startswith("#favorites"):
                     user = db.users.find_one({"_id": user_id})
                     if user and user.get("favorites"):
                         cursor = db.files.find({"file_id": {"$in": user["favorites"]}}).limit(50)
            else:
                search_filter = {"file_id": {"$exists": True}}
                if query:
                    # Regex Search using Clean PyMongo
                    search_filter["display_name"] = {"$regex": re.escape(query), "$options": "i"}
                
                # If query is empty, this returns latest 50
                cursor = db.files.find(search_filter).sort("_id", -1).limit(50)

            if cursor:
                # Iterate cursor directly (It works perfectly in sync mode)
                for doc in cursor:
                    results.append({
                        "type": "audio",
                        "id": str(doc["_id"]),
                        "audio_file_id": doc["file_id"],
                        "caption": f"{doc.get('display_name')}\n\n@Almadihbot"
                    })

            await telegram_request("answerInlineQuery", {
                "inline_query_id": query_id, "results": results, "cache_time": 0, "is_personal": True
            })
            return

        # 3. Message Handling
        if "message" in data:
            msg = data["message"]
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id")
            first_name = msg.get("from", {}).get("first_name", "User")
            text = msg.get("text", "")
            
            db.users.update_one({"_id": user_id}, {"$set": {"first_name": first_name, "last_active": datetime.now()}}, upsert=True)

            # Admin Upload
            if str(user_id) == str(ADMIN_ID) and ("audio" in msg or "voice" in msg):
                 file_obj = msg.get("audio") or msg.get("voice")
                 file_id = file_obj.get("file_id")
                 caption = msg.get("caption") or ""
                 clean_name = caption.split('\n')[0].strip().replace("@Almadihbot", "") if caption else "Unknown"
                 if len(clean_name) > 2:
                     db.files.update_one({"display_name": {"$regex": re.escape(clean_name), "$options": "i"}}, {"$set": {"file_id": file_id, "display_name": clean_name}}, upsert=True)
                     await telegram_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Saved: {clean_name}"})
                 return

            if not await check_membership(user_id):
                kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}], [{"text": "✅ Verify", "callback_data": "check_subscription"}]]}
                await telegram_request("sendMessage", {"chat_id": chat_id, "text": "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ።", "reply_markup": kb})
                return

            if text == "/start":
                welcome = "*🌙 አል-ማዲህ (Al-Madih)*\n\nከ 1,200 በላይ መንዙማዎች!"
                kb = {"inline_keyboard": [[{"text": "🔥 ተወዳጅ", "switch_inline_query_current_chat": "#trending"}, {"text": "🆕 አዳዲስ", "switch_inline_query_current_chat": "#new"}], [{"text": "❤️ የእኔ ምርጫ", "switch_inline_query_current_chat": "#favorites"}, {"text": "📚 ማህደር", "callback_data": "pg_1"}], [{"text": "🔍 መንዙማ ይፈልጉ", "switch_inline_query_current_chat": ""}]]}
                await telegram_request("sendMessage", {"chat_id": chat_id, "text": welcome, "parse_mode": "Markdown", "reply_markup": kb})
            
            elif text == "/list" or text == "📂 Catalog (List)":
                 total = db.files.count_documents({"file_id": {"$exists": True}})
                 cursor = db.files.find({"file_id": {"$exists": True}}).sort("_id", -1).limit(ITEMS_PER_PAGE)
                 txt = f"📂 **መንዙማዎች (1/{(total+9)//10})**\n\n"
                 idx = 1
                 for doc in cursor:
                     clean_name = doc.get('display_name', '').replace('`','')
                     txt += f"{idx}. `{clean_name}`\n"
                     idx += 1
                 kb = {"inline_keyboard": [[{"text": "❌", "callback_data": "pg_close"}, {"text": "➡️", "callback_data": "pg_2"}]]}
                 await telegram_request("sendMessage", {"chat_id": chat_id, "text": txt, "parse_mode": "Markdown", "reply_markup": kb})
            
            elif text == "/admin" and str(user_id) == str(ADMIN_ID):
                 await telegram_request("sendMessage", {"chat_id": chat_id, "text": get_stats()})

            elif text and not text.startswith("/"):
                # Direct Search (Regex)
                doc = db.files.find_one({"display_name": {"$regex": re.escape(text.strip()), "$options": "i"}, "file_id": {"$exists": True}})
                if doc:
                    kb = {"inline_keyboard": [[{"text": "❤️ Add", "callback_data": f"fav_{doc['_id']}"}], [{"text": "↗️ Share", "switch_inline_query": ""}, {"text": "⚠️ Report", "callback_data": f"report_{doc['_id']}"}]]}
                    await telegram_request("sendAudio", {"chat_id": chat_id, "audio": doc['file_id'], "caption": f"{doc.get('display_name')}\n\n@Almadihbot", "reply_markup": kb})
                    db.files.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})
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
    return 'Bot Running (PyMongo Mode) 🚀'

if __name__ == '__main__':
    app.run(debug=True)
