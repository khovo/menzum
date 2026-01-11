from flask import Flask, request, jsonify
from telethon import TelegramClient, events, Button
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
import traceback

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Environment Variables ---
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")

# --- Helper: Run Async Code in Sync Flask ---
def run_async(coro):
    """ይህ ፈንክሽን Async ኮድን በግዳጅ Sync አድርጎ ያሰራል"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

# --- Async Logic (Main Bot Function) ---
async def process_telegram_update(data):
    # 1. Client Setup
    client = TelegramClient(None, int(API_ID), API_HASH)
    
    # 2. Database Setup
    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]["files"]

    # 3. Connect & Login
    await client.start(bot_token=BOT_TOKEN)

    # --- BOT EVENTS DEFINITION ---
    
    # Event: Start Command
    @client.on(events.NewMessage(pattern='/start'))
    async def start(event):
        welcome_text = (
            "**🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ!**\n\n"
            "መንዙማዎችን ለመስማት `@Almadihbot` ብለው ይጻፉ።"
        )
        buttons = [
            [Button.switch_inline("🔍 መንዙማ ይፈልጉ", query="", same_peer=True)],
            [Button.url("Join Channel 📢", "https://t.me/Al_madih")]
        ]
        await event.reply(welcome_text, buttons=buttons)

    # Event: Inline Search
    @client.on(events.InlineQuery)
    async def inline_handler(event):
        query = event.text.strip()
        search_criteria = {"display_name": {"$regex": query, "$options": "i"}} if query else {}
        
        try:
            # 50 ውጤቶችን አምጣ
            cursor = db.find(search_criteria).sort("_id", -1).limit(50)
            results = []
            
            async for doc in cursor:
                if 'file_id' in doc:
                    results.append(
                        event.builder.document(
                            file=doc['file_id'],
                            title=doc.get("display_name", "Audio"),
                            description="@Almadihbot",
                            text=f"{doc.get('display_name')}\n\n@Almadihbot" 
                        )
                    )
            
            if results:
                await event.answer(results)
            else:
                await event.answer([], switch_pm="ምንም አልተገኘም", switch_pm_param="start")
        except Exception as e:
            logger.error(f"Inline Error: {e}")

    # 4. Process the Update
    try:
        # Convert JSON to Telethon Update
        update = await client.get_updates_as_event_loop(data)
        # Dispatch to handlers
        await client.dispatch(update)
    except Exception as e:
        logger.error(f"Dispatch Error: {e}")
    finally:
        await client.disconnect()

# --- FLASK ROUTE (SYNC) ---
@app.route('/', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            # Async ስራውን ለ run_async እንሰጠዋለን
            run_async(process_telegram_update(data))
            return 'ok'
        except Exception as e:
            logger.error(f"Webhook Error: {traceback.format_exc()}")
            return 'error', 500
            
    return 'Al-Madih Bot is Running! (Final Fix) 🚀'

# Local Run
if __name__ == '__main__':
    app.run(debug=True)
