from flask import Flask, request
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
import asyncio
import logging
import traceback
import aiohttp 
import re
import random
from datetime import datetime, timedelta

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

# --- Helpers ---
def run_async(coro):
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
            async with session.post(url, json=payload) as resp: return await resp.json()
        except: pass

async def send_audio(chat_id, audio_file_id, caption, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "audio": audio_file_id, "caption": caption, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        try:
            async with session.post(url, json=payload) as resp:
                res = await resp.json()
                if not res.get("ok"):
                    if "BUTTON_DATA_INVALID" in str(res):
                         payload.pop("reply_markup")
                         await session.post(url, json=payload)
                    else:
                        await send_message(chat_id, "⚠️ ፋይሉን መላክ አልተቻለም።")
                return res
        except: pass

async def send_document(chat_id, file_path, caption=None):
    """ጽሁፍ ፋይል (Text File) ለመላክ"""
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    data = aiohttp.FormData()
    data.add_field('chat_id', str(chat_id))
    if caption: data.add_field('caption', caption)
    data.add_field('document', open(file_path, 'rb'))
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, data=data) as resp:
                return await resp.json()
        except: pass

async def copy_message(chat_id, from_chat_id, message_id, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
        if reply_markup: payload["reply_markup"] = reply_markup
        try:
            async with session.post(url, json=payload) as resp: return await resp.json()
        except: pass

async def edit_message_reply_markup(chat_id, message_id, reply_markup):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup}
        try:
            async with session.post(url, json=payload) as resp: return await resp.json()
        except: pass

