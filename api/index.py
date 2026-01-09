import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram.fsm.storage.memory import MemoryStorage

# 1. መቼቶች (Configuration) - ከ Environment Variables ይወስዳል
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")

# Logging
logging.basicConfig(level=logging.INFO)

# Setup
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
client = AsyncIOMotorClient(MONGO_URL)
db = client["MenzumaDB"]
files_collection = db["files"]

# --- Handlers (ተግባራት) ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        f"ሰላም {message.from_user.full_name}! 👋\n\n"
        "ይህ የመንዙማ ባንክ ነው (Vercel Edition)።\n"
        "🔍 የሚፈልጉትን መንዙማ ስም ይጻፉ።"
    )

@dp.message(F.audio | F.voice)
async def save_file(message: types.Message):
    # ይሄ ክፍል ለአንተ (ለ Admin) ብቻ እንዲሰራ ማድረግ ይቻላል
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
# Vercel ጥሪ ሲያደርግ የሚቀበለው ዋና function
from http.server import BaseHTTPRequestHandler
import json
import asyncio

# Vercel serverless function entry point
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            # መልዕክቱን ወደ Aiogram update መቀየር
            update_dict = json.loads(post_data.decode('utf-8'))
            
            async def feed_update():
                update = types.Update(**update_dict)
                await dp.feed_update(bot=bot, update=update)

            # Event loop ውስጥ ማስኬድ
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(feed_update())
            loop.close()
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except Exception as e:
            logging.error(f"Error: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
