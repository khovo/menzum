import os
import logging
import json
import asyncio
from http.server import BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient

# Logging Setup
logging.basicConfig(level=logging.INFO)

# 1. Dispatcher ብቻ እዚህ እንፈጥራለን (መዝገብ ስለሆነ)
dp = Dispatcher(storage=MemoryStorage())

# Global Variables (ለጊዜው ባዶ እናደርጋቸዋለን)
mongo_client = None
files_collection = None

# --- Handlers (ተግባራት) ---
# ማሳሰቢያ: Handlers አሁን 'files_collection'ን ከ Global ያነባሉ

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        f"ሰላም {message.from_user.full_name}! 👋\n\n"
        "ይህ የመንዙማ ባንክ ነው (Vercel Edition)።\n"
        "🔍 የሚፈልጉትን መንዙማ ስም ይጻፉ።"
    )

@dp.message(F.audio | F.voice)
async def save_file(message: types.Message):
    # files_collection መኖሩን ማረጋገጥ
    if files_collection is None:
        await message.reply("System Error: Database not connected.")
        return

    file_id = message.audio.file_id if message.audio else message.voice.file_id
    file_name = message.caption if message.caption else (message.audio.file_name if message.audio else "Unknown")
    
    data = {
        "file_id": file_id,
        "file_name": file_name.lower(),
        "display_name": file_name
    }
    
    await files_collection.update_one(
        {"file_name": file_name.lower()}, 
        {"$set": data}, 
        upsert=True
    )
    await message.reply(f"✅ ተቀብያለሁ! '{file_name}' ተመዝግቧል።")

@dp.message(F.text)
async def search_handler(message: types.Message):
    if files_collection is None:
        await message.reply("System Error: Database not connected.")
        return

    search_text = message.text.lower()
    found_file = await files_collection.find_one({"file_name": {"$regex": search_text}})
    
    if found_file:
        await message.answer_audio(
            found_file["file_id"], 
            caption=f"🎧 **{found_file['display_name']}**\n\nከ @MenzumaBoxBot የተላከ"
        )
    else:
        await message.reply("😔 ይቅርታ፣ አልተገኘም።")

# --- Vercel Webhook Handler ---
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 2. Vercel ጥሪ ሲያደርግ ብቻ እነዚህን ነገሮች እንፈጥራለን (Inside Request Loop)
        BOT_TOKEN = os.environ.get("BOT_TOKEN")
        MONGO_URL = os.environ.get("MONGO_URL")

        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        async def feed_update():
            # Global variableችን መጠቀም
            global mongo_client, files_collection
            
            # Bot እና Database አሁን ባለው Loop ውስጥ እንፈጥራለን
            bot = Bot(token=BOT_TOKEN)
            
            # Database Connection (ከሌለ ወይም ከተዘጋ ብቻ እንፈጥራለን)
            if mongo_client is None:
                mongo_client = AsyncIOMotorClient(MONGO_URL)
                db = mongo_client["MenzumaDB"]
                files_collection = db["files"]

            try:
                update_dict = json.loads(post_data.decode('utf-8'))
                update = types.Update(**update_dict)
                
                # መልዕክቱን ወደ Dispatcher መመገብ
                await dp.feed_update(bot=bot, update=update)
            except Exception as e:
                logging.error(f"Process Error: {e}")
            finally:
                # Bot session መዝጋት (Memory leak እንዳይኖር)
                await bot.session.close()

        try:
            # አዲስ Loop ከመፍጠር ይልቅ asyncio.run መጠቀም ይሻላል (Clean start)
            asyncio.run(feed_update())
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except Exception as e:
            logging.error(f"Server Error: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running! (V2)")
