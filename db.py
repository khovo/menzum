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

async def track_user(db, user_id: int, username: str | None, first_name: str | None) -> None:
    """Inserts or updates the user document with basic Telegram profile info."""
    try:
        await db.users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "username":   username,
                    "first_name": first_name,
                    "last_seen":  datetime.now(),
                },
                "$setOnInsert": {
                    "created_at": datetime.now(),
                    "favorites":  [],
                }
            },
            upsert=True
        )
    except Exception:
        logger.exception("track_user failed id=%s", user_id)


async def track_and_get_user(db, user_id: int, username: str | None, first_name: str | None) -> dict:
    """
    Combined atomic check-in & fetch. Returns the user document.
    Ensures 'favorites' field exists and updates basic info in one round-trip.
    """
    try:
        user = await db.users.find_one_and_update(
            {"_id": user_id},
            {
                "$set": {
                    "username":   username,
                    "first_name": first_name,
                    "last_seen":  datetime.now(),
                },
                "$setOnInsert": {
                    "created_at": datetime.now(),
                    "favorites":  [],
                }
            },
            upsert=True,
            return_document=True
        )
        return user or {}
    except Exception:
        logger.exception("track_and_get_user failed id=%s", user_id)
        # Fallback to local doc if write fails to prevent bot crash
        return {"_id": user_id, "favorites": []}


async def save_last_menu_msg_id(db, user_id: int, message_id: int) -> None:
    """Store the message ID of the active interactive keyboard menu."""
    try:
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {"last_menu_msg_id": message_id}}
        )
    except Exception:
        logger.exception("save_last_menu_msg_id failed user=%s", user_id)


async def save_pending_start(db, user_id: int, start_param: str) -> None:
    """Persist start_param (deep-links) so users can proceed post channel join."""
    try:
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {"pending_start": start_param}}
        )
    except Exception:
        logger.exception("save_pending_start failed user=%s", user_id)


async def toggle_favorite(db, user_id: int, track_id_str: str) -> bool | None:
    """
    Toggles a track in user's favorites array.
    Returns True if added, False if removed, None if error or ID invalid.
    """
    try:
        track_oid = ObjectId(track_id_str)
    except Exception:
        logger.error("toggle_favorite invalid ObjectId format: %s", track_id_str)
        return None

    try:
        # Check if the file document actually exists
        exists = await db.files.find_one({"_id": track_oid}, {"_id": 1})
        if not exists:
            logger.warning("toggle_favorite track does not exist: %s", track_id_str)
            return None

        user = await db.users.find_one({"_id": user_id}, {"favorites": 1})
        favorites = user.get("favorites", []) if user else []

        if track_oid in favorites:
            # Pull (remove)
            await db.users.update_one(
                {"_id": user_id},
                {"$pull": {"favorites": track_oid}}
            )
            return False
        else:
            # Push (add)
            await db.users.update_one(
                {"_id": user_id},
                {"$addToSet": {"favorites": track_oid}}
            )
            return True
    except Exception:
        logger.exception("toggle_favorite failed user=%s track=%s", user_id, track_id_str)
        return None


async def get_user_data(db, user_id: int) -> dict | None:
    """Generic fetch for user document."""
    try:
        return await db.users.find_one({"_id": user_id})
    except Exception:
        logger.exception("get_user_data failed user=%s", user_id)
        return None


async def set_user_state(db, user_id: int, state_name: str | None) -> None:
    """Set or clear a custom behavioral string state on the user doc."""
    try:
        if state_name is None:
            await db.users.update_one({"_id": user_id}, {"$unset": {"state": ""}})
        else:
            await db.users.update_one({"_id": user_id}, {"$set": {"state": state_name}})
    except Exception:
        logger.exception("set_user_state failed user=%s state=%s", user_id, state_name)


# ── Catalog & Search ─────────────────────────────────────────────────────────

def build_search_query(query_text: str) -> dict:
    """
    Tokenizes query, converts to clean regex terms.
    Checks inside display_name. Supports multi-term spacing.
    """
    clean = re.sub(r'[^\w\s-]', '', query_text).strip()
    if not clean:
        return {}
    tokens = clean.split()
    regex_parts = [f"(?=.*{re.escape(t)})" for t in tokens]
    pattern = "^" + "".join(regex_parts) + ".*$"
    return {
        "file_type": "audio",
        "display_name": {"$regex": pattern, "$options": "i"}
    }


