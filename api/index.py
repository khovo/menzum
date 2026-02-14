from flask import Flask, request
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
import asyncio
import logging
import aiohttp 
import re
import time
from datetime import datetime, timedelta

# Logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID = os.environ.get("ADMIN_ID")

FORCE_CHANNEL_USERNAME = "Al_madih" 
FORCE_CHANNEL_URL = "https://t.me/Al_madih"

ITEMS_PER_PAGE = 10 

# --- SPEED BOOST: MEMORY CACHE ---
MEMBERSHIP_CACHE = {} 
CACHED_EMPTY_RESULT = {"data": [], "time": 0}
CACHE_TTL = 60 

# --- Helpers (Now using shared session) ---
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def send_message(session, chat_id, text, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with session.post(url, json=payload) as resp: return await resp.json()
    except: pass

async def send_audio(session, chat_id, audio_file_id, caption, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    payload = {"chat_id": chat_id, "audio": audio_file_id, "caption": caption, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with session.post(url, json=payload) as resp: return await resp.json()
    except: pass

async def edit_message_text(session, chat_id, message_id, text, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with session.post(url, json=payload) as resp: return await resp.json()
    except: pass

async def answer_callback_query(session, callback_query_id, text=None, show_alert=False):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    if show_alert: payload["show_alert"] = True
    try:
        async with session.post(url, json=payload) as resp: return await resp.json()
    except: pass

# 🔥 SUPER OPTIMIZED: Membership Check with Session Reuse
async def check_membership(session, user_id):
    if not BOT_TOKEN: return True
    
    # 1. Check Cache
    current_time = time.time()
    if user_id in MEMBERSHIP_CACHE:
        is_member, timestamp = MEMBERSHIP_CACHE[user_id]
        if current_time - timestamp < CACHE_TTL:
            return is_member

    # 2. Call Telegram API (Using shared session)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    try:
        async with session.get(url, params=params) as resp:
            res = await resp.json()
            if not res.get("ok"): return True 
            status = res["result"]["status"]
            is_member = status in ["creator", "administrator", "member"]
            
            # Save to Cache
            MEMBERSHIP_CACHE[user_id] = (is_member, current_time)
            return is_member
    except: return True

async def answer_inline_query(session, query_id, results, switch_pm_text=None, switch_pm_param=None, cache_time=300):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    payload = {"inline_query_id": query_id, "results": results, "cache_time": cache_time, "is_personal": True}
    if switch_pm_text:
        payload["switch_pm_text"] = switch_pm_text
        payload["switch_pm_parameter"] = switch_pm_param
    try:
        async with session.post(url, json=payload) as resp: return await resp.json()
    except: pass

async def copy_message(session, chat_id, from_chat_id, message_id, reply_markup=None):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with session.post(url, json=payload) as resp: return await resp.json()
    except: pass

# --- DB Helpers ---
async def track_user(db, user_id, first_name):
    try:
        now = datetime.now()
        await db.users.update_one(
            {"_id": int(user_id)},
            {"$set": {"first_name": first_name, "last_active": now}, "$setOnInsert": {"joined_at": now}},
            upsert=True
        )
    except: pass

async def toggle_favorite(db, user_id, file_id):
    try:
        user = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
        if not user: user = await db.users.find_one({"_id": str(user_id)}, {"favorites": 1})
        
        target_id = user["_id"] if user else int(user_id)
        favorites = user.get("favorites", []) if user else []
        
        if file_id in favorites:
            await db.users.update_one({"_id": target_id}, {"$pull": {"favorites": file_id}})
            return False
        else:
            await db.users.update_one({"_id": target_id}, {"$addToSet": {"favorites": file_id}})
            return True
    except: return False

async def get_user_data(db, user_id):
    try:
        return await db.users.find_one({"_id": int(user_id)})
    except: return None

async def set_user_state(db, user_id, state, meta=None):
    update = {"$set": {"state": state}}
    if meta: update["$set"].update(meta)
    await db.users.update_one({"_id": int(user_id)}, update, upsert=True)

def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    if len(query_text) == 1:
        return {"display_name": {"$regex": f"^{re.escape(query_text)}", "$options": "i"}}
    words = query_text.split()
    conditions = [{"display_name": {"$regex": re.escape(word), "$options": "i"}} for word in words]
    if len(conditions) == 1: return conditions[0]
    return {"$and": conditions}

async def get_catalog_page(db, page):
    limit = ITEMS_PER_PAGE
    skip = (page - 1) * limit
    total_docs = await db.files.count_documents({"file_id": {"$exists": True}})
    total_pages = (total_docs + limit - 1) // limit
    
    cursor = db.files.find(
        {"file_id": {"$exists": True}},
        {"display_name": 1}
    ).sort("_id", -1).skip(skip).limit(limit)
    
    msg_text = f"📂 **የመንዙማዎች ዝርዝር (ገጽ {page}/{total_pages})**\n\n💡 _ስሙን ሲነኩት ኮፒ ይሆናል፣ ከዛ ለቦቱ ይላኩት።_\n\n"
    idx = skip + 1
    async for doc in cursor:
        clean_name = doc.get("display_name", "Unknown").replace("`", "") 
        msg_text += f"{idx}. `{clean_name}`\n"
        idx += 1
    
    buttons = []
    nav_row = []
    if page > 1: nav_row.append({"text": "⬅️ Back", "callback_data": f"pg_{page-1}"})
    nav_row.append({"text": "❌ ዝጋ", "callback_data": "pg_close"})
    if page < total_pages: nav_row.append({"text": "Next ➡️", "callback_data": f"pg_{page+1}"})
    buttons.append(nav_row)
    return msg_text, {"inline_keyboard": buttons}

async def get_daily_stats(db):
    try:
        now = datetime.now()
        last_24h = now - timedelta(hours=24)
        new_users = await db.users.count_documents({"joined_at": {"$gte": last_24h}})
        active_users = await db.users.count_documents({"last_active": {"$gte": last_24h}})
        total_users = await db.users.count_documents({})
        total_files = await db.files.count_documents({})
        return f"📅 **Daily Statistics**\n\n🆕 New: `{new_users}`\n⚡ Active: `{active_users}`\n👥 Total: `{total_users}`\n📂 Files: `{total_files}`"
    except: return "Error"

def get_main_menu_kb():
    return {
        "inline_keyboard": [
            [
                {"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"},
                {"text": "📂 Catalog (List)", "callback_data": "pg_1"}
            ],
            [{"text": "📞 አስተያየት ለመስጠት (Support)", "callback_data": "support_start"}],
            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}]
        ]
    }

# --- Main Logic ---
async def process_telegram_update(data):
    if not MONGO_URL or not BOT_TOKEN: return
    db_client = AsyncIOMotorClient(MONGO_URL)
    db = db_client["MenzumaDB"]

    # 🔥 OPTIMIZATION: Create ONE session for the entire update
    async with aiohttp.ClientSession() as session:
        try:
            # 1. Callback Query (Buttons)
            if "callback_query" in data:
                cb = data["callback_query"]
                user_id = cb["from"]["id"]
                cb_id = cb["id"]
                data_str = cb.get("data", "")
                chat_id = cb["message"]["chat"]["id"]
                message_id = cb["message"]["message_id"]
                
                # --- SECURITY GATEKEEPER ---
                if data_str != "check_subscription":
                    if not await check_membership(session, user_id):
                        await answer_callback_query(session, cb_id, "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!", show_alert=True)
                        return 

                # --- BUTTON LOGIC ---
                if data_str == "check_subscription":
                    if user_id in MEMBERSHIP_CACHE: del MEMBERSHIP_CACHE[user_id]

                    if await check_membership(session, user_id):
                        await answer_callback_query(session, cb_id, "✅ እንኳን ደህና መጡ!")
                        welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                        await edit_message_text(session, chat_id, message_id, welcome, reply_markup=get_main_menu_kb())
                    else:
                        await answer_callback_query(session, cb_id, "❌ አሁንም አልተቀላቀሉም! ቻናሉን Join ይበሉ", show_alert=True)
                    return

                # Support Buttons
                if data_str == "support_start":
                    await set_user_state(db, user_id, "support_wait")
                    kb = {"inline_keyboard": [[{"text": "🔙 ተመለስ", "callback_data": "support_cancel"}]]}
                    await edit_message_text(session, chat_id, message_id, "📝 **ሀሳቦን እዚህ ጋር ይጻፉ ወይም 'ተመለስ' የሚለውን በተን ይጫኑ።**", reply_markup=kb)
                    await answer_callback_query(session, cb_id)
                    return

                if data_str == "support_cancel":
                    await set_user_state(db, user_id, "idle")
                    welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                    await edit_message_text(session, chat_id, message_id, welcome, reply_markup=get_main_menu_kb())
                    await answer_callback_query(session, cb_id)
                    return
                
                if data_str.startswith("reply_") and str(user_id) == str(ADMIN_ID):
                    target_user_id = data_str.split("_")[1]
                    await set_user_state(db, user_id, "admin_reply_wait", {"target_user_id": target_user_id})
                    await send_message(session, chat_id, f"📝 **መልስ ለተጠቃሚ {target_user_id} እየጻፉ ነው:**\n\nመልእክቱን ይጻፉ (Text, Voice, Photo...).")
                    await answer_callback_query(session, cb_id)
                    return

                if data_str.startswith("pg_"):
                    if data_str == "pg_close":
                        welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                        await edit_message_text(session, chat_id, message_id, welcome, reply_markup=get_main_menu_kb())
                    else:
                        new_page = int(data_str.split("_")[1])
                        text, kb = await get_catalog_page(db, new_page)
                        await edit_message_text(session, chat_id, message_id, text, reply_markup=kb)
                    await answer_callback_query(session, cb_id)
                    return

                if data_str.startswith("fav_"):
                    doc_id = data_str.split("fav_")[1]
                    try:
                        if len(doc_id) == 24:
                            file_exists = await db.files.find_one({"_id": ObjectId(doc_id)}, {"_id": 1, "file_id": 1})
                            if file_exists:
                                is_fav = await toggle_favorite(db, user_id, file_exists['file_id'])
                                text = "❤️ Saved" if is_fav else "💔 Removed"
                                await answer_callback_query(session, cb_id, text)
                            else:
                                await answer_callback_query(session, cb_id, "⚠️ Missing")
                        else:
                            await answer_callback_query(session, cb_id, "⚠️ Error")
                    except:
                        await answer_callback_query(session, cb_id, "Error")
                    return

                if data_str.startswith("report_") or data_str.startswith("broadcast_"):
                    if data_str.startswith("report_"):
                        doc_id = data_str.split("report_")[1]
                        try:
                            file_doc = await db.files.find_one({"_id": ObjectId(doc_id)}, {"display_name": 1})
                            if file_doc:
                                await send_message(session, ADMIN_ID, f"🚨 Report: `{file_doc.get('display_name')}`\nID: `{doc_id}`")
                                await answer_callback_query(session, cb_id, "✅ Reported!", show_alert=True)
                        except: pass
                    
                    elif data_str == "broadcast_confirm" and str(user_id) == str(ADMIN_ID):
                        admin_data = await get_user_data(db, user_id)
                        msg_id = (admin_data or {}).get("broadcast_msg_id")
                        markup = (admin_data or {}).get("broadcast_markup")
                        if msg_id:
                            await edit_message_text(session, chat_id, message_id, "🚀 Sending...")
                            users = db.users.find({}, {"_id": 1})
                            count = 0
                            async for u in users:
                                try:
                                    await copy_message(session, u["_id"], chat_id, msg_id, reply_markup=markup)
                                    count += 1
                                    await asyncio.sleep(0.05) 
                                except: pass
                            await send_message(session, chat_id, f"✅ Sent to {count}")
                            await set_user_state(db, user_id, "idle")
                        await answer_callback_query(session, cb_id)
                    elif data_str == "broadcast_cancel":
                        await edit_message_text(session, chat_id, message_id, "❌ Cancelled")
                        await set_user_state(db, user_id, "idle")
                        await answer_callback_query(session, cb_id)
                return

            # 2. Message Handling
            if "message" in data:
                message = data["message"]
                chat_id = message.get("chat", {}).get("id")
                user_id = message.get("from", {}).get("id")
                text = message.get("text", "")
                
                # --- SECURITY GATEKEEPER ---
                is_joined = await check_membership(session, user_id)
                if not is_joined:
                    msg = "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**"
                    kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}], [{"text": "✅ ተቀላቅያለሁ (Verify)", "callback_data": "check_subscription"}]]}
                    await send_message(session, chat_id, msg, reply_markup=kb)
                    return

                if text == "/start":
                    first_name = message.get("from", {}).get("first_name", "User")
                    await track_user(db, user_id, first_name)
                    welcome = "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*"
                    await send_message(session, chat_id, welcome, reply_markup=get_main_menu_kb())
                    return

                if text == "/list" or text == "📂 Catalog (List)":
                    msg_text, kb = await get_catalog_page(db, 1) 
                    await send_message(session, chat_id, msg_text, reply_markup=kb)
                    return

                # Support & Admin Logic
                user_data = await get_user_data(db, user_id)
                state = (user_data or {}).get("state")

                if state == "support_wait":
                    if text == "/start":
                        await set_user_state(db, user_id, "idle")
                        await send_message(session, chat_id, "🏠 ወደ ዋናው ገጽ ተመልሰዋል።", reply_markup=get_main_menu_kb())
                        return

                    sender_name = message.get("from", {}).get("first_name", "User")
                    kb = {"inline_keyboard": [[{"text": "↩️ መልስ ለመስጠት (Reply)", "callback_data": f"reply_{user_id}"}]]}
                    await send_message(session, ADMIN_ID, f"📩 **New Feedback from:** {sender_name} (`{user_id}`)", reply_markup=kb)
                    await copy_message(session, ADMIN_ID, chat_id, message.get("message_id"))
                    
                    await send_message(session, chat_id, "✅ **መልእክትዎ ተልኳል! እናመሰግናለን።**\n\nወደ ዋናው ገጽ ተመልሰዋል።", reply_markup=get_main_menu_kb())
                    await set_user_state(db, user_id, "idle")
                    return

                if str(user_id) == str(ADMIN_ID):
                    if text == "/admin":
                        kb = {"keyboard": [[{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}], [{"text": "📢 Broadcast"}, {"text": "📂 Total Files"}]], "resize_keyboard": True}
                        await send_message(session, chat_id, "Admin Panel", reply_markup=kb)
                    elif text == "📊 Statistics":
                        u = await db.users.count_documents({})
                        f = await db.files.count_documents({})
                        await send_message(session, chat_id, f"Users: {u}\nFiles: {f}")
                    elif text == "📅 Daily Stats":
                        msg = await get_daily_stats(db)
                        await send_message(session, chat_id, msg)
                    elif text == "📢 Broadcast":
                        await set_user_state(db, user_id, "broadcast_wait")
                        await send_message(session, chat_id, "Send message to broadcast.")
                    
                    if state == "admin_reply_wait":
                        target_user = (user_data or {}).get("target_user_id")
                        if target_user:
                            try:
                                await send_message(session, target_user, "🔔 **ከአድሚኑ የተሰጠ መልስ:**")
                                await copy_message(session, target_user, chat_id, message["message_id"])
                                await send_message(session, chat_id, "✅ መልሱ ተልኳል!")
                            except Exception as e:
                                await send_message(session, chat_id, f"❌ አልተላከም: {e}")
                            
                            await set_user_state(db, user_id, "idle")
                        return

                    if state == "broadcast_wait" and text != "🔙 Back" and "message_id" in message:
                        await set_user_state(db, user_id, "broadcast_confirm", {"broadcast_msg_id": message["message_id"], "broadcast_markup": message.get("reply_markup")})
                        await copy_message(session, chat_id, chat_id, message["message_id"], reply_markup=message.get("reply_markup"))
                        kb = {"inline_keyboard": [[{"text": "✅ Post", "callback_data": "broadcast_confirm"}], [{"text": "❌ Cancel", "callback_data": "broadcast_cancel"}]]}
                        await send_message(session, chat_id, "Confirm?", reply_markup=kb)
                        return

                    if "audio" in message or "voice" in message:
                        f = message.get("audio") or message.get("voice")
                        cap = message.get("caption", "").split('\n')[0].strip()
                        name = cap if cap else f.get("file_name", "Unknown")
                        if len(name) > 3:
                            await db.files.update_one(
                                {"display_name": {"$regex": re.escape(name), "$options": "i"}},
                                {"$set": {"file_id": f["file_id"], "display_name": name}},
                                upsert=True
                            )
                            await send_message(session, chat_id, f"✅ Saved: `{name}`")
                    return

                if text and not text.startswith("/"):
                    sq = build_search_query(text)
                    doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})
                    if doc:
                        kb = {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }], [{"text": "↗️ Share", "switch_inline_query": ""}, {"text": "⚠️ Report", "callback_data": f"report_{str(doc['_id'])}" }]]}
                        await send_audio(session, chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot", kb)
                    else:
                        await send_message(session, chat_id, "😔 አልተገኘም።")

            # 3. Inline Query (Optimized & Fixed)
            elif "inline_query" in data:
                iq = data["inline_query"]
                query_id = iq["id"]
                query = iq.get("query", "").strip().lower()

                results = []

                # --- A. FAVORITES LIST ---
                if query.startswith("#favorites"):
                    user_id = iq.get("from", {}).get("id")
                    # handle int/str id mismatch
                    user = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
                    if not user: user = await db.users.find_one({"_id": str(user_id)}, {"favorites": 1})
                    
                    fav_ids = user.get("favorites", []) if user else []
                    if fav_ids:
                        cursor = db.files.find({"file_id": {"$in": fav_ids}}, {"file_id": 1, "display_name": 1}).limit(50)
                        docs = await cursor.to_list(length=50)
                        for doc in docs:
                            results.append({
                                "type": "audio",
                                "id": str(doc["_id"]),
                                "audio_file_id": doc["file_id"],
                                "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                                "reply_markup": {"inline_keyboard": [[{"text": "💔 Remove", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                            })
                    # Always send response even if empty
                    await answer_inline_query(session, query_id, results, cache_time=10, switch_pm_text="Favorites", switch_pm_param="start")

                # --- B. EMPTY QUERY (RECENT FILES) ---
                elif not query:
                    current_time = time.time()
                    # Check Cache
                    if CACHED_EMPTY_RESULT["data"] and (current_time - CACHED_EMPTY_RESULT["time"] < CACHE_TTL):
                        results = CACHED_EMPTY_RESULT["data"]
                    else:
                        # Fetch Fresh
                        cursor = db.files.find({"file_id": {"$exists": True}}, {"file_id": 1, "display_name": 1}).sort("_id", -1).limit(50)
                        docs = await cursor.to_list(length=50)
                        for doc in docs:
                            results.append({
                                "type": "audio",
                                "id": str(doc["_id"]),
                                "audio_file_id": doc["file_id"],
                                "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                                "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                            })
                        # Update Cache
                        CACHED_EMPTY_RESULT["data"] = results
                        CACHED_EMPTY_RESULT["time"] = current_time
                    
                    # Send Response
                    await answer_inline_query(session, query_id, results, cache_time=300, switch_pm_text="Open Bot", switch_pm_param="start")

                # --- C. SEARCH QUERY ---
                else:
                    sq = build_search_query(query)
                    cursor = db.files.find(sq, {"file_id": 1, "display_name": 1}).limit(50)
                    docs = await cursor.to_list(length=50)
                    for doc in docs:
                        results.append({
                            "type": "audio",
                            "id": str(doc["_id"]),
                            "audio_file_id": doc["file_id"],
                            "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                            "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                        })
                    
                    await answer_inline_query(session, query_id, results, cache_time=300)

        except Exception as e:
            logger.error(f"Err: {e}")
        finally:
            db_client.close()

@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            run_async(process_telegram_update(data))
            return 'ok'
        except: return 'error', 500
    return 'Al-Madih Bot Running (Electric Speed ⚡) 🚀'

if __name__ == '__main__':
    app.run(debug=True)

