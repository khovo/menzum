from flask import Flask, request, jsonify
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
import asyncio
import logging
import aiohttp 
import re
import time
from datetime import datetime, timedelta

# --- CONFIGURATION ---
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID = os.environ.get("ADMIN_ID")
FORCE_CHANNEL_USERNAME = "Al_madih" 
FORCE_CHANNEL_URL = "https://t.me/Al_madih"

# Performance Settings
ITEMS_PER_PAGE = 10 
CACHE_TTL = 300 # 5 minutes cache

# --- 🚀 SPEED OPTIMIZATION: GLOBAL DB CLIENT ---
# Vercel will keep this variable alive between requests (Warm Start)
try:
    mongo_client = AsyncIOMotorClient(MONGO_URL)
    db = mongo_client["MenzumaDB"]
except:
    db = None

# --- IN-MEMORY CACHE (Ephemeral) ---
MEMBERSHIP_CACHE = {} 

# --- Helper: Async Runner ---
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

# --- Telegram API Helpers (Optimized) ---
async def call_api(session, method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        async with session.post(url, json=payload) as resp:
            return await resp.json()
    except:
        return None

async def check_membership(session, user_id):
    # 1. Check RAM Cache first (Instant)
    current_time = time.time()
    if user_id in MEMBERSHIP_CACHE:
        is_member, timestamp = MEMBERSHIP_CACHE[user_id]
        if current_time - timestamp < CACHE_TTL:
            return is_member

    # 2. Check API
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    try:
        async with session.get(url, params=params) as resp:
            res = await resp.json()
            if not res.get("ok"): return True 
            status = res["result"]["status"]
            is_member = status in ["creator", "administrator", "member"]
            # Cache the result
            MEMBERSHIP_CACHE[user_id] = (is_member, current_time)
            return is_member
    except:
        return True

# --- Database Helpers ---
async def get_user_state(user_id):
    try:
        doc = await db.users.find_one({"_id": int(user_id)}, {"state": 1, "meta": 1})
        return doc.get("state"), doc.get("meta")
    except: return None, None

async def set_user_state(user_id, state, meta=None):
    update = {"$set": {"state": state}}
    if meta: update["$set"]["meta"] = meta
    await db.users.update_one({"_id": int(user_id)}, update, upsert=True)

async def get_daily_stats():
    try:
        now = datetime.now()
        last_24h = now - timedelta(hours=24)
        
        # Run counts in parallel
        tasks = [
            db.users.count_documents({"joined_at": {"$gte": last_24h}}),
            db.users.count_documents({"last_active": {"$gte": last_24h}}),
            db.users.count_documents({}),
            db.files.count_documents({})
        ]
        new_users, active_users, total_users, total_files = await asyncio.gather(*tasks)
        
        return f"📅 **Daily Statistics**\n\n🆕 New: `{new_users}`\n⚡ Active: `{active_users}`\n👥 Total: `{total_users}`\n📂 Files: `{total_files}`"
    except: return "Error fetching stats"

async def get_catalog_page(page):
    limit = ITEMS_PER_PAGE
    skip = (page - 1) * limit
    
    count_task = db.files.count_documents({"file_id": {"$exists": True}})
    cursor = db.files.find(
        {"file_id": {"$exists": True}},
        {"display_name": 1}
    ).sort("_id", -1).skip(skip).limit(limit)
    
    total_docs, docs = await asyncio.gather(count_task, cursor.to_list(length=limit))
    total_pages = (total_docs + limit - 1) // limit
    
    msg_text = f"📂 **መንዙማዎች (ገጽ {page}/{total_pages})**\n\n"
    lines = [f"{skip+i+1}. `{doc.get('display_name', 'Unknown').replace('`', '')}`" for i, doc in enumerate(docs)]
    msg_text += "\n".join(lines)
    msg_text += "\n\n💡 _ስሙን ነክተው ኮፒ በማድረግ ይላኩት_"

    buttons = []
    nav_row = []
    if page > 1: nav_row.append({"text": "⬅️", "callback_data": f"pg_{page-1}"})
    nav_row.append({"text": "❌", "callback_data": "pg_close"})
    if page < total_pages: nav_row.append({"text": "➡️", "callback_data": f"pg_{page+1}"})
    buttons.append(nav_row)
    
    return msg_text, {"inline_keyboard": buttons}

def get_main_menu_kb():
    return {
        "inline_keyboard": [
            [
                {"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"},
                {"text": "📂 Catalog", "callback_data": "pg_1"}
            ],
            [{"text": "📞 አስተያየት (Support)", "callback_data": "support_start"}],
            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}]
        ]
    }

