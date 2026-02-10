from flask import Flask, request
from pymongo import MongoClient
from bson import ObjectId
import os
import logging
import requests
import re
import time
import certifi  # <--- NEW IMPORT
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

# --- GLOBAL DB CONNECTION (SSL FIX) ---
try:
    # ca=certifi.where() is CRITICAL for Vercel
    client = MongoClient(MONGO_URL, tlsCAFile=certifi.where())
    db = client["MenzumaDB"]
    # Test connection immediately to fail fast if broken
    client.admin.command('ping')
    logger.info("MongoDB Connected Successfully!")
except Exception as e:
    logger.error(f"DB Connection Error: {e}")
    db = None

# --- IN-MEMORY CACHES ---
MEMBERSHIP_CACHE = {} 
USER_UPDATE_CACHE = {} 
CACHED_EMPTY_RESULT = {"data": [], "time": 0} 
CACHE_TTL = 300 

# --- Synchronous Helpers ---
def send_request(method, payload):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=5)
        return resp.json()
    except: return None

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    return send_request("sendMessage", payload)

def send_audio(chat_id, audio_file_id, caption, reply_markup=None):
    payload = {"chat_id": chat_id, "audio": audio_file_id, "caption": caption, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    return send_request("sendAudio", payload)

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if reply_markup: payload["reply_markup"] = reply_markup
    return send_request("editMessageText", payload)

def answer_callback_query(callback_query_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    if show_alert: payload["show_alert"] = True
    return send_request("answerCallbackQuery", payload)

def answer_inline_query(query_id, results, cache_time=300):
    payload = {"inline_query_id": query_id, "results": results, "cache_time": cache_time}
    return send_request("answerInlineQuery", payload)

def check_membership(user_id):
    if not BOT_TOKEN: return True
    
    current_time = time.time()
    if user_id in MEMBERSHIP_CACHE:
        if current_time - MEMBERSHIP_CACHE[user_id] < 300: 
            return True
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    params = {"chat_id": f"@{FORCE_CHANNEL_USERNAME}", "user_id": user_id}
    try:
        resp = requests.get(url, params=params, timeout=5)
        res = resp.json()
        if not res.get("ok"): return True 
        status = res["result"]["status"]
        is_member = status in ["creator", "administrator", "member"]
        if is_member:
            MEMBERSHIP_CACHE[user_id] = current_time
        return is_member
    except: return True

def track_user(user_id, first_name):
    if not db: return
    current_time = time.time()
    if user_id in USER_UPDATE_CACHE:
        if current_time - USER_UPDATE_CACHE[user_id] < 3600:
            return 
            
    try:
        now = datetime.now()
        db.users.update_one(
            {"_id": int(user_id)},
            {"$set": {"first_name": first_name, "last_active": now}, "$setOnInsert": {"joined_at": now}},
            upsert=True
        )
        USER_UPDATE_CACHE[user_id] = current_time
    except: pass

def toggle_favorite(user_id, file_id):
    if not db: return False
    try:
        res = db.users.update_one({"_id": int(user_id)}, {"$addToSet": {"favorites": file_id}})
        if res.modified_count > 0: return True 
        
        res = db.users.update_one({"_id": int(user_id)}, {"$pull": {"favorites": file_id}})
        if res.modified_count > 0: return False 
        
        # Fallback for old string IDs
        res = db.users.update_one({"_id": str(user_id)}, {"$addToSet": {"favorites": file_id}})
        return True
    except: return False

def build_search_query(query_text):
    if not query_text: return {}
    query_text = query_text.strip()
    if len(query_text) == 1:
        return {"display_name": {"$regex": f"^{re.escape(query_text)}", "$options": "i"}}
    words = query_text.split()
    conditions = [{"display_name": {"$regex": re.escape(word), "$options": "i"}} for word in words]
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}

def get_catalog_page(page):
    if not db: return "Error: DB Disconnected", {}
    skip = (page - 1) * ITEMS_PER_PAGE
    cursor = db.files.find({"file_id": {"$exists": True}}, {"display_name": 1}).sort("_id", -1).skip(skip).limit(ITEMS_PER_PAGE)
    
    # Estimate total
    total_docs = 1400 
    total_pages = (total_docs + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    msg_text = f"📂 **የመንዙማዎች ዝርዝር (ገጽ {page})**\n\n💡 _ስሙን ሲነኩት ኮፒ ይሆናል፣ ከዛ ለቦቱ ይላኩት።_\n\n"
    idx = skip + 1
    for doc in cursor:
        clean_name = doc.get("display_name", "Unknown").replace("`", "") 
        msg_text += f"{idx}. `{clean_name}`\n"
        idx += 1
    
    buttons = []
    nav_row = []
    if page > 1: nav_row.append({"text": "⬅️ Back", "callback_data": f"pg_{page-1}"})
    nav_row.append({"text": "❌ ዝጋ", "callback_data": "pg_close"})
    nav_row.append({"text": "Next ➡️", "callback_data": f"pg_{page+1}"})
    buttons.append(nav_row)
    return msg_text, {"inline_keyboard": buttons}

def get_main_menu_kb():
    return {
        "inline_keyboard": [
            [
                {"text": "❤️ Favorites", "switch_inline_query_current_chat": "#favorites"},
                {"text": "📂 Catalog (List)", "callback_data": "pg_1"}
            ],
            [{"text": "🔍 Search Name", "switch_inline_query_current_chat": ""}]
        ]
    }

def get_user_data(user_id):
    if not db: return None
    try:
        data = db.users.find_one({"_id": int(user_id)})
        if data: return data
    except: pass
    return db.users.find_one({"_id": str(user_id)})

def set_user_state(user_id, state, meta=None):
    if not db: return
    update = {"$set": {"state": state}}
    if meta: update["$set"].update(meta)
    db.users.update_one({"_id": int(user_id)}, update, upsert=True)

def copy_message(chat_id, from_chat_id, message_id, reply_markup=None):
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    if reply_markup: payload["reply_markup"] = reply_markup
    return send_request("copyMessage", payload)

def get_daily_stats():
    if not db: return "DB Error"
    try:
        now = datetime.now()
        last_24h = now - timedelta(hours=24)
        new_users = db.users.count_documents({"joined_at": {"$gte": last_24h}})
        active_users = db.users.count_documents({"last_active": {"$gte": last_24h}})
        total_users = db.users.count_documents({})
        total_files = db.files.count_documents({})
        return f"📅 **Daily Stats**\n\n🆕 New: `{new_users}`\n⚡ Active: `{active_users}`\n👥 Total: `{total_users}`\n📂 Files: `{total_files}`"
    except: return "Error"

# --- Main Logic (Synchronous) ---
def process_telegram_update(data):
    if not db: 
        logger.error("DB NOT CONNECTED")
        return 

    try:
        # 1. Callback Query
        if "callback_query" in data:
            cb = data["callback_query"]
            user_id = cb["from"]["id"]
            cb_id = cb["id"]
            data_str = cb.get("data", "")
            chat_id = cb["message"]["chat"]["id"]
            message_id = cb["message"]["message_id"]
            
            if data_str == "check_subscription":
                if check_membership(user_id):
                    answer_callback_query(cb_id, "✅ ተቀላቅለዋል!")
                    edit_message_text(chat_id, message_id, "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*", reply_markup=get_main_menu_kb())
                else:
                    answer_callback_query(cb_id, "❌ አሁንም አልተቀላቀሉም!", show_alert=True)
                return

            if data_str.startswith("fav_"):
                doc_id = data_str.split("fav_")[1]
                target_file_id = doc_id
                if len(doc_id) == 24:
                    f = db.files.find_one({"_id": ObjectId(doc_id)}, {"file_id": 1})
                    if f: target_file_id = f['file_id']
                
                is_fav = toggle_favorite(user_id, target_file_id)
                text = "❤️ Saved" if is_fav else "💔 Removed"
                answer_callback_query(cb_id, text)
            
            elif data_str.startswith("pg_"):
                 if data_str == "pg_close":
                    edit_message_text(chat_id, message_id, "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*", reply_markup=get_main_menu_kb())
                 else:
                    new_page = int(data_str.split("_")[1])
                    text, kb = get_catalog_page(new_page)
                    edit_message_text(chat_id, message_id, text, reply_markup=kb)
                 answer_callback_query(cb_id)

            elif data_str.startswith("report_"):
                answer_callback_query(cb_id, "✅ ሪፖርት ተልኳል!", show_alert=True)
                send_message(ADMIN_ID, f"Report: {data_str} by {user_id}")

            return

        # 2. Message Handling
        if "message" in data:
            message = data["message"]
            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            first_name = message.get("from", {}).get("first_name", "User")
            text = message.get("text", "")
            
            track_user(user_id, first_name)

            if text == "/start":
                send_message(chat_id, "*🌙 እንኳን ወደ አል-ማዲህ (Al-Madih) በደህና መጡ! 🌙*", reply_markup=get_main_menu_kb())
                return

            if not check_membership(user_id):
                kb = {"inline_keyboard": [[{"text": "Join Channel 📢", "url": FORCE_CHANNEL_URL}], [{"text": "✅ ተቀላቅያለሁ (Verify)", "callback_data": "check_subscription"}]]}
                send_message(chat_id, "**⚠️ ይቅርታ! ቦቱን ለመጠቀም መጀመሪያ ቻናላችንን ይቀላቀሉ።**", reply_markup=kb)
                return

            if text == "/list" or text == "📂 Catalog (List)":
                msg, kb = get_catalog_page(1)
                send_message(chat_id, msg, reply_markup=kb)
                return

            # Admin & File Upload
            if str(user_id) == str(ADMIN_ID):
                if text == "/admin":
                    admin_kb = {"keyboard": [[{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}], [{"text": "📢 Broadcast"}, {"text": "👥 User Count"}], [{"text": "📂 Total Files"}]], "resize_keyboard": True}
                    send_message(chat_id, "👋 Admin Panel", reply_markup=admin_kb)
                    return
                elif text == "📊 Statistics" or text == "/stats":
                    u = db.users.count_documents({})
                    f = db.files.count_documents({})
                    send_message(chat_id, f"Users: {u}, Files: {f}")
                    return
                elif text == "📅 Daily Stats":
                    send_message(chat_id, get_daily_stats())
                    return
                elif text == "📢 Broadcast":
                    set_user_state(user_id, "broadcast_wait")
                    send_message(chat_id, "Send message to broadcast or '🔙 Back'.")
                    return
                elif text == "🔙 Back":
                    set_user_state(user_id, "idle")
                    send_message(chat_id, "Back to menu.")
                    return
                
                # Check for broadcast state
                admin_data = get_user_data(user_id)
                state = (admin_data or {}).get("state")
                
                if state == "broadcast_wait":
                    msg_id = message["message_id"]
                    markup = message.get("reply_markup")
                    set_user_state(user_id, "broadcast_confirm", {"broadcast_msg_id": msg_id, "broadcast_markup": markup})
                    copy_message(chat_id, chat_id, msg_id, reply_markup=markup)
                    kb = {"inline_keyboard": [[{"text": "✅ Post", "callback_data": "broadcast_confirm"}], [{"text": "❌ Cancel", "callback_data": "broadcast_cancel"}]]}
                    send_message(chat_id, "Confirm?", reply_markup=kb)
                    return

                if "audio" in message or "voice" in message:
                    file_obj = message.get("audio") or message.get("voice")
                    clean_name = (message.get("caption") or file_obj.get("file_name", "Audio")).split('\n')[0].strip()
                    clean_search = clean_name.replace("@Almadihbot", "").strip()
                    if len(clean_search) > 2:
                        db.files.update_one(
                            {"display_name": {"$regex": re.escape(clean_search), "$options": "i"}},
                            {"$set": {"file_id": file_obj.get("file_id"), "display_name": clean_name}},
                            upsert=True
                        )
                        send_message(chat_id, "✅ Saved")
                return

            if data.get("callback_query"): # Late check for broadcast buttons
                pass 

            # Text Search (Faster Direct)
            if text and not text.startswith("/"):
                query = build_search_query(text)
                doc = db.files.find_one(query, {"file_id": 1, "display_name": 1})
                if doc:
                    kb = {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }], [{"text": "↗️ Share", "switch_inline_query": ""}, {"text": "⚠️ Report", "callback_data": f"report_{str(doc['_id'])}" }]]}
                    send_audio(chat_id, doc['file_id'], f"{doc.get('display_name')}\n\n@Almadihbot", kb)
                    db.files.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})
                else:
                    send_message(chat_id, "😔 አልተገኘም።")

        # 3. Inline Query (SYNC & FAST)
        elif "inline_query" in data:
            iq = data["inline_query"]
            query_id = iq["id"]
            user_id = iq.get("from", {}).get("id")
            query = iq.get("query", "").strip().lower()

            if not check_membership(user_id):
                answer_inline_query(query_id, [], cache_time=300)
                return

            results = []

            # A. Favorites
            if query.startswith("#favorites"):
                user = db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
                if not user: user = db.users.find_one({"_id": str(user_id)}, {"favorites": 1})
                
                fav_ids = user.get("favorites", []) if user else []
                if fav_ids:
                    cursor = db.files.find({"file_id": {"$in": fav_ids}}, {"file_id": 1, "display_name": 1}).limit(50)
                    for doc in cursor:
                        results.append({
                            "type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"],
                            "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                            "reply_markup": {"inline_keyboard": [[{"text": "💔 Remove", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                        })
                else:
                     results.append({"type": "article", "id": "404", "title": "No Favorites", "input_message_content": {"message_text": "No favorites yet."}})

            # B. Empty Query
            elif not query:
                if CACHED_EMPTY_RESULT["data"] and (time.time() - CACHED_EMPTY_RESULT["time"] < CACHE_TTL):
                    answer_inline_query(query_id, CACHED_EMPTY_RESULT["data"], cache_time=300)
                    return
                
                cursor = db.files.find({"file_id": {"$exists": True}}, {"file_id": 1, "display_name": 1}).sort("_id", -1).limit(20)
                for doc in cursor:
                     results.append({
                        "type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"],
                        "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                         "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                    })
                
                if results:
                    CACHED_EMPTY_RESULT["data"] = results
                    CACHED_EMPTY_RESULT["time"] = time.time()

            # C. Search Query
            else:
                mongo_query = build_search_query(query)
                mongo_query["file_id"] = {"$exists": True}
                cursor = db.files.find(mongo_query, {"file_id": 1, "display_name": 1}).limit(20)
                for doc in cursor:
                     results.append({
                        "type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"],
                        "caption": f"{doc.get('display_name')}\n\n@Almadihbot",
                         "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}" }]]}
                    })

            answer_inline_query(query_id, results, cache_time=300)

    except Exception as e:
        logger.error(f"Error: {e}")

@app.route('/', methods=['GET', 'POST'])
@app.route('/api/webhook', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            process_telegram_update(data)
            return 'ok'
        except: return 'error', 500
    return 'Al-Madih Bot Running (Sync SSL Mode) 🚀'

if __name__ == '__main__':
    app.run(debug=True)
