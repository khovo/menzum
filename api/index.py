from flask import Flask, request
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
import asyncio
import logging
import aiohttp 
import re
import time
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

# ==========================================
# 🔥 HARDCODED BEST 50 MENZUMAS (በጣም ፈጣን)
# ==========================================
# እዚህ ጋር የምትፈልጋቸውን መንዙማዎች file_id እና ስም አስገባ።
# ቦቱ ዝም ብሎ ሲጠራ እነዚህን ነው የሚያመጣው።

BEST_MENZUMAS = [
    {
        "file_id": "CQACAgQAAxkBAAJ4G2mLk56zMK_nt6lPzuPY6xglNPm5AAIdGwACDYywU7f-6zo6HrwYOgQ",  # <-- የፋይሉን ID እዚህ ጋር (Example)
        "name": " (ትልቁ ሰው)አዲስ የህብረት ነሺዳ NEW NESHID TILKU SEW/ MUAZ HABIB MUHAMMED… (Example 1)" # <-- የሚታየው ስም
    },
    {
        "file_id": "CQACAgQAAxkBAAJ4GGmLkyK4wtGWeeiSHf_OQ5tYORzsAAKuIQACIi-RU07ORdJOMuerOgQ", 
        "name": "ሸይኽ አማን ኬራጎ ሙሃመድ ሰላም ዐለይኩም"
    },
    # ... ሌሎችንም እዚህ ጋር ቀጥል (እስከ 50 መሙላት ትችላለህ)
]

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
                return await resp.json()
        except: pass

