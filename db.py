"""
db.py
-----
All MongoDB Motor async operations.

CHANGES FROM v2:
  - Added save_last_menu_msg_id(): stores the bot's last menu message_id in the
    user doc so handlers.py can delete it before sending a fresh menu (zero-clutter UI).
  - Added track_and_get_user(): merges track_user + get_user_data into a single
    findOneAndUpdate round-trip, cutting every message handler from 2 DB calls to 1.
  - Added save_pending_start(): persists the deep-link start param when a user
    hits the force-join gate, so check_subscription can resume delivery.
  - Added add_track_to_building_playlist(): atomic check-then-push for the playlist
    builder flow.  Returns the new track count, or -1 if already at the 10-track cap,
    or -2 if the track was already in the list.
  - Added create_playlist(): resolves doc_ids → file_id+name pairs, generates a
    unique "pl_{token}" ID, and persists to the `playlists` collection.
  - Added get_playlist(): fetches a playlist doc by its short ID.
  - Added increment_playlist_plays(): atomic counter bump on every delivery.
"""
import re
import asyncio
import secrets
import string
import logging
from datetime import datetime, timedelta
from bson import ObjectId
from bson.errors import InvalidId

from config import ITEMS_PER_PAGE

logger = logging.getLogger(__name__)

# Characters safe for Telegram deep-link start parameters
_PL_ALPHABET = string.ascii_letters + string.digits


# ── User Tracking ─────────────────────────────────────────────────────────────

async def track_user(db, user_id: int, first_name: str) -> None:
    """
    Upsert a user document.
    $setOnInsert → joined_at written only on first insert.
    $set         → first_name and last_active always refreshed.
    Called at the top of ALL three handler paths so every interaction is counted.
    """
    try:
        now = datetime.now()
        await db.users.update_one(
            {"_id": int(user_id)},
            {
                "$set":         {"first_name": first_name, "last_active": now},
                "$setOnInsert": {"joined_at": now},
            },
            upsert=True,
        )
    except Exception:
        logger.exception("track_user failed for user_id=%s", user_id)


async def track_and_get_user(db, user_id: int, first_name: str) -> dict:
    """
    PERFORMANCE: Replaces the previous two-call pattern of:
        await track_user(db, user_id, first_name)
        user_data = await get_user_data(db, user_id)

    Uses findOneAndUpdate with returnDocument=True so the upsert and the
    read are a single atomic MongoDB round-trip instead of two.

    Returns the full (post-update) user document — guaranteed non-None
    because upsert=True creates the doc if it does not exist.
    """
    try:
        now = datetime.now()
        doc = await db.users.find_one_and_update(
            {"_id": int(user_id)},
            {
                "$set":         {"first_name": first_name, "last_active": now},
                "$setOnInsert": {"joined_at": now},
            },
            upsert=True,
            return_document=True,   # motor: ReturnDocument.AFTER equivalent
        )
        return doc or {}
    except Exception:
        logger.exception("track_and_get_user failed for user_id=%s", user_id)
        return {}


async def save_pending_start(db, user_id: int, start_param: str | None) -> None:
    """
    Persist (or clear) the deep-link start parameter for a user who hit the
    force-join gate before being allowed through.

    When the user later taps "Verify", check_subscription reads this field,
    delivers the pending playlist, and clears the field.

    Pass start_param=None to clear the pending value after consumption.
    """
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
    """
    Persist the message_id of the most recently sent bot menu for this user.
    Used by the chat-cleanup logic: before sending a new /start or /list menu,
    handlers.py deletes the old one using this stored ID.
    Never raises — a failed write just means cleanup won't work for that one message.
    """
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
    """Toggle a file_id in the user's favorites list. Returns True if added."""
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
    """Persist conversational state (and optional metadata) for a user."""
    update = {"$set": {"state": state}}
    if meta:
        update["$set"].update(meta)
    await db.users.update_one({"_id": int(user_id)}, update, upsert=True)


# ── File Search ───────────────────────────────────────────────────────────────

def build_search_query(query_text: str) -> dict:
    """
    Strict AND-search.  Single char → prefix.  Multiple words → all must appear.
    """
    if not query_text:
        return {}
    query_text = query_text.strip()
    if len(query_text) == 1:
        return {"display_name": {"$regex": f"^{re.escape(query_text)}", "$options": "i"}}
    words      = query_text.split()
    conditions = [{"display_name": {"$regex": re.escape(w), "$options": "i"}} for w in words]
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