async def answer_callback_query(callback_query_id, text=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp: return await resp.json()
        except: pass

async def check_membership(user_id):
    if not BOT_TOKEN: return True
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                res = await resp.json()
                if not res.get("ok"): return True 
                return res["result"]["status"] in ["creator", "administrator", "member"]
        except: return True

async def answer_inline_query(query_id, results, switch_pm_text=None, switch_pm_param=None, cache_time=0):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    payload = {"inline_query_id": query_id, "results": results, "cache_time": cache_time, "is_personal": True}
    if switch_pm_text:
        payload["switch_pm_text"] = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp: return await resp.json()
        except: pass

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
    except: pass

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

def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    if query_text.startswith("#"): return {} 
    if len(query_text) == 1:
        return {"display_name": {"$regex": f"^{re.escape(query_text)}", "$options": "i"}}
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
        return f"📅 **Daily Statistics (24h)**\n\n🆕 New Users: `{new_users}`\n⚡ Active Users: `{active_users}`\n\n👥 Total Users: `{total_users}`\n📂 Total Files: `{total_files}`"
    except: return "Error"

# --- Main Logic ---
async def process_telegram_update(data):
    if not MONGO_URL or not BOT_TOKEN: return
    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]

    try:
        # 1. Callback Query
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            
            if data_str.startswith("fav_"):
                doc_id = data_str.split("fav_")[1]
                try:
                    file_doc = await db.files.find_one({"_id": ObjectId(doc_id)})
                    if file_doc:
                        file_id = file_doc['file_id']
                        is_fav = await toggle_favorite(db, user_id, file_id)
                        text = "❤️ Saved" if is_fav else "💔 Removed"
                        new_text = "💔 Remove" if is_fav else "❤️ Add to Favorite"
                        kb = {"inline_keyboard": [[{"text": new_text, "callback_data": f"fav_{doc_id}"}]]}
                        await answer_callback_query(cb_id, text)
                        await edit_message_reply_markup(cb["message"]["chat"]["id"], cb["message"]["message_id"], kb)
                    else:
                        await answer_callback_query(cb_id, "⚠️ File not found")
                except:
                    await answer_callback_query(cb_id, "Error")
            return

        # 2. Message Handling
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            first_name = message.get("from", {}).get("first_name", "User")
            text = message.get("text", "")
            
            await track_user(db, user_id, first_name)

            # ADMIN ONLY UPLOAD
            if "audio" in message or "voice" in message:
                if str(user_id) != str(ADMIN_ID): return 
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
                kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}]]}
                await send_message(chat_id, msg, reply_markup=kb)
                return

            # --- ADMIN DASHBOARD ---
            if str(user_id) == str(ADMIN_ID):
                if text == "/start" or text == "/admin" or text == "🔙 Back":
                    msg = "👋 **ሰላም አለቃ! (Admin Panel)**\n\nከታች ባሉት አዝራሮች ቦቱን ይቆጣጠሩ።"
                    admin_kb = {
                        "keyboard": [
                            [{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}],
                            [{"text": "📢 Broadcast"}, {"text": "👥 User Count"}],
                            [{"text": "📂 Total Files"}]
                        ],
                        "resize_keyboard": True
                    }
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
                    await send_message(chat_id, "📢 **Broadcast Mode:**\n\nለተጠቃሚዎች መልዕክት ለመላክ፣ መልዕክቱን (ጽሁፍ፣ ፎቶ፣ ወይም ኦዲዮ) **Reply** በማድረግ `/broadcast` ብለው ይላኩ።")
                    return

                elif text == "👥 User Count":
                    users = await db.users.count_documents({})
                    await send_message(chat_id, f"👥 አጠቃላይ ተጠቃሚዎች: `{users}`")
                    return
                
                elif text == "📂 Total Files":
                    files = await db.files.count_documents({})
                    await send_message(chat_id, f"📂 የተጫኑ መንዙማዎች: `{files}`")
                    return

            # --- USER COMMANDS ---
            if text == "/start":
                welcome = (
                    "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*\n\n"
                    "ከ 1,200 በላይ መንዙማዎችን እዚህ ያገኛሉ።\n\n"
                    "👇 **አጠቃቀም:**\n"
                    "• ዝም ብለው ስም ይጻፉ (Direct).\n"
                    "• `/list` ብለው ሙሉ ዝርዝር ማግኘት ይችላሉ።"
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

            # 🔥 NEW: /list command (Sends a text file with all titles)
            elif text == "/list":
                cursor = db.files.find({}, {"display_name": 1}).sort("_id", -1)
                lines = []
                async for doc in cursor:
                    lines.append(doc.get("display_name", "Unknown"))
                
                if lines:
                    content = "\n".join(lines)
                    file_path = "/tmp/menzuma_list.txt"
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    
                    await send_document(chat_id, file_path, "📂 **የሁሉም መንዙማዎች ዝርዝር (Catalog)**\n\nየሚፈልጉትን ስም ኮፒ አድርገው ለቦቱ ይላኩ።")
                    os.remove(file_path)
                else:
                    await send_message(chat_id, "📭 እስካሁን የተመዘገበ መንዙማ የለም።")

            # Broadcast Handler (Reply based)
            elif text and text.startswith("/broadcast") and str(user_id) == str(ADMIN_ID):
                if "reply_to_message" in message:
                    reply_msg_id = message["reply_to_message"]["message_id"]
                    users_cursor = db.users.find({})
                    count = 0
                    await send_message(chat_id, "🚀 Broadcasting started...")
                    async for user in users_cursor:
                        try:
                            await copy_message(user["_id"], chat_id, reply_msg_id)
                            count += 1
                            await asyncio.sleep(0.05) 
                        except: pass
                    await send_message(chat_id, f"✅ Broadcast sent to {count} users.")
                else:
                    await send_message(chat_id, "⚠️ ለማስታወቂያ፣ መላክ ለሚፈልጉት መልዕክት Reply በማድረግ `/broadcast` ይበሉ።")

            # Search Logic (Mono Text for easy copy)
            elif text and not text.startswith("/"):
                search_query = build_search_query(text)
                doc = await db.files.find_one(search_query)
                if doc:
                    if 'file_id' in doc:
                        short_id = str(doc['_id'])
                        kb = {"inline_keyboard": [[{"text": "❤️ Add to Favorite", "callback_data": f"fav_{short_id}"}]]}
                        await send_audio(chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot", kb)
                        await increment_view(db, doc['file_id'])
                    else:
                        await send_message(chat_id, "⚠️ ፋይሉ ተገኝቷል ግን ኦዲዮው ጠፍቷል።")
                else:
                    await send_message(chat_id, "😔 ይቅርታ፣ አልተገኘም።")

        # 3. Inline Query
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
            
            if query.startswith("#random"):
                pipeline = [{"$match": {"file_id": {"$exists": True}}}, {"$sample": {"size": 50}}]
                cursor = db.files.aggregate(pipeline)
            elif query.startswith("#trending"):
                filter_text = query.replace("#trending", "").strip()
                match_stage = {"file_id": {"$exists": True}}
                if filter_text:
                    match_stage["display_name"] = {"$regex": re.escape(filter_text), "$options": "i"}
                pipeline = [
                    {"$match": match_stage},
                    {"$addFields": {"views_safe": {"$ifNull": ["$views", 0]}}}, 
                    {"$sort": {"views_safe": -1, "_id": -1}}, 
                    {"$limit": 50}
                ]
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
                search_criteria = build_search_query(query) if query else {}
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

            await answer_inline_query(query_id, results, cache_time=0)

    except Exception as e:
        logger.error(f"Logic Error: {e}")
    finally:
        db_client.close()

@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            run_async(process_telegram_update(data))
            return 'ok'
        except: return 'error', 500
    return 'Al-Madih Bot Running (Catalog Feature) 🚀'

if __name__ == '__main__':
    app.run(debug=True)