async def edit_message_text(chat_id, message_id, text, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
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

async def answer_callback_query(callback_query_id, text=None, show_alert=False):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    if show_alert: payload["show_alert"] = True
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

async def answer_inline_query(query_id, results, switch_pm_text=None, switch_pm_param=None, cache_time=300):
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

async def copy_message(chat_id, from_chat_id, message_id, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
        if reply_markup: payload["reply_markup"] = reply_markup
        try:
            async with session.post(url, json=payload) as resp: return await resp.json()
        except: pass

# --- DB Helpers ---
async def track_user(db, user_id, first_name):
    try:
        now = datetime.now()
        # Ensure consistent Integer ID storage
        await db.users.update_one(
            {"_id": int(user_id)},
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
        # Try finding user by Int first, then String (Safety Net)
        user = await db.users.find_one({"_id": user_id})
        if not user:
            user = await db.users.find_one({"_id": str(user_id)})
            
        target_id = user["_id"] if user else user_id
        
        favorites = user.get("favorites", []) if user else []
        if file_id in favorites:
            await db.users.update_one({"_id": target_id}, {"$pull": {"favorites": file_id}})
            return False
        else:
            await db.users.update_one({"_id": target_id}, {"$addToSet": {"favorites": file_id}})
            return True
    except: return False

async def get_user_data(db, user_id):
    return await db.users.find_one({"_id": user_id})

def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    words = query_text.split()
    regex_pattern = ""
    for word in words:
        regex_pattern += f"(?=.*{re.escape(word)})"
    return {"display_name": {"$regex": f"^{regex_pattern}", "$options": "i"}}

async def get_catalog_page(db, page):
    limit = ITEMS_PER_PAGE
    skip = (page - 1) * limit
    total_docs = await db.files.count_documents({"file_id": {"$exists": True}})
    total_pages = (total_docs + limit - 1) // limit
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

# --- Main Logic ---
async def process_telegram_update(data):
    if not MONGO_URL or not BOT_TOKEN: return
    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]

    try:
        # 1. Callback Query (Buttons)
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            message_id = cb["message"]["message_id"]
            
            if data_str == "check_subscription":
                if await check_membership(user_id):
                    await answer_callback_query(cb_id, "✅ ተቀላቅለዋል! እንኳን ደህና መጡ።")
                    welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
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

            if data_str.startswith("fav_"):
                doc_id = data_str.split("fav_")[1]
                # Try simple update first
                try:
                    # If it's an object ID from DB search
                    if len(doc_id) == 24:
                        file_doc = await db.files.find_one({"_id": ObjectId(doc_id)})
                        if file_doc:
                            file_id = file_doc['file_id']
                            is_fav = await toggle_favorite(db, user_id, file_id)
                            text = "❤️ Saved" if is_fav else "💔 Removed"
                            await answer_callback_query(cb_id, text)
                        else:
                            await answer_callback_query(cb_id, "⚠️ File not found")
                    else:
                        # If it's a direct file_id from Hardcoded list
                        is_fav = await toggle_favorite(db, user_id, doc_id)
                        text = "❤️ Saved" if is_fav else "💔 Removed"
                        await answer_callback_query(cb_id, text)
                except:
                    await answer_callback_query(cb_id, "Error")
            
            # Handle Pagination & Other callbacks (Same as before)
            if data_str.startswith("pg_"):
                 if data_str == "pg_close":
                    await edit_message_text(chat_id, message_id, "❌ ዝርዝሩ ተዘግቷል። /list በማለት እንደገና መክፈት ይችላሉ።")
                 else:
                    new_page = int(data_str.split("_")[1])
                    text, kb = await get_catalog_page(db, new_page)
                    await edit_message_text(chat_id, message_id, text, reply_markup=kb)
                 await answer_callback_query(cb_id)

            return

        # 2. Message Handling (Same as before - Simplified for brevity)
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            first_name = message.get("from", {}).get("first_name", "User")
            text = message.get("text", "")
            
            await track_user(db, user_id, first_name)

            # ... (Existing Admin & User commands logic remains here) ...
            if text == "/start":
                welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                kb = {
                    "inline_keyboard": [
                        [{"text": "🔥 Trending", "switch_inline_query_current_chat": ""}], # Empty query = Hardcoded List
                        [{"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"}]
                    ]
                }
                await send_message(chat_id, welcome, reply_markup=kb)

        # 3. Inline Query (THE MAIN FIX)
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

            results = []

            # ==========================================
            # 🚀 MODE 1: HARDCODED LIST (Ultra Fast)
            # ==========================================
            # ባዶ ሲሆን ወይም #trending ወይም #new ሲባል - ኮዱ ላይ ያለውን ዝርዝር አምጣ
            if not query or query == "#trending" or query == "#new":
                for index, item in enumerate(BEST_MENZUMAS):
                    results.append({
                        "type": "audio",
                        "id": f"static_{index}", # Unique ID for static items
                        "audio_file_id": item["file_id"],
                        "caption": f"{item['name']}\n\n@Almadihbot",
                        "reply_markup": {
                            "inline_keyboard": [[
                                {"text": "❤️ Fav", "callback_data": f"fav_{item['file_id']}"}
                            ]]
                        }
                    })
                
                # Cache this result on Telegram side for 10 minutes (600s)
                await answer_inline_query(query_id, results, cache_time=600)
                return

            # ==========================================
            # 🔍 MODE 2: FAVORITES (Database Search)
            # ==========================================
            elif query.startswith("#favorites"):
                user = await db.users.find_one({"_id": user_id})
                if not user: user = await db.users.find_one({"_id": str(user_id)})
                
                fav_ids = user.get("favorites", []) if user else []
                
                if fav_ids:
                    # Search DB for file details if we stored ID, OR just construct if we have info
                    # Assuming we need to fetch details from DB based on File ID
                    cursor = db.files.find({"file_id": {"$in": fav_ids}}).limit(50)
                    docs = await cursor.to_list(length=50)
                    
                    for doc in docs:
                        results.append({
                            "type": "audio",
                            "id": str(doc["_id"]),
                            "audio_file_id": doc["file_id"],
                            "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                            "reply_markup": {
                                "inline_keyboard": [[{"text": "💔 Remove", "callback_data": f"fav_{str(doc['_id'])}" }]]
                            }
                        })
                else:
                     results.append({
                        "type": "article",
                        "id": "empty_favs",
                        "title": "No Favorites Yet",
                        "description": "የመረጡት መንዙማ የለም።",
                        "input_message_content": {"message_text": "የመረጡት መንዙማ የለም።"}
                    })

            # ==========================================
            # 🔎 MODE 3: SPECIFIC SEARCH (Database Search)
            # ==========================================
            else:
                search_criteria = build_search_query(query)
                search_criteria["file_id"] = {"$exists": True}
                
                cursor = db.files.find(
                    search_criteria, 
                    {"file_id": 1, "display_name": 1, "_id": 1}
                ).limit(20) 

                docs = await cursor.to_list(length=20)
                for doc in docs:
                     results.append({
                        "type": "audio",
                        "id": str(doc["_id"]),
                        "audio_file_id": doc["file_id"],
                        "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                         "reply_markup": {
                            "inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }]]
                        }
                    })

            await answer_inline_query(query_id, results, cache_time=300)

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
    return 'Al-Madih Bot Running (Hardcoded Mode) 🚀'

if __name__ == '__main__':
    app.run(debug=True)
