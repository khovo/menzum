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

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def send_message(chat_id, text, reply_markup=None):
    if not BOT_TOKEN: 
        logger.error("BOT_TOKEN is missing")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        try:
            async with session.post(url, json=payload) as resp:
                logger.info(f"Sent message to {chat_id}: {resp.status}")
                return await resp.json()
        except Exception as e:
            logger.error(f"Send Error: {e}")

async def process_telegram_update(data):
    # 1. ቼክ ማድረግ (Debug)
    if not BOT_TOKEN:
        logger.critical("CRITICAL: BOT_TOKEN is missing in Vercel!")
        return
    if not MONGO_URL:
        logger.critical("CRITICAL: MONGO_URL is missing in Vercel!")
        return

    try:
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")

            if text == "/start":
                # መጀመሪያ ዳታቤዝ ሳይነካ ሰላም ይበል (ግንኙነት ለመሞከር)
                logger.info("Processing /start command...")
                
                # DB Connection ሙከራ
                try:
                    db_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
                    db = db_client["MenzumaDB"]["files"]
                    # ቀላል ጥያቄ (Ping)
                    await db.find_one({})
                    logger.info("Database Connected Successfully")
                except Exception as e:
                    error_msg = f"⚠️ **System Error:** Database Connection Failed!\nReason: {str(e)}"
                    await send_message(chat_id, error_msg)
                    return

                # ሁሉም ሰላም ከሆነ መልዕክቱን ይላክ
                welcome_text = (
                    "*🌙 አል-ማዲህ (Al-Madih) ቦት ይሰራል! ✅*\n\n"
                    "Database: Connected 🟢\n"
                    "Webhook: Active 🟢\n\n"
                    "መንዙማ ለመስማት `@Almadihbot` ብለው ይጻፉ።"
                )
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🔍 መንዙማ ይፈልጉ", "switch_inline_query_current_chat": ""}],
                        [{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}]
                    ]
                }
                await send_message(chat_id, welcome_text, reply_markup=keyboard)

        elif "inline_query" in data:
            # Inline Logic (Simplified for Debug)
            pass

    except Exception as e:
        logger.error(f"Logic Error: {e}")

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
            
    return 'Al-Madih Bot Debug Mode 🚧'

if __name__ == '__main__':
    app.run(debug=True)
