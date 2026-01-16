from flask import Flask, request
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
import traceback
import aiohttp 

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")

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
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Send Error: {e}")

# አዲስ: ኦዲዮ መላኪያ Function
async def send_audio(chat_id, audio_file_id, caption):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "audio": audio_file_id, "caption": caption, "parse_mode": "Markdown"}
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Send Audio Error: {e}")

async def check_membership(user_id):
    if not BOT_TOKEN: return True
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                result = await resp.json()
                if not result.get("ok"): return True 
                status = result["result"]["status"]
                return status in ["creator", "administrator", "member"]
        except:
            return True

async def answer_inline_query(query_id, results, switch_pm_text=None, switch_pm_param=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    payload = {"inline_query_id": query_id, "results": results, "cache_time": 5} # Cache time reduced
    if switch_pm_text:
        payload["switch_pm_text"] = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Inline Answer Error: {e}")

# --- Main Logic ---
async def process_telegram_update(data):
    if not MONGO_URL or not BOT_TOKEN:
        logger.error("Missing ENV Variables")
        return

    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]["files"]

    try:
        # 1. Message Handling (/start OR Text Search)
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            text = message.get("text", "")

            # Force Subscribe Check
            is_member = await check_membership(user_id)
            if not is_member:
                msg = "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**"
                kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}]]}
                await send_message(chat_id, msg, reply_markup=kb)
                return

            # Command: /start
            if text.startswith("/start"):
                welcome = (
                    "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*\n\n"
                    "በዚህ ቦት ከ 1,200 በላይ መንዙማዎችን ማግኘት ይችላሉ።\n\n"
                    "👇 **አጠቃቀም:**\n"
                    "1. ዝም ብለው የመንዙማውን ስም ይጻፉልን።\n"
                    "2. ወይም `Search` የሚለውን ቁልፍ ይጫኑ።"
                )
                kb = {
                    "inline_keyboard": [
                        [{"text": "🔍 መንዙማ ይፈልጉ (Search)", "switch_inline_query_current_chat": ""}],
                        [{"text": "ቻናላችን / Our Channel", "url": FORCE_CHANNEL_URL}]
                    ]
                }
                await send_message(chat_id, welcome, reply_markup=kb)
            
            # Direct Text Search (ዝም ብሎ ጽሁፍ ሲላክ)
            elif text:
                logger.info(f"Direct Search: {text}")
                query = text.strip()
                # 1. በትክክለኛ ስም (Exact/Regex) መፈለግ
                doc = await db.find_one({"display_name": {"$regex": query, "$options": "i"}})
                
                if doc and 'file_id' in doc:
                    await send_audio(chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot")
                else:
                    await send_message(chat_id, "😔 ይቅርታ፣ ይህ መንዙማ አልተገኘም። እባክዎ ስሙን አስተካክለው ይሞክሩ።")

        # 2. Inline Query (Search)
        elif "inline_query" in data:
            iq = data["inline_query"]
            query_id = iq["id"]
            user_id = iq.get("from", {}).get("id")
            query = iq.get("query", "").strip()

            is_member = await check_membership(user_id)
            if not is_member:
                await answer_inline_query(query_id, [], "⚠️ Join Channel First", "start")
                return

            # Search Query
            search_criteria = {"display_name": {"$regex": query, "$options": "i"}} if query else {}
            cursor = db.find(search_criteria).sort("_id", -1).limit(50)
            
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

# --- WEBHOOK ROUTE FIX ---
@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            run_async(process_telegram_update(data))
            return 'ok'
        except Exception as e:
            logger.error(f"Webhook Error: {traceback.format_exc()}")
            return 'error', 500
    return 'Al-Madih Bot is Running! 🚀'

if __name__ == '__main__':
    app.run(debug=True)
