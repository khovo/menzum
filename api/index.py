import os
import logging
import json
import asyncio
from http.server import BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from motor.motor_asyncio import AsyncIOMotorClient

# Logging
logging.basicConfig(level=logging.INFO)

# Dispatcher እዚህ ይፈጠራል
dp = Dispatcher(storage=MemoryStorage())

# --- Helper Function: Database Connection ---
def get_db_collection():
    """እያንዳንዱ function የራሱን connection እንዲፈጥር እናደርጋለን"""
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        return None, None
    client = AsyncIOMotorClient(mongo_url)
    db = client["MenzumaDB"]
    return client, db["files"]

# --- Handlers (ተግባራት) ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        f"ሰላም {message.from_user.full_name}! 👋\n\n"
        "ይህ የመንዙማ ባንክ (Al-Madih) ነው።\n"
        "🔍 የሚፈልጉትን መንዙማ ስም ይጻፉ።"
    )

@dp.message(F.audio | F.voice)
async def save_file(message: types.Message):
    # 1. ለእዚህ ጥሪ ብቻ የሚሆን Database connection መክፈት
    client, files_collection = get_db_collection()
    if not client:
        return

    try:
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        file_name = message.caption if message.caption else (message.audio.file_name if message.audio else "Unknown")
        
        # ስም ማጣራት (Cleaning)
        clean_name = file_name.strip()
        
        data = {
            "file_id": file_id,
            "file_name": clean_name.lower(),
            "display_name": clean_name
        }
        
        # Database ላይ መጫን
        await files_collection.update_one(
            {"file_name": clean_name.lower()}, 
            {"$set": data}, 
            upsert=True
        )
        
        await message.reply(f"✅ ተቀብያለሁ! **{clean_name}** ተመዝግቧል።")
        
    except Exception as e:
        logging.error(f"DB Error: {e}")
    finally:
        # በጣም ወሳኙ ፓርት: ስራውን ሲጨርስ Connection መዝጋት
        client.close()

@dp.message(F.text)
async def search_handler(message: types.Message):
    # 1. ለእዚህ ጥሪ ብቻ የሚሆን Database connection መክፈት
    client, files_collection = get_db_collection()
    if not client:
        return

    try:
        search_text = message.text.lower().strip()
        # Regex search
        found_file = await files_collection.find_one({"file_name": {"$regex": search_text, "$options": "i"}})
        
        if found_file:
            await message.answer_audio(
                found_file["file_id"], 
                caption=f"🎧 **{found_file['display_name']}**\n\n@Almadihbot"
            )
        else:
            await message.reply("😔 ይቅርታ፣ አልተገኘም።")
    except Exception as e:
        logging.error(f"Search Error: {e}")
    finally:
        # Connection መዝጋት
        if client:
            client.close()

# --- Vercel Webhook Handler ---
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        BOT_TOKEN = os.environ.get("BOT_TOKEN")
        
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        async def feed_update():
            bot = Bot(token=BOT_TOKEN)
            try:
                update_dict = json.loads(post_data.decode('utf-8'))
                update = types.Update(**update_dict)
                await dp.feed_update(bot=bot, update=update)
            except Exception as e:
                logging.error(f"Process Error: {e}")
            finally:
                await bot.session.close()

        try:
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
        self.wfile.write(b"Bot is Running (Aiogram Mode)!")
```

### 2. ቀጣይ ማድረግ ያለብህ (ግዴታ ነው!)

ይህ ኮድ `aiogram` ስለሚጠቀም፣ **`requirements.txt`** ፋይልህን የግድ ማስተካከል አለብህ። ከዚህ በፊት የነበረውን አጥፋና በዚህ ተካው፡

**`requirements.txt` (አዲስ):**
```text
aiogram
motor
dnspython
pymongo
