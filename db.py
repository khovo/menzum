```python
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
import secrets
import string
import logging
from datetime import datetime, timedelta
from bson import ObjectId

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


# ── Lyrics ────────────────────────────────────────────────────────────────────

async def insert_lyrics(db, doc: dict) -> str | None:
    """
    Insert a pending lyrics submission.
    Returns the new ObjectId as a string, or None on failure.
    """
    try:
        result = await db.lyrics.insert_one(doc)
        return str(result.inserted_id)
    except Exception:
        logger.exception("insert_lyrics failed")
        return None


async def approve_lyrics(db, doc_id: str) -> dict | None:
    """
    Set status=approved on a lyrics doc.
    Returns the updated doc (used to read submitted_by, file_id, track_name).
    Uses findOneAndUpdate with return_document=True — single round-trip.
    """
    try:
        return await db.lyrics.find_one_and_update(
            {"_id": ObjectId(doc_id)},
            {"$set": {"status": "approved", "approved_at": datetime.now()}},
            return_document=True,
        )
    except Exception:
        logger.exception("approve_lyrics failed doc_id=%s", doc_id)
        return None


async def reject_lyrics(db, doc_id: str) -> dict | None:
    """
    Set status=rejected on a lyrics doc.
    Returns the updated doc (used to read submitted_by, track_name).
    """
    try:
        return await db.lyrics.find_one_and_update(
            {"_id": ObjectId(doc_id)},
            {"$set": {"status": "rejected"}},
            return_document=True,
        )
    except Exception:
        logger.exception("reject_lyrics failed doc_id=%s", doc_id)
        return None


async def set_file_has_lyrics(db, file_id: str, value: bool) -> None:
    """
    Write has_lyrics=True/False onto the files doc identified by Telegram file_id.
    Called immediately after approving or rejecting lyrics so that
    featured/search/library can do O(1) reads instead of a cross-collection check.
    Fire-and-forget — errors are logged but not re-raised.
    """
    try:
        await db.files.update_one(
            {"file_id": file_id},
            {"$set": {"has_lyrics": value}},
        )
    except Exception:
        logger.exception("set_file_has_lyrics failed file_id=%s", file_id)


async def has_pending_lyrics(db, file_id: str, user_id: int) -> bool:
    """
    Check whether this user already has a pending submission for this track.
    Used by the POST /api/webapp/lyrics route to block duplicate submissions.
    """
    try:
        doc = await db.lyrics.find_one(
            {"file_id": file_id, "submitted_by": user_id, "status": "pending"},
            {"_id": 1},
        )
        return doc is not None
    except Exception:
        logger.exception("has_pending_lyrics failed")
        return False


```