async def get_fuzzy_suggestions(db, query_text: str) -> list:
    """
    Fallback fuzzy matcher using regex on word boundaries
    when direct exact query returns zero documents.
    """
    clean = re.sub(r'[^\w\s-]', '', query_text).strip()
    if not clean:
        return []
    tokens = clean.split()
    # Try match starting with any token
    patterns = []
    for t in tokens:
        patterns.append({"display_name": {"$regex": rf"\b{re.escape(t)}", "$options": "i"}})
    
    if not patterns:
        return []

    try:
        cursor = db.files.find(
            {"file_type": "audio", "$or": patterns},
            {"display_name": 1}
        ).limit(5)
        results = await cursor.to_list(length=5)
        return [r["display_name"] for r in results]
    except Exception:
        logger.exception("get_fuzzy_suggestions failed query=%s", query_text)
        return []


async def get_catalog_page(db, page: int) -> tuple[list, int]:
    """
    Paginated catalog lookup.
    Returns: (list of track docs, total track count)
    """
    if page < 1:
        page = 1
    skip = (page - 1) * ITEMS_PER_PAGE
    try:
        total = await db.files.count_documents({"file_type": "audio"})
        cursor = db.files.find(
            {"file_type": "audio"},
            {"_id": 1, "display_name": 1, "file_size": 1}
        ).sort("display_name", 1).skip(skip).limit(ITEMS_PER_PAGE)
        tracks = await cursor.to_list(length=ITEMS_PER_PAGE)
        return tracks, total
    except Exception:
        logger.exception("get_catalog_page failed page=%s", page)
        return [], 0


# ── Statistics & Broadcast ───────────────────────────────────────────────────

async def get_daily_stats(db) -> tuple[int, int]:
    """Calculate counts of registered users and audio catalog files."""
    try:
        user_count = await db.users.count_documents({})
        file_count = await db.files.count_documents({"file_type": "audio"})
        return user_count, file_count
    except Exception:
        logger.exception("get_daily_stats failed")
        return 0, 0


# ── Force Join Gates ─────────────────────────────────────────────────────────

async def get_force_channels(db) -> list:
    """Retrieve all channels marked for force-joining."""
    try:
        cursor = db.config.find({"_id": {"$regex": "^fj_"}})
        channels = await cursor.to_list(length=10)
        return [
            {"channel_id": c["channel_id"], "title": c.get("title", c["channel_id"])}
            for c in channels
        ]
    except Exception:
        logger.exception("get_force_channels failed")
        return []


async def add_force_channel(db, channel_id: str, title: str) -> bool:
    """Add a channel to force join list. Key prefix prevents collision."""
    try:
        clean_id = channel_id.strip()
        if not clean_id.startswith("@") and not clean_id.startswith("-100"):
            # Normalize to username target
            clean_id = f"@{clean_id}"
        await db.config.update_one(
            {"_id": f"fj_{clean_id}"},
            {"$set": {"channel_id": clean_id, "title": title}},
            upsert=True
        )
        return True
    except Exception:
        logger.exception("add_force_channel failed ch=%s", channel_id)
        return False


async def remove_force_channel(db, channel_id: str) -> bool:
    """Remove a channel from force join list by direct ID or prefixed key."""
    try:
        clean_id = channel_id.strip()
        if not clean_id.startswith("@") and not clean_id.startswith("-100"):
            clean_id = f"@{clean_id}"
        res = await db.config.delete_one({"_id": f"fj_{clean_id}"})
        if res.deleted_count == 0:
            # Try direct fallback
            res = await db.config.delete_one({"channel_id": clean_id})
        return res.deleted_count > 0
    except Exception:
        logger.exception("remove_force_channel failed ch=%s", channel_id)
        return False


# ── Playlists & Sharing ───────────────────────────────────────────────────────

def _generate_playlist_id() -> str:
    """Generates a safe 8-char base-62 token prefixed with pl_"""
    token = "".join(secrets.choice(_PL_ALPHABET) for _ in range(8))
    return f"pl_{token}"