# --- Main Logic ---
async def process_update(data):
    if not BOT_TOKEN: return

    async with aiohttp.ClientSession() as session:
        # --- 1. Callback Query ---
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]

            # Security: Gatekeeper (Skip for check_sub button)
            if data_str != "check_subscription":
                if not await check_membership(session, user_id):
                    await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!", "show_alert": True})
                    return 

            # Catalog
            if data_str.startswith("pg_"):
                if data_str == "pg_close":
                    await call_api(session, "deleteMessage", {"chat_id": chat_id, "message_id": msg_id})
                    welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ!*"
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": welcome, "parse_mode": "Markdown", "reply_markup": get_main_menu_kb()})
                else:
                    page = int(data_str.split("_")[1])
                    text, kb = await get_catalog_page(page)
                    await call_api(session, "editMessageText", {
                        "chat_id": chat_id, "message_id": msg_id, 
                        "text": text, "parse_mode": "Markdown", "reply_markup": kb
                    })
                await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id})
                return

            # Subscription Check
            if data_str == "check_subscription":
                if user_id in MEMBERSHIP_CACHE: del MEMBERSHIP_CACHE[user_id]
                if await check_membership(session, user_id):
                    welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ!*"
                    await call_api(session, "editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": welcome, "parse_mode": "Markdown", "reply_markup": get_main_menu_kb()})
                else:
                    await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "❌ አሁንም አልተቀላቀሉም!", "show_alert": True})
                return

            # Support Logic
            if data_str == "support_start":
                await set_user_state(user_id, "support_wait")
                kb = {"inline_keyboard": [[{"text": "🔙 ተመለስ", "callback_data": "support_cancel"}]]}
                await call_api(session, "editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "📝 **መልእክትዎን እዚህ ይጻፉ:**", "parse_mode": "Markdown", "reply_markup": kb})
                await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id})
                return

            if data_str == "support_cancel":
                await set_user_state(user_id, "idle")
                welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ!*"
                await call_api(session, "editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": welcome, "parse_mode": "Markdown", "reply_markup": get_main_menu_kb()})
                await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id})
                return

            # Admin Reply Logic
            if data_str.startswith("reply_") and str(user_id) == str(ADMIN_ID):
                target_user_id = data_str.split("_")[1]
                await set_user_state(user_id, "admin_reply_wait", {"target": target_user_id})
                await call_api(session, "sendMessage", {"chat_id": chat_id, "text": f"📝 **Reply to User {target_user_id}:**\nWrite your message now."})
                await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id})
                return

            # Report Logic
            if data_str.startswith("report_"):
                doc_id = data_str.split("report_")[1]
                file_doc = await db.files.find_one({"_id": ObjectId(doc_id)}, {"display_name": 1})
                if file_doc:
                    await call_api(session, "sendMessage", {"chat_id": ADMIN_ID, "text": f"🚨 **Report:** `{file_doc.get('display_name')}`\nID: `{doc_id}`", "parse_mode": "Markdown"})
                    await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "✅ Reported to Admin!", "show_alert": True})
                return

            # Broadcast Logic
            if data_str == "broadcast_confirm" and str(user_id) == str(ADMIN_ID):
                _, meta = await get_user_state(user_id)
                msg_id_to_copy = meta.get("msg_id") if meta else None
                if msg_id_to_copy:
                    await call_api(session, "editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "🚀 Sending..."})
                    
                    # Batch processing for speed
                    users = db.users.find({}, {"_id": 1})
                    count = 0
                    async for u in users:
                        try:
                            # Use copyMessage for efficiency
                            await call_api(session, "copyMessage", {"chat_id": u["_id"], "from_chat_id": chat_id, "message_id": msg_id_to_copy})
                            count += 1
                            if count % 20 == 0: await asyncio.sleep(0.05) # Rate limit protection
                        except: pass
                    
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": f"✅ Broadcast sent to {count} users."})
                await set_user_state(user_id, "idle")
                await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id})
                return

            if data_str == "broadcast_cancel":
                await set_user_state(user_id, "idle")
                await call_api(session, "editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "❌ Broadcast Cancelled"})
                await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id})
                return

            # Favorites Logic
            if data_str.startswith("fav_"):
                doc_id = data_str.split("fav_")[1]
                await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "🔄 Updating..."})
                
                user = await db.users.find_one({"_id": int(user_id)})
                if not user: await db.users.insert_one({"_id": int(user_id), "favorites": []})
                
                action = "$addToSet"
                if user and doc_id in user.get("favorites", []):
                    action = "$pull"
                    msg = "💔 Removed"
                else:
                    msg = "❤️ Saved"
                
                await db.users.update_one({"_id": int(user_id)}, {action: {"favorites": doc_id}})
                await call_api(session, "answerCallbackQuery", {"callback_query_id": cb_id, "text": msg})
                return

        # --- 2. Message Handling ---
        if "message" in data:
            msg = data["message"]
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id")
            text = msg.get("text", "")
            
            # --- State Handling (Priority) ---
            state, meta = await get_user_state(user_id)
            
            # Support Wait Mode
            if state == "support_wait":
                if text == "/start":
                    await set_user_state(user_id, "idle")
                else:
                    kb = {"inline_keyboard": [[{"text": "↩️ Reply", "callback_data": f"reply_{user_id}"}]]}
                    sender_name = msg.get("from", {}).get("first_name", "User")
                    await call_api(session, "sendMessage", {"chat_id": ADMIN_ID, "text": f"📩 **Support Msg from:** {sender_name} (`{user_id}`)", "parse_mode": "Markdown", "reply_markup": kb})
                    await call_api(session, "copyMessage", {"chat_id": ADMIN_ID, "from_chat_id": chat_id, "message_id": msg["message_id"]})
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": "✅ **መልእክትዎ ተልኳል!**", "parse_mode": "Markdown", "reply_markup": get_main_menu_kb()})
                    await set_user_state(user_id, "idle")
                    return

            # Admin Reply Wait Mode
            if state == "admin_reply_wait" and str(user_id) == str(ADMIN_ID):
                target_user = meta.get("target")
                if target_user:
                    await call_api(session, "sendMessage", {"chat_id": target_user, "text": "🔔 **Admin Response:**", "parse_mode": "Markdown"})
                    await call_api(session, "copyMessage", {"chat_id": target_user, "from_chat_id": chat_id, "message_id": msg["message_id"]})
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": "✅ Reply sent!"})
                await set_user_state(user_id, "idle")
                return

            # Broadcast Wait Mode
            if state == "broadcast_wait" and str(user_id) == str(ADMIN_ID):
                if text == "🔙 Back":
                    await set_user_state(user_id, "idle")
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": "Cancelled."})
                else:
                    await set_user_state(user_id, "idle") # Temp reset to avoid loops
                    # Save ID to meta for confirmation step (requires re-saving state properly or passing it)
                    # Simplified: Re-set state to confirm
                    await set_user_state(user_id, "broadcast_confirm", {"msg_id": msg["message_id"]})
                    
                    kb = {"inline_keyboard": [[{"text": "✅ Post", "callback_data": "broadcast_confirm"}, {"text": "❌ Cancel", "callback_data": "broadcast_cancel"}]]}
                    await call_api(session, "copyMessage", {"chat_id": chat_id, "from_chat_id": chat_id, "message_id": msg["message_id"]})
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": "Confirm Broadcast?", "reply_markup": kb})
                return

            # --- Standard Commands ---
            # Gatekeeper
            if not await check_membership(session, user_id):
                kb = {"inline_keyboard": [[{"text": "📢 Join Channel", "url": FORCE_CHANNEL_URL}], [{"text": "✅ Verify", "callback_data": "check_subscription"}]]}
                await call_api(session, "sendMessage", {"chat_id": chat_id, "text": "⚠️ *ቦቱን ለመጠቀም ቻናሉን ይቀላቀሉ!*", "parse_mode": "Markdown", "reply_markup": kb})
                return

            if text == "/start":
                # Track User
                first_name = msg.get("from", {}).get("first_name", "User")
                await db.users.update_one(
                    {"_id": int(user_id)},
                    {"$set": {"first_name": first_name, "last_active": datetime.now()}, "$setOnInsert": {"joined_at": datetime.now()}},
                    upsert=True
                )
                await set_user_state(user_id, "idle") # Reset state
                welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ!*"
                await call_api(session, "sendMessage", {"chat_id": chat_id, "text": welcome, "parse_mode": "Markdown", "reply_markup": get_main_menu_kb()})
                return

            # Admin Commands
            if str(user_id) == str(ADMIN_ID):
                if text == "/admin":
                    kb = {"keyboard": [[{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}], [{"text": "📢 Broadcast"}]], "resize_keyboard": True}
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": "Admin Panel", "reply_markup": kb})
                    return
                elif text == "📊 Statistics" or text == "📅 Daily Stats":
                    stats_msg = await get_daily_stats()
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": stats_msg, "parse_mode": "Markdown"})
                    return
                elif text == "📢 Broadcast":
                    await set_user_state(user_id, "broadcast_wait")
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": "Send the message you want to broadcast now...", "reply_markup": {"keyboard": [[{"text": "🔙 Back"}]], "resize_keyboard": True}})
                    return

                # File Upload Handling (Admin Only)
                if "audio" in msg or "voice" in msg:
                    f = msg.get("audio") or msg.get("voice")
                    cap = msg.get("caption", "").split('\n')[0].strip()
                    name = cap if cap else f.get("file_name", "Unknown")
                    if len(name) > 2:
                        await db.files.update_one(
                            {"display_name": {"$regex": re.escape(name), "$options": "i"}},
                            {"$set": {"file_id": f["file_id"], "display_name": name}},
                            upsert=True
                        )
                        await call_api(session, "sendMessage", {"chat_id": chat_id, "text": f"✅ Saved: `{name}`", "parse_mode": "Markdown"})
                    return

            # Search Logic
            if text and not text.startswith("/"):
                # 1. Exact Match
                doc = await db.files.find_one({"display_name": {"$regex": f"^{re.escape(text.strip())}", "$options": "i"}})
                if not doc:
                    # 2. Fuzzy Search
                    doc = await db.files.find_one({"display_name": {"$regex": re.escape(text.strip()), "$options": "i"}})
                
                if doc:
                    kb = {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }], [{"text": "Share", "switch_inline_query": text}, {"text": "⚠️ Report", "callback_data": f"report_{str(doc['_id'])}" }]]}
                    await call_api(session, "sendAudio", {"chat_id": chat_id, "audio": doc['file_id'], "caption": f"{doc.get('display_name')}\n@Almadihbot", "reply_markup": kb})
                else:
                    await call_api(session, "sendMessage", {"chat_id": chat_id, "text": "❌ አልተገኘም! ስሙን አስተካክለው ይጻፉ ወይም Catalog የሚለውን ይጫኑ።"})
                return

        # --- 3. Inline Query ---
        if "inline_query" in data:
            iq = data["inline_query"]
            qid = iq["id"]
            q = iq.get("query", "").strip()
            
            results = []
            
            if q == "#favorites":
                user = await db.users.find_one({"_id": int(iq["from"]["id"])}, {"favorites": 1})
                favs = user.get("favorites", []) if user else []
                if favs:
                    cursor = db.files.find({"file_id": {"$in": favs}}).limit(50)
                    docs = await cursor.to_list(length=50)
                    for doc in docs:
                        results.append({
                            "type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"],
                            "caption": f"{doc.get('display_name')}\n@Almadihbot"
                        })
            else:
                query_filter = {"file_id": {"$exists": True}}
                if q:
                    query_filter["display_name"] = {"$regex": re.escape(q), "$options": "i"}
                
                cursor = db.files.find(query_filter).limit(20)
                docs = await cursor.to_list(length=20)
                for doc in docs:
                    results.append({
                        "type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"],
                        "caption": f"{doc.get('display_name')}\n@Almadihbot",
                         "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                    })
            
            await call_api(session, "answerInlineQuery", {"inline_query_id": qid, "results": results, "cache_time": 300})

@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        try:
            run_async(process_update(request.get_json()))
            return "ok", 200
        except Exception as e:
            logger.error(f"Error: {e}")
            return "error", 200
    return "🚀 Al-Madih Bot is Running!"

if __name__ == "__main__":
    app.run(debug=True)
