from flask import Flask, request, jsonify
from telethon import TelegramClient, events, Button
from telethon.tl.types import InputWebDocument
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging

# Logging ማብራት
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# --- ቅንብሮች ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MONGO_URL = os.environ.get("MONGO_URL", "")

# --- Database & Client Setup ---
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

client = TelegramClient(None, API_ID, API_HASH, loop=loop)
db_client = AsyncIOMotorClient(MONGO_URL)
db = db_client["MenzumaDB"]["files"]

async def ensure_connected():
    if not client.is_connected():
        await client.start(bot_token=BOT_TOKEN)

# --- WEBHOOK ROUTE (ስሙ ተቀይሯል) ---
# እዚህ ጋር ነው ችግሩ የነበረው፣ አሁን 'telegram_webhook' አልነው
@app.route('/', methods=['GET', 'POST'])
async def telegram_webhook():
    if request.method == 'POST':
        try:
            await ensure_connected()
            data = request.get_json()
            update = await client.get_updates_as_event_loop(data)
            await client.dispatch(update)
            return 'ok'
        except Exception as e:
            logging.error(f"Error: {e}")
            return 'error', 500
    return 'Al-Madih Bot is Running on Vercel! 🚀'

# --- ቦቱ ምን ይስራ? (LOGIC) ---

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

@client.on(events.InlineQuery)
async def inline_handler(event):
    query = event.text.strip()
    search_criteria = {"display_name": {"$regex": query, "$options": "i"}} if query else {}
    
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

# Local Test
if __name__ == '__main__':
    app.run(debug=True)
