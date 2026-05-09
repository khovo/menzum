"""
db.py
-----
All MongoDB Motor async operations.
"""
import re
import secrets
import string
import logging
from datetime import datetime, timedelta
from bson import ObjectId

from config import ITEMS_PER_PAGE

logger = logging.getLogger(__name__)

# Characters safe for Telegram deep-link start parameters
_PL_ALPHABET = string.ascii_letters + string.digits


# ── User Tracking & Language ──────────────────────────────────────────────────

async def track_user(db, user_id: int, first_name: str) -> None:
    try:
        now = datetime.now()
        await db.users.update_one(
            {"_id": int(user_id)},
            {
                "$set":         {"first_name": first_name, "last_active": now},
                "$setOnInsert": {"joined_at": now, "language": "am"},
            },
            upsert=True,
        )
    except Exception:
        logger.exception("track_user failed for user_id=%s", user_id)


async def track_and_get_user(db, user_id: int, first_name: str) -> dict:
    try:
        now = datetime.now()
        doc = await db.users.find_one_and_update(
            {"_id": int(user_id)},
            {
                "$set":         {"first_name": first_name, "last_active": now},
                "$setOnInsert": {"joined_at": now, "language": "am"},
            },
            upsert=True,
            return_document=True,
        )
        return doc or {}
    except Exception:
        logger.exception("track_and_get_user failed for user_id=%s", user_id)
        return {}


async def update_user_language(db, user_id: int, lang_code: str) -> None:
    try:
        await db.users.update_one(
            {"_id": int(user_id)},
            {"$set": {"language": lang_code}},
            upsert=True
        )
    except Exception:
        logger.exception("update_user_language failed for user_id=%s", user_id)


async def save_pending_start(db, user_id: int, start_param: str | None) -> None:
    try:
        update = (
            {"$set":   {"pending_start": start_param}}
            if start_param is not None
            else {"$unset": {"pending_start": ""}}
        )
        await db.users.update_one({"_id": int(user_id)}, update, upsert=True)
    except Exception:
        logger.exception("save_pending_start failed user_id=%s", user_id)


async def save_last_menu_msg_id(db, user_id: int, msg_id: int) -> None:
    try:
        await db.users.update_one(
            {"_id": int(user_id)},
            {"$set": {"last_menu_msg_id": msg_id}},
            upsert=True,
        )
    except Exception:
        logger.exception("save_last_menu_msg_id failed user_id=%s", user_id)


# ── Favorites ─────────────────────────────────────────────────────────────────

async def toggle_favorite(db, user_id: int, file_id: str) -> bool:
    try:
        user      = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
        target_id = user["_id"] if user else int(user_id)
        favorites = user.get("favorites", []) if user else []

        if file_id in favorites:
            await db.users.update_one({"_id": target_id}, {"$pull":    {"favorites": file_id}})
            return False
        else:
            await db.users.update_one({"_id": target_id}, {"$addToSet": {"favorites": file_id}})
            return True
    except Exception:
        logger.exception("toggle_favorite failed")
        return False


# ── Generic User Read / Write ─────────────────────────────────────────────────

async def get_user_data(db, user_id: int) -> dict | None:
    try:
        return await db.users.find_one({"_id": int(user_id)})
    except Exception:
        return None


async def set_user_state(db, user_id: int, state: str, meta: dict | None = None) -> None:
    update = {"$set": {"state": state}}
    if meta:
        update["$set"].update(meta)
    await db.users.update_one({"_id": int(user_id)}, update, upsert=True)


# ── File Search ───────────────────────────────────────────────────────────────

def build_search_query(query_text: str) -> dict:
    if not query_text:
        return {}
    query_text = query_text.strip()
    if len(query_text) == 1:
        return {"display_name": {"$regex": f"^{re.escape(query_text)}", "$options": "i"}}
    words      = query_text.split()
    conditions = [{"display_name": {"$regex": re.escape(w), "$options": "i"}} for w in words]
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


async def get_fuzzy_suggestions(db, query_text: str, limit: int = 5) -> list[dict]:
    if not query_text:
        return []
    words = [w for w in query_text.strip().split() if len(w) > 1]
    if not words:
        return []
    conditions = [{"display_name": {"$regex": re.escape(w), "$options": "i"}} for w in words]
    query = {"$or": conditions} if len(conditions) > 1 else conditions[0]
    try:
        cursor = db.files.find(query, {"file_id": 1, "display_name": 1}).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        logger.exception("get_fuzzy_suggestions failed")
        return []


# ── Catalog Pagination ────────────────────────────────────────────────────────

