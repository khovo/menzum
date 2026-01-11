from flask import Flask, request, jsonify
from telethon import TelegramClient, events, Button
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
import traceback

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- 1. Environment Variables መኖራቸውን ማረጋገጥ ---
# ከሌሉ ኮዱ እንዳይበላሽ በ try/except እንይዛቸዋለን
try:
    API_ID = os.environ.get("API_ID")
    if API_ID:
        API_ID = int(API_ID)
    else:
        logger.warning("API_ID is missing!")
        
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    MONGO_URL = os.environ.get("MONGO_URL")
except Exception as e:
    logger.error(f"Env Var Error: {e}")

# --- 2. Database & Client Setup (Global) ---
# እዚህ ጋር global loop እና client መፍጠር አደገኛ ሊሆን ይችላል፣ 
# ስለዚህ ጥንቃቄ በተሞላበት መንገድ እንፈጥራለን።

client = None
db = None

try:
    if API_ID and API_HASH:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Session file እንዳይጠይቅ (None) እንጠቀማለን
        client = TelegramClient(None, API_ID, API_HASH, loop=loop)
    
    if MONGO_URL:
        db_client = AsyncIOMotorClient(MONGO_URL)
        db = db_client["MenzumaDB"]["files"]
except Exception as e:
    logger.error(f"Initialization Error: {e}")

# --- Helper to Start Client ---
async def start_bot():
    global client
    if client and not client.is_connected():
        await client.start(bot_token=BOT_TOKEN)

# --- 3. WEBHOOK ROUTE ---
@app.route('/', methods=['GET', 'POST'])
async def telegram_webhook():
    # ስህተት ካለ በቀጥታ ስክሪኑ ላይ እንዲያሳይ (Debugging)
    global client, db
    
    # መጀመሪያ Environment Variables መሞላታቸውን እንፈትሽ
    if not API_ID or not API_HASH or not BOT_TOKEN or not MONGO_URL:
        return jsonify({
            "status": "error",
            "message": "Missing Environment Variables!",
            "details": {
                "API_ID": "OK" if API_ID else "MISSING",
                "API_HASH": "OK" if API_HASH else "MISSING",
                "BOT_TOKEN": "OK" if BOT_TOKEN else "MISSING",
                "MONGO_URL": "OK" if MONGO_URL else "MISSING"
            }
        }), 500

    if request.method == 'POST':
        try:
            await start_bot()
            data = request.get_json()
            # Updateውን ወደ Telethon Event ቀይሮ መላክ
            update = await client.get_updates_as_event_loop(data)
            await client.dispatch(update)
            return 'ok'
        except Exception as e:
            logger.error(f"Webhook Error: {traceback.format_exc()}")
            return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
            
    # GET Request (Browser ላይ ሲከፈት)
    return f"Al-Madih Bot is Running! Status: {'Connected' if client else 'Client Error'}"

# --- 4. BOT LOGIC (Logic) ---

# Logic የሚሰራው client ከተፈጠረ ብቻ ነው
if client:
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
        if not db:
            return # DB ከሌለ ዝም ይበል

        query = event.text.strip()
        search_criteria = {"display_name": {"$regex": query, "$options": "i"}} if query else {}
        
        try:
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

# Local Run
if __name__ == '__main__':
    app.run(debug=True)