async def add_track_to_building_playlist(db, user_id: int, track_id_str: str) -> int:
    """
    Atomic check-then-push into user's active playlist-builder array.
    Returns:
      >= 0 : New playlist size
       -1  : Limit of 10 tracks reached
       -2  : Track already inside playlist
       -3  : Database or formatting error
    """
    try:
        track_oid = ObjectId(track_id_str)
    except Exception:
        logger.error("playlist_builder invalid ObjectId format: %s", track_id_str)
        return -3

    try:
        user = await db.users.find_one({"_id": user_id}, {"building_playlist": 1})
        current = user.get("building_playlist", []) if user else []

        if len(current) >= 10:
            return -1
        if track_oid in current:
            return -2

        # Atomic append
        res = await db.users.find_one_and_update(
            {"_id": user_id},
            {"$addToSet": {"building_playlist": track_oid}},
            return_document=True
        )
        return len(res.get("building_playlist", []))
    except Exception:
        logger.exception("add_track_to_building_playlist failed user=%s track=%s", user_id, track_id_str)
        return -3


async def create_playlist(db, creator_id: int, doc_ids: list[ObjectId]) -> str | None:
    """
    Takes an array of ObjectIds, fetches their display_name + file_id,
    and creates a shareable playlist doc with a random collision-free ID.
    Returns the string ID (e.g., pl_AbCdEfGh) or None if empty/error.
    """
    if not doc_ids:
        return None

    tracks = []
    for oid in doc_ids:
        try:
            file_doc = await db.files.find_one(
                {"_id": oid, "file_type": "audio"},
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
            {"$inc": {"play_count": 1}}
        )
    except Exception:
        pass


# ── Advanced Admin Schema & Helpers ───────────────────────────────────────────

async def toggle_ban_user(db, user_id: int, status: bool) -> None:
    """Ban or unban a user by updating their document is_banned field."""
    try:
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {"is_banned": status}}
        )
    except Exception:
        logger.exception("toggle_ban_user failed for user=%s", user_id)


async def update_file_name(db, doc_id: str, new_name: str) -> bool:
    """Updates the display_name of a catalog file queryable by ObjectId or file_unique_id."""
    try:
        try:
            query = {"_id": ObjectId(doc_id)}
        except Exception:
            query = {"file_unique_id": doc_id}

        res = await db.files.update_one(query, {"$set": {"display_name": new_name}})
        return res.modified_count > 0
    except Exception:
        logger.exception("update_file_name failed doc=%s name=%s", doc_id, new_name)
        return False


async def delete_media_file(db, doc_id: str) -> bool:
    """Deletes a file document from the catalog collection by ObjectId or file_unique_id."""
    try:
        try:
            query = {"_id": ObjectId(doc_id)}
        except Exception:
            query = {"file_unique_id": doc_id}

        res = await db.files.delete_one(query)
        return res.deleted_count > 0
    except Exception:
        logger.exception("delete_media_file failed doc=%s", doc_id)
        return False


async def toggle_maintenance(db) -> bool:
    """Toggles global maintenance mode state safely inside config collection."""
    try:
        config = await db.config.find_one({"_id": "global_config"})
        current = config.get("maintenance_mode", False) if config else False
        new_status = not current
        await db.config.update_one(
            {"_id": "global_config"},
            {"$set": {"maintenance_mode": new_status}},
            upsert=True
        )
        return new_status
    except Exception:
        logger.exception("toggle_maintenance failed")
        return False


async def is_maintenance_active(db) -> bool:
    """Helper query returning active state of maintenance_mode."""
    try:
        config = await db.config.find_one({"_id": "global_config"})
        if config:
            return config.get("maintenance_mode", False)
        return False
    except Exception:
        logger.exception("is_maintenance_active failed")
        return False


async def manage_admin_role(db, user_id: int, status: bool) -> None:
    """Updates user document's role field to 'admin' or 'user'."""
    try:
        role = "admin" if status else "user"
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {"role": role}}
        )
    except Exception:
        logger.exception("manage_admin_role failed for user=%s status=%s", user_id, status)


async def generate_users_backup(db) -> str:
    """Retrieves all users and packages them into a cleanly formatted JSON dump."""
    import json
    try:
        users = await db.users.find().to_list(length=None)
        for u in users:
            if "created_at" in u and isinstance(u["created_at"], datetime):
                u["created_at"] = u["created_at"].isoformat()
            if "last_seen" in u and isinstance(u["last_seen"], datetime):
                u["last_seen"] = u["last_seen"].isoformat()
        return json.dumps(users, indent=2, default=str)
    except Exception:
        logger.exception("generate_users_backup failed")
        return "[]"