async def get_catalog_page(db, page: int) -> tuple[str, dict]:
    limit       = ITEMS_PER_PAGE
    skip        = (page - 1) * limit
    total       = await db.files.count_documents({"file_id": {"$exists": True}})
    total_pages = max(1, (total + limit - 1) // limit)

    cursor = (
        db.files.find({"file_id": {"$exists": True}}, {"display_name": 1})
        .sort("_id", -1)
        .skip(skip)
        .limit(limit)
    )

    msg_text = (
        f"📂 **የመንዙማዎች ዝርዝር (ገጽ {page}/{total_pages})**\n\n"
        "💡 _ስሙን ሲነኩት ኮፒ ይሆናል፣ ከዛ ለቦቱ ይላኩት።_\n\n"
    )
    idx = skip + 1
    async for doc in cursor:
        clean     = doc.get("display_name", "Unknown").replace("`", "")
        msg_text += f"{idx}. `{clean}`\n"
        idx      += 1

    nav_row = []
    if page > 1:
        nav_row.append({"text": "⬅️ Back", "callback_data": f"pg_{page - 1}"})
    nav_row.append({"text": "❌ ዝጋ", "callback_data": "pg_close"})
    if page < total_pages:
        nav_row.append({"text": "Next ➡️", "callback_data": f"pg_{page + 1}"})

    return msg_text, {"inline_keyboard": [nav_row]}


# ── Admin Statistics ──────────────────────────────────────────────────────────

async def get_daily_stats(db) -> str:
    try:
        now          = datetime.now()
        last_24h     = now - timedelta(hours=24)
        new_users    = await db.users.count_documents({"joined_at":   {"$gte": last_24h}})
        active_users = await db.users.count_documents({"last_active": {"$gte": last_24h}})
        total_users  = await db.users.count_documents({})
        total_files  = await db.files.count_documents({})
        return (
            "📅 **Daily Statistics**\n\n"
            f"🆕 New: `{new_users}`\n"
            f"⚡ Active: `{active_users}`\n"
            f"👥 Total: `{total_users}`\n"
            f"📂 Files: `{total_files}`"
        )
    except Exception:
        return "❌ Error fetching statistics."


# ── Force-Join Channel Management ────────────────────────────────────────────

async def get_force_channels(db) -> list[dict]:
    try:
        cursor = db.settings.find(
            {"type": "force_channel"},
            {"_id": 0, "username": 1, "url": 1},
        )
        return await cursor.to_list(length=20)
    except Exception:
        logger.exception("get_force_channels failed")
        return []


async def add_force_channel(db, username: str) -> bool:
    try:
        username = username.lstrip("@").strip()
        url      = f"https://t.me/{username}"
        result   = await db.settings.update_one(
            {"type": "force_channel", "username": username},
            {"$set": {"type": "force_channel", "username": username, "url": url}},
            upsert=True,
        )
        return result.upserted_id is not None
    except Exception:
        logger.exception("add_force_channel failed username=%s", username)
        return False


async def remove_force_channel(db, username: str) -> bool:
    try:
        username = username.lstrip("@").strip()
        result   = await db.settings.delete_one(
            {"type": "force_channel", "username": username}
        )
        return result.deleted_count > 0
    except Exception:
        logger.exception("remove_force_channel failed username=%s", username)
        return False


# ── Playlist: Building State ──────────────────────────────────────────────────

async def add_track_to_building_playlist(db, user_id: int, doc_id: str) -> int:
    try:
        user    = await db.users.find_one({"_id": int(user_id)}, {"building_playlist": 1})
        current = (user or {}).get("building_playlist", [])

        if doc_id in current:
            return -2  # duplicate
        if len(current) >= 10:
            return -1  # cap reached

        await db.users.update_one(
            {"_id": int(user_id)},
            {"$push": {"building_playlist": doc_id}},
        )
        return len(current) + 1
    except Exception:
        logger.exception("add_track_to_building_playlist failed user_id=%s", user_id)
        return -1


# ── Playlist: Persistence ─────────────────────────────────────────────────────

def _generate_playlist_id() -> str:
    return "pl_" + "".join(secrets.choice(_PL_ALPHABET) for _ in range(6))


async def create_playlist(db, creator_id: int, doc_ids: list[str]) -> str | None:
    tracks = []
    for doc_id in doc_ids:
        if len(doc_id) != 24:
            continue
        try:
            file_doc = await db.files.find_one(
                {"_id": ObjectId(doc_id)},
                {"file_id": 1, "display_name": 1},
            )
            if file_doc:
                tracks.append({
                    "file_id": file_doc["file_id"],
                    "name":    file_doc.get("display_name", "Unknown"),
                })
        except Exception:
            continue

    if not tracks:
        return None

    playlist_id = None
    for _ in range(5):
        candidate = _generate_playlist_id()
        if not await db.playlists.find_one({"_id": candidate}):
            playlist_id = candidate
            break

    if not playlist_id:
        return None

    await db.playlists.insert_one({
        "_id":        playlist_id,
        "creator_id": creator_id,
        "tracks":     tracks,
        "created_at": datetime.now(),
        "play_count": 0,
    })
    return playlist_id


async def get_playlist(db, playlist_id: str) -> dict | None:
    try:
        return await db.playlists.find_one({"_id": playlist_id})
    except Exception:
        logger.exception("get_playlist failed id=%s", playlist_id)
        return None


async def increment_playlist_plays(db, playlist_id: str) -> None:
    try:
        await db.playlists.update_one(
            {"_id": playlist_id},
            {"$inc": {"play_count": 1}},
        )
    except Exception:
        pass