async def get_fuzzy_suggestions(db, query_text: str, limit: int = 5) -> list[dict]:
    """
    Broad OR-search fallback when AND-search finds nothing.
    Returns docs whose display_name contains ANY word from the query.
    """
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
    """
    Append a track (by MongoDB doc_id string) to the user's in-progress playlist.

    Returns:
      new count (1–10)  → successfully added
      -1                → cap reached (already 10 tracks)
      -2                → track already in the list (duplicate)

    Uses a read-then-write pattern which is safe here because:
      - Max 10 items, so reads are tiny
      - Only one session per user (bot is 1:1 chat)
    """
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
    """Return a unique-enough 6-char alphanumeric token prefixed with 'pl_'."""
    return "pl_" + "".join(secrets.choice(_PL_ALPHABET) for _ in range(6))


async def create_playlist(db, creator_id: int, doc_ids: list[str]) -> str | None:
    """
    Resolve a list of file-doc ObjectId strings → track dicts, persist to `playlists`.

    Returns the new playlist_id (e.g. "pl_xY7k9z"), or None if no valid tracks found.

    Collision handling: retries ID generation up to 5 times (statistically negligible
    collision probability with 62^6 ≈ 56 billion possibilities).
    """
    # Resolve doc_ids → track objects
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

    # Generate a collision-free ID
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
    """Fetch a playlist document by its short ID. Returns None if not found."""
    try:
        return await db.playlists.find_one({"_id": playlist_id})
    except Exception:
        logger.exception("get_playlist failed id=%s", playlist_id)
        return None


