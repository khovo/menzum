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

# የግዴታ የምናስገባበት ቻናል (Username without @)
FORCE_CHANNEL_USERNAME = "Al_madih" 
FORCE_CHANNEL_URL = "https://t.me/Al_madih"

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

# ሰውየው ቻናሉ ውስጥ መኖሩን ማረጋገጥ
async def check_membership(user_id):
    if not BOT_TOKEN: return True # Token ከሌለ ዝም ብሎ ይለፍ
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                result = await resp.json()
                if not result.get("ok"):
                    # ቦቱ አድሚን ካልሆነ ወይም ቻናሉ ካልተገኘ ዝም ብሎ ያለፋል (Error እንዳይሆን)
                    logger.warning(f"Membership Check Fail: {result}")
                    return True 
                
                status = result["result"]["status"]
                # አባል ከሆነ (creator, administrator, member)
                if status in ["creator", "administrator", "member"]:
                    return True
                return False
        except Exception as e:
            logger.error(f"Check Member Error: {e}")
            return True # Error ካለ እንዳይዘጋባቸው ዝም ብሎ ያስለፍ

async def answer_inline_query(query_id, results, switch_pm_text=None, switch_pm_param=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    
    payload = {"inline_query_id": query_id, "results": results, "cache_time": 10}
    if switch_pm_text and switch_pm_param:
        payload["switch_pm_text"] = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                return await resp.json()
        except Exception:
            pass

# --- Main Logic ---
async def process_telegram_update(data):
    if not MONGO_URL: return

    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]["files"]

    try:
        # 1. Handle Messages (/start)
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            text = message.get("text", "")

            # Force Subscribe Check
            is_member = await check_membership(user_id)
            
            if not is_member:
                # አባል ካልሆነ ማስጠንቀቂያ
                text = (
                    "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን መቀላቀል አለብዎት።**\n\n"
                    "Please join our channel to use this bot."
                )
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}],
                        [{"text": "Try Again 🔄", "url": f"https://t.me/Almadihbot?start=start"}]
                    ]
                }
                await send_message(chat_id, text, reply_markup=keyboard)
                return

            if text == "/start":
                welcome_text = (
                    "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*\n\n"
                    "በዚህ ቦት ከ 1,200 በላይ መንዙማዎችን እና ነሺዳዎችን ማግኘት ይችላሉ።\n\n"
                    "👇 **ከታች ያለውን ቁልፍ በመጫን ይፈልጉ:**"
                )
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🔍 መንዙማ ይፈልጉ (Search)", "switch_inline_query_current_chat": ""}],
                        [{"text": "ቻናላችን / Our Channel", "url": FORCE_CHANNEL_URL}]
                    ]
                }
                await send_message(chat_id, welcome_text, reply_markup=keyboard)

        # 2. Handle Inline Query (Search)
        elif "inline_query" in data:
            inline_query = data["inline_query"]
            query_id = inline_query["id"]
            user_id = inline_query.get("from", {}).get("id")
            query = inline_query.get("query", "").strip()

            # Inline ላይም አባል መሆኑን ማረጋገጥ (Optional - ግን ጠቃሚ ነው)
            is_member = await check_membership(user_id)
            if not is_member:
                await answer_inline_query(
                    query_id, [], 
                    switch_pm_text="⚠️ መጀመሪያ ቻናሉን ይቀላቀሉ (Join Channel)", 
                    switch_pm_param="start"
                )
                return

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
        except Exception:
            return 'error', 500
            
    return 'Al-Madih Bot is Running! (Force Sub Active) 🚀'

if __name__ == '__main__':
    app.run(debug=True)
