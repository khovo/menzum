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
ADMIN_ID = os.environ.get("ADMIN_ID") # Add your Telegram ID in Vercel Env Vars

FORCE_CHANNEL_USERNAME = "Al_madih" 
FORCE_CHANNEL_URL = "https://t.me/Al_madih"

# Global DB Client
db_client = None

# --- Helpers ---
def get_database():
    global db_client
    if not db_client:
        db_client = AsyncIOMotorClient(MONGO_URL)
    return db_client["MenzumaDB"]

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

async def answer_inline_query(query_id, results, switch_pm_text=None, switch_pm_param=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    payload = {"inline_query_id": query_id, "results": results, "cache_time": 5}
    if switch_pm_text:
        payload["switch_pm_text"] = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except: pass

# --- DB Helpers ---
async def track_user(user_id, first_name):
    db = get_database()
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"first_name": first_name, "last_active": datetime.now()}},
        upsert=True
    )

async def increment_view(file_id):
    db = get_database()
    await db.files.update_one({"file_id": file_id}, {"$inc": {"views": 1}})

async def toggle_favorite(user_id, file_id):
    db = get_database()
    user = await db.users.find_one({"_id": user_id})
    favorites = user.get("favorites", []) if user else []
    
    if file_id in favorites:
        await db.users.update_one({"_id": user_id}, {"$pull": {"favorites": file_id}})
        return False # Removed
    else:
        await db.users.update_one({"_id": user_id}, {"$addToSet": {"favorites": file_id}})
        return True # Added

