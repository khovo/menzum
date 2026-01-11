from flask import Flask, request, jsonify
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
import traceback
import aiohttp 

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")

# --- Helper: Run Async Code in Sync Flask ---
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

# --- Direct API Helpers ---
async def send_message(chat_id, text, reply_markup=None):
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing!")
        return
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        try:
            async with session.post(url, json=payload) as resp:
                result = await resp.json()
                if not result.get("ok"):
                    logger.error(f"Telegram Send Error: {result}")
                else:
                    logger.info(f"Message sent to {chat_id}")
                return result
        except Exception as e:
            logger.error(f"Network Error: {e}")

async def answer_inline_query(query_id, results):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    
    async with aiohttp.ClientSession() as session:
        payload = {"inline_query_id": query_id, "results": results}
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"Inline Answer Error: {e}")

# --- Main Logic ---
async def process_telegram_update(data):
    # Database Connection
    if not MONGO_URL:
        logger.error("MONGO_URL is missing!")
        return

    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]["files"]

    try:
        # 1. Handle /start Command
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")
            
            logger.info(f"Received Message: {text}")

            if text == "/start":
                # Telegram Markdown ይጠቀማል (*bold* እንጂ **bold** አይደለም)
                welcome_text = (
                    "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ!*\n\n"
                    "መንዙማዎችን ለመስማት `@Almadihbot` ብለው ይጻፉ።"
                )
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🔍 መንዙማ ይፈልጉ", "switch_inline_query_current_chat": ""}],
                        [{"text": "Join Channel 📢", "url": "https://t.me/Al_madih"}]
                    ]
                }
                await send_message(chat_id, welcome_text, reply_markup=keyboard)

        # 2. Handle Inline Query (Search)
        elif "inline_query" in data:
            inline_query = data["inline_query"]
            query_id = inline_query["id"]
            query = inline_query.get("query", "").strip()
            
            logger.info(f"Searching for: {query}")

            # Search in DB
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

# --- FLASK ROUTE ---
@app.route('/', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            run_async(process_telegram_update(data))
            return 'ok'
        except Exception as e:
            logger.error(f"Webhook Error: {traceback.format_exc()}")
            return 'error', 500
            
    return 'Al-Madih Bot is Running! (Direct API Mode) 🚀'

# Local Run
if __name__ == '__main__':
    app.run(debug=True)