async def increment_playlist_plays(db, playlist_id: str) -> None:
    """Bump the play counter. Fire-and-forget — errors are silently ignored."""
    try:
        await db.playlists.update_one(
            {"_id": playlist_id},
            {"$inc": {"play_count": 1}},
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  CHANGES FROM v3 — Advanced admin commands
#  Added multi-admin (admins), audio/pdf management, user/ban management
#  (banned_users), maintenance toggle (settings), db stats, and user export.
#  Every helper takes `db` first and never raises — logs + returns a safe default.
# ─────────────────────────────────────────────────────────────────────────────

# ── Multi-Admin Management (admins collection) ────────────────────────────────

async def add_admin(db, user_id: int, display_name: str, added_by: int) -> bool:
    """Upsert a co-admin. added_at is written only on first insert."""
    try:
        await db.admins.update_one(
            {"_id": int(user_id)},
            {
                "$set":         {"display_name": display_name, "added_by": int(added_by)},
                "$setOnInsert": {"added_at": datetime.now()},
            },
            upsert=True,
        )
        return True
    except Exception:
        logger.exception("add_admin failed user_id=%s", user_id)
        return False


async def remove_admin(db, user_id: int) -> bool:
    try:
        res = await db.admins.delete_one({"_id": int(user_id)})
        return res.deleted_count > 0
    except Exception:
        logger.exception("remove_admin failed user_id=%s", user_id)
        return False


async def list_admins(db) -> list[dict]:
    try:
        return await db.admins.find({}).to_list(length=200)
    except Exception:
        logger.exception("list_admins failed")
        return []


async def is_co_admin(db, user_id: int) -> bool:
    try:
        return await db.admins.find_one({"_id": int(user_id)}, {"_id": 1}) is not None
    except Exception:
        return False


# ── Audio Management (files collection) ───────────────────────────────────────

async def rename_audio(db, file_id: str, new_title: str) -> bool:
    """Set display_name for the track whose file_id matches. True if a doc matched."""
    try:
        res = await db.files.update_one({"file_id": file_id}, {"$set": {"display_name": new_title}})
        return res.matched_count > 0
    except Exception:
        logger.exception("rename_audio failed")
        return False


async def get_audio_by_file_id(db, file_id: str) -> dict | None:
    try:
        return await db.files.find_one({"file_id": file_id}, {"file_id": 1, "display_name": 1})
    except Exception:
        return None


async def delete_audio_by_id(db, doc_id: str) -> str | None:
    """Delete a track by its Mongo _id. Returns its display_name if deleted, else None."""
    try:
        oid = ObjectId(doc_id)
    except (InvalidId, Exception):
        return None
    try:
        doc = await db.files.find_one({"_id": oid}, {"display_name": 1})
        if not doc:
            return None
        await db.files.delete_one({"_id": oid})
        return doc.get("display_name", "Unknown")
    except Exception:
        logger.exception("delete_audio_by_id failed doc_id=%s", doc_id)
        return None


async def find_audio(db, term: str, limit: int = 5) -> list[dict]:
    """AND-regex search on display_name (reuses build_search_query)."""
    try:
        query = build_search_query(term)
        return await db.files.find(query, {"file_id": 1, "display_name": 1}).limit(limit).to_list(length=limit)
    except Exception:
        logger.exception("find_audio failed")
        return []


# ── PDF Management (pdfs collection) ──────────────────────────────────────────

async def find_pdf(db, identifier: str) -> dict | None:
    """Resolve a PDF by 24-char ObjectId, else by case-insensitive partial title."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    try:
        if len(identifier) == 24:
            try:
                doc = await db.pdfs.find_one({"_id": ObjectId(identifier)})
                if doc:
                    return doc
            except InvalidId:
                pass
        return await db.pdfs.find_one({"title": {"$regex": re.escape(identifier), "$options": "i"}})
    except Exception:
        logger.exception("find_pdf failed identifier=%s", identifier)
        return None


async def rename_pdf(db, object_id: str, new_title: str) -> bool:
    try:
        res = await db.pdfs.update_one({"_id": ObjectId(object_id)}, {"$set": {"title": new_title}})
        return res.matched_count > 0
    except Exception:
        logger.exception("rename_pdf failed object_id=%s", object_id)
        return False


async def delete_pdf_by_id(db, object_id: str) -> str | None:
    """Delete a PDF by its _id. Returns its title if deleted, else None."""
    try:
        oid = ObjectId(object_id)
    except (InvalidId, Exception):
        return None
    try:
        doc = await db.pdfs.find_one({"_id": oid}, {"title": 1})
        if not doc:
            return None
        await db.pdfs.delete_one({"_id": oid})
        return doc.get("title", "Untitled")
    except Exception:
        logger.exception("delete_pdf_by_id failed object_id=%s", object_id)
        return None


async def list_pdfs(db, limit: int = 200) -> list[dict]:
    try:
        return await db.pdfs.find({}, {"title": 1, "download_count": 1}).sort("_id", -1).to_list(length=limit)
    except Exception:
        logger.exception("list_pdfs failed")
        return []


# ── User / Ban Management (banned_users collection) ───────────────────────────

async def ban_user(db, user_id: int, reason: str, banned_by: int) -> bool:
    try:
        await db.banned_users.update_one(
            {"_id": int(user_id)},
            {
                "$set":         {"reason": reason, "banned_by": int(banned_by)},
                "$setOnInsert": {"banned_at": datetime.now()},
            },
            upsert=True,
        )
        return True
    except Exception:
        logger.exception("ban_user failed user_id=%s", user_id)
        return False


async def unban_user(db, user_id: int) -> bool:
    try:
        res = await db.banned_users.delete_one({"_id": int(user_id)})
        return res.deleted_count > 0
    except Exception:
        logger.exception("unban_user failed user_id=%s", user_id)
        return False


async def is_banned(db, user_id: int) -> bool:
    try:
        return await db.banned_users.find_one({"_id": int(user_id)}, {"_id": 1}) is not None
    except Exception:
        return False


async def list_banned(db, limit: int = 200) -> list[dict]:
    try:
        return await db.banned_users.find({}).to_list(length=limit)
    except Exception:
        logger.exception("list_banned failed")
        return []


# ── Bot Control: Maintenance (settings collection) ────────────────────────────

async def set_maintenance(db, is_on: bool) -> None:
    try:
        await db.settings.update_one(
            {"type": "maintenance"},
            {"$set": {"type": "maintenance", "is_on": bool(is_on)}},
            upsert=True,
        )
    except Exception:
        logger.exception("set_maintenance failed")


async def get_maintenance(db) -> bool:
    try:
        doc = await db.settings.find_one({"type": "maintenance"}, {"is_on": 1})
        return bool(doc.get("is_on")) if doc else False
    except Exception:
        return False


# ── Database Statistics & Export ──────────────────────────────────────────────

async def get_db_stats(db) -> dict:
    """Parallel countDocuments across every collection."""
    try:
        users, files, pdfs, playlists, banned, admins = await asyncio.gather(
            db.users.count_documents({}),
            db.files.count_documents({}),
            db.pdfs.count_documents({}),
            db.playlists.count_documents({}),
            db.banned_users.count_documents({}),
            db.admins.count_documents({}),
        )
        return {
            "users": users, "files": files, "pdfs": pdfs,
            "playlists": playlists, "banned": banned, "admins": admins,
        }
    except Exception:
        logger.exception("get_db_stats failed")
        return {}


async def get_all_users_for_export(db) -> list[dict]:
    """All user docs with just the fields needed for the export file."""
    try:
        return await db.users.find(
            {},
            {"first_name": 1, "joined_at": 1, "last_active": 1, "total_plays": 1, "favorites": 1, "state": 1},
        ).to_list(length=None)
    except Exception:
        logger.exception("get_all_users_for_export failed")
        return []