# --- 🔥 SMART SEARCH ALGORITHM 🔥 ---
def build_search_query(query_text):
    if not query_text:
        return {} 
    query_text = query_text.strip()
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
    db = get_database()

    try:
        # 1. Callback Query (Button Clicks)
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            
            if data_str.startswith("fav_"):
                file_id = data_str.split("fav_")[1]
                is_fav = await toggle_favorite(user_id, file_id)
                text = "❤️ Saved to Favorites" if is_fav else "💔 Removed from Favorites"
                
                # Update Button
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

            # Track User
            await track_user(user_id, first_name)

            # Force Subscribe Check
            if not await check_membership(user_id):
                msg = "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**"
                kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}]]}
                await send_message(chat_id, msg, reply_markup=kb)
                return

            # --- Commands ---
            if text == "/start":
                welcome = (
                    "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*\n\n"
                    "በዚህ ቦት ከ 1,200 በላይ መንዙማዎችን ማግኘት ይችላሉ።\n\n"
                    "👇 **ትዕዛዞች / Commands:**\n"
                    "🎲 /random - እጣ (Random Audio)\n"
                    "🔥 /trending - ተወዳጅ (Top 10)\n"
                    "🆕 /new - አዲስ የገቡ (New)\n"
                    "❤️ /favorites - የመረጧቸው (Saved)\n\n"
                    "🔍 **ፍለጋ:** ዝም ብለው የመንዙማ ስም ይጻፉ።"
                )
                kb = {
                    "inline_keyboard": [
                        [{"text": "🔍 ለጓደኛዎ ይላኩ", "switch_inline_query": ""}],
                        [{"text": "ቻናላችን 📢", "url": FORCE_CHANNEL_URL}]
                    ]
                }
                await send_message(chat_id, welcome, reply_markup=kb)

            elif text == "/random":
                pipeline = [{"$match": {"file_id": {"$exists": True}}}, {"$sample": {"size": 1}}]
                async for doc in db.files.aggregate(pipeline):
                    kb = {"inline_keyboard": [[{"text": "❤️ Add to Favorite", "callback_data": f"fav_{doc['file_id']}"}]]}
                    await send_audio(chat_id, doc['file_id'], f"🎲 **Random Pick:**\n{doc.get('display_name')}\n\n@Almadihbot", kb)
                    await increment_view(doc['file_id'])

            elif text == "/new":
                cursor = db.files.find({"file_id": {"$exists": True}}).sort("_id", -1).limit(10)
                msg = "**🆕 አዲስ የተጫኑ መንዙማዎች:**\n\n"
                i = 1
                async for doc in cursor:
                    clean_name = doc.get('display_name', '').split('\n')[0]
                    msg += f"{i}. {clean_name}\n"
                    i += 1
                await send_message(chat_id, msg)

            elif text == "/trending":
                cursor = db.files.find({"views": {"$exists": True}}).sort("views", -1).limit(10)
                msg = "**🔥 በብዛት የተደመጡ (Trending):**\n\n"
                i = 1
                async for doc in cursor:
                    clean_name = doc.get('display_name', '').split('\n')[0]
                    views = doc.get('views', 0)
                    msg += f"{i}. {clean_name} ({views} views)\n"
                    i += 1
                await send_message(chat_id, msg)

            elif text == "/favorites":
                user = await db.users.find_one({"_id": user_id})
                fav_ids = user.get("favorites", []) if user else []
                if not fav_ids:
                    await send_message(chat_id, "📭 እስካሁን የመረጡት መንዙማ የለም።\n\nመንዙማ ሲሰሙ '❤️ Add to Favorite' የሚለውን ይጫኑ።")
                else:
                    msg = "**❤️ የእርስዎ ምርጫዎች:**\n\n"
                    # Get details for first 20 favs
                    cursor = db.files.find({"file_id": {"$in": fav_ids}}).limit(20)
                    i = 1
                    async for doc in cursor:
                        clean_name = doc.get('display_name', '').split('\n')[0]
                        msg += f"{i}. {clean_name}\n"
                        i += 1
                    await send_message(chat_id, msg)

            # --- Admin Commands ---
            elif text == "/admin" and str(user_id) == str(ADMIN_ID):
                users_count = await db.users.count_documents({})
                files_count = await db.files.count_documents({})
                msg = (
                    "**📊 Admin Dashboard**\n\n"
                    f"👥 Total Users: `{users_count}`\n"
                    f"📂 Total Files: `{files_count}`\n\n"
                    "Commands:\n"
                    "`/broadcast [message]` - Send msg to all users"
                )
                await send_message(chat_id, msg)

            elif text.startswith("/broadcast ") and str(user_id) == str(ADMIN_ID):
                broadcast_msg = text.replace("/broadcast ", "")
                users_cursor = db.users.find({})
                count = 0
                await send_message(chat_id, "🚀 Broadcasting started...")
                async for user in users_cursor:
                    try:
                        await send_message(user["_id"], f"📢 **ማስታወቂያ:**\n\n{broadcast_msg}")
                        count += 1
                        await asyncio.sleep(0.05) # Prevent Rate limit
                    except: pass
                await send_message(chat_id, f"✅ Broadcast completed to {count} users.")

            # --- Direct Search ---
            elif text and not text.startswith("/"):
                search_query = build_search_query(text)
                doc = await db.files.find_one(search_query)
                
                if doc and 'file_id' in doc:
                    # Check if fav
                    user = await db.users.find_one({"_id": user_id})
                    favs = user.get("favorites", []) if user else []
                    btn_text = "💔 Remove" if doc['file_id'] in favs else "❤️ Add to Favorite"
                    kb = {"inline_keyboard": [[{"text": btn_text, "callback_data": f"fav_{doc['file_id']}"}]]}
                    
                    await send_audio(chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot", kb)
                    await increment_view(doc['file_id'])
                else:
                    await send_message(chat_id, "😔 ይቅርታ፣ ይህ መንዙማ አልተገኘም።")

        # 3. Inline Query (Search)
        elif "inline_query" in data:
            iq = data["inline_query"]
            query_id = iq["id"]
            user_id = iq.get("from", {}).get("id")
            first_name = iq.get("from", {}).get("first_name", "User")
            query = iq.get("query", "").strip()

            await track_user(user_id, first_name)

            if not await check_membership(user_id):
                await answer_inline_query(query_id, [], "⚠️ Join Channel First", "start")
                return

            search_criteria = build_search_query(query)
            cursor = db.files.find(search_criteria).sort("_id", -1).limit(50)
            
            results = []
            async for doc in cursor:
                if 'file_id' in doc:
                    results.append({
                        "type": "audio",
                        "id": str(doc["_id"]),
                        "audio_file_id": doc["file_id"],
                        "caption": f"{doc.get('display_name')}\n\n@Almadihbot"
                    })
            
            await answer_inline_query(query_id, results)

    except Exception as e:
        logger.error(f"Logic Error: {e}")
    finally:
        if db_client: db_client.close()

# --- WEBHOOK ROUTE ---
@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            run_async(process_telegram_update(data))
            return 'ok'
        except: return 'error', 500
    return 'Al-Madih Bot Running (v2.0) 🚀'

if __name__ == '__main__':
    app.run(debug=True)
