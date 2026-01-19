from flask import Flask, request
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
import traceback
import aiohttp 
import re
import random
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

# Global DB Client
db_client = None

# --- Helpers ---
def run_async(coro):
    """Run async code in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def send_message(chat_id, text, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except: pass

async def send_audio(chat_id, audio_file_id, caption, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "audio": audio_file_id, "caption": caption, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except: pass

async def copy_message(chat_id, from_chat_id, message_id, reply_markup=None):
    """ማንኛውንም አይነት መልዕክት (Media/Text) ኮፒ አድርጎ መላክ"""
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    async with aiohttp.ClientSession() as session:
        payload = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id
        }
        if reply_markup: payload["reply_markup"] = reply_markup
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Copy Error: {e}")

async def edit_message_reply_markup(chat_id, message_id, reply_markup):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup}
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except: pass

async def answer_callback_query(callback_query_id, text=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except: pass

async def check_membership(user_id):
    if not BOT_TOKEN: return True
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                result = await resp.json()
                if not result.get("ok"): return True 
                return result["result"]["status"] in ["creator", "administrator", "member"]
        except: return True

async def answer_inline_query(query_id, results, switch_pm_text=None, switch_pm_param=None, cache_time=1):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    # 🔥 Cache Time 1 ሰከንድ አድርጌዋለሁ (ለውጡ ወዲያው እንዲታይ)
    payload = {"inline_query_id": query_id, "results": results, "cache_time": cache_time}
    if switch_pm_text:
        payload["switch_pm_text"] = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except: pass

# --- DB Helpers ---
async def track_user(db, user_id, first_name):
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"first_name": first_name, "last_active": datetime.now()}},
        upsert=True
    )

async def increment_view(db, file_id):
    await db.files.update_one({"file_id": file_id}, {"$inc": {"views": 1}})

async def toggle_favorite(db, user_id, file_id):
    user = await db.users.find_one({"_id": user_id})
    favorites = user.get("favorites", []) if user else []
    
    if file_id in favorites:
        await db.users.update_one({"_id": user_id}, {"$pull": {"favorites": file_id}})
        return False # Removed
    else:
        await db.users.update_one({"_id": user_id}, {"$addToSet": {"favorites": file_id}})
        return True # Added

# --- 🔥 SMART SEARCH BUILDER 🔥 ---
def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    
    if query_text.startswith("#"):
        return {} 

    if len(query_text) == 1:
        return {"display_name": {"$regex": f"^{re.escape(query_text)}", "$options": "i"}}
    
    words = query_text.split()
    regex_pattern = ""
    for word in words:
        regex_pattern += f"(?=.*{re.escape(word)})"
    return {"display_name": {"$regex": f"^{regex_pattern}", "$options": "i"}}

# --- Main Logic ---
async def process_telegram_update(data):
    if not MONGO_URL or not BOT_TOKEN: return
    
    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]

    try:
        # 1. Callback Query (Button Clicks)
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            
            if data_str.startswith("fav_"):
                file_id = data_str.split("fav_")[1]
                is_fav = await toggle_favorite(db, user_id, file_id)
                text = "❤️ Saved" if is_fav else "💔 Removed"
                new_text = "💔 Remove" if is_fav else "❤️ Add to Favorite"
                kb = {"inline_keyboard": [[{"text": new_text, "callback_data": f"fav_{file_id}"}]]}
                await answer_callback_query(cb_id, text)
                await edit_message_reply_markup(cb["message"]["chat"]["id"], cb["message"]["message_id"], kb)
            return

        # 2. Message Handling
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            first_name = message.get("from", {}).get("first_name", "User")
            text = message.get("text", "")
            
            await track_user(db, user_id, first_name)

            if not await check_membership(user_id):
                msg = "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**"
                kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}]]}
                await send_message(chat_id, msg, reply_markup=kb)
                return

            # Commands
            if text == "/start":
                welcome = (
                    "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*\n\n"
                    "በዚህ ቦት ከ 1,200 በላይ መንዙማዎችን ማግኘት ይችላሉ።\n\n"
                    "👇 **ይሞክሩ (Try Inline Search):**\n"
                    "ማንኛውም ቻት ላይ `@Almadihbot` ብለው ስፔስ ሲሰጡ ምርጫ ይመጣልዎታል።\n\n"
                    "🆕 `#new` - አዳዲስ የገቡ\n"
                    "🔥 `#trending` - ተወዳጅ\n"
                    "🎲 `#random` - እጣ\n"
                    "❤️ `#favorites` - የመረጧቸው"
                )
                kb = {
                    "inline_keyboard": [
                        [
                            {"text": "🔥 Trending", "switch_inline_query_current_chat": "#trending"},
                            {"text": "🆕 New", "switch_inline_query_current_chat": "#new"}
                        ],
                        [
                            {"text": "🎲 Random", "switch_inline_query_current_chat": "#random"},
                            {"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"}
                        ],
                        [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}]
                    ]
                }
                await send_message(chat_id, welcome, reply_markup=kb)

            # --- Admin Broadcast (Reply Mode) ---
            elif text and text.startswith("/broadcast") and str(user_id) == str(ADMIN_ID):
                # 1. Media Broadcast (Reply)
                if "reply_to_message" in message:
                    reply_msg_id = message["reply_to_message"]["message_id"]
                    users_cursor = db.users.find({})
                    count = 0
                    await send_message(chat_id, "🚀 Media Broadcasting started...")
                    async for user in users_cursor:
                        try:
                            # copyMessage ይጠቀማል (ሁሉንም አይነት ሚዲያ ይልካል)
                            await copy_message(user["_id"], chat_id, reply_msg_id)
                            count += 1
                            await asyncio.sleep(0.05) 
                        except: pass
                    await send_message(chat_id, f"✅ Broadcast sent to {count} users.")
                # 2. Text Broadcast (Direct)
                else:
                    msg_content = text.replace("/broadcast ", "")
                    if len(msg_content) < 2:
                        await send_message(chat_id, "⚠️ Usage: Reply to media OR type `/broadcast message`")
                        return
                    users_cursor = db.users.find({})
                    count = 0
                    await send_message(chat_id, "🚀 Text Broadcasting...")
                    async for user in users_cursor:
                        try:
                            await send_message(user["_id"], f"📢 **ማስታወቂያ:**\n\n{msg_content}")
                            count += 1
                            await asyncio.sleep(0.05)
                        except: pass
                    await send_message(chat_id, f"✅ Text Broadcast sent to {count} users.")

            elif text == "/admin" and str(user_id) == str(ADMIN_ID):
                users_count = await db.users.count_documents({})
                files_count = await db.files.count_documents({})
                msg = f"📊 **Stats:**\n👥 Users: {users_count}\n📂 Files: {files_count}"
                await send_message(chat_id, msg)

            # Direct Search Fallback (Text sent to bot)
            elif text and not text.startswith("/"):
                search_query = build_search_query(text)
                doc = await db.files.find_one(search_query)
                if doc:
                    if 'file_id' in doc:
                        kb = {"inline_keyboard": [[{"text": "❤️ Add to Favorite", "callback_data": f"fav_{doc['file_id']}"}]]}
                        await send_audio(chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot", kb)
                        await increment_view(db, doc['file_id'])
                    else:
                        await send_message(chat_id, "⚠️ ፋይሉ በዳታቤዝ አለ ነገር ግን ኦዲዮው ጠፍቷል።")
                else:
                    await send_message(chat_id, "😔 ይቅርታ፣ አልተገኘም።")

        # 3. Inline Query (The Main Feature!)
        elif "inline_query" in data:
            iq = data["inline_query"]
            query_id = iq["id"]
            user_id = iq.get("from", {}).get("id")
            query = iq.get("query", "").strip()

            if not await check_membership(user_id):
                await answer_inline_query(query_id, [], "⚠️ Join Channel First", "start")
                return

            cursor = None
            results = []
            
            # --- HASHTAG LOGIC (Limit = 50) ---
            if query.startswith("#random"):
                pipeline = [{"$match": {"file_id": {"$exists": True}}}, {"$sample": {"size": 50}}]
                cursor = db.files.aggregate(pipeline)
                
            elif query.startswith("#trending"):
                filter_text = query.replace("#trending", "").strip()
                search_filter = {} 
                if filter_text:
                    search_filter["display_name"] = {"$regex": filter_text, "$options": "i"}
                # እዚህ ጋር Limit 50 ነው
                cursor = db.files.find(search_filter).sort("views", -1).limit(50)
                
            elif query.startswith("#new"):
                filter_text = query.replace("#new", "").strip()
                search_filter = {"file_id": {"$exists": True}}
                if filter_text:
                    search_filter["display_name"] = {"$regex": filter_text, "$options": "i"}
                # እዚህ ጋር Limit 50 ነው
                cursor = db.files.find(search_filter).sort("_id", -1).limit(50)
                
            elif query.startswith("#favorites"):
                user = await db.users.find_one({"_id": user_id})
                fav_ids = user.get("favorites", []) if user else []
                if fav_ids:
                    filter_text = query.replace("#favorites", "").strip()
                    search_filter = {"file_id": {"$in": fav_ids}}
                    if filter_text:
                        search_filter["display_name"] = {"$regex": filter_text, "$options": "i"}
                    cursor = db.files.find(search_filter).limit(50)
            
            else:
                # Normal Search (Limit 50)
                search_criteria = build_search_query(query) if query else {}
                cursor = db.files.find(search_criteria).sort("_id", -1).limit(50)

            # Process Results
            if cursor:
                async for doc in cursor:
                    if 'file_id' in doc:
                        desc = "@Almadihbot"
                        if query.startswith("#trending"):
                            desc = f"🔥 {doc.get('views', 0)} Views"
                        
                        results.append({
                            "type": "audio",
                            "id": str(doc["_id"]),
                            "audio_file_id": doc["file_id"],
                            "caption": f"{doc.get('display_name')}\n\n@Almadihbot"
                        })

            # 🔥 Cache Time 0 (ወይም 1) አድርጌዋለሁ ለውጡ ወዲያው እንዲታይ
            cache_time = 0 if query.startswith("#random") else 1
            await answer_inline_query(query_id, results, cache_time=cache_time)

    except Exception as e:
        logger.error(f"Logic Error: {e}")
    finally:
        db_client.close()

# --- WEBHOOK ---
@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            run_async(process_telegram_update(data))
            return 'ok'
        except: return 'error', 500
    return 'Al-Madih Bot Running (v3.0 Final) 🚀'

if __name__ == '__main__':
    app.run(debug=True)
