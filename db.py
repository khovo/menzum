"""
db.py
-----
All MongoDB Motor async operations.  If the database engine ever changes,
this is the ONLY file to touch.

CHANGES FROM v1:
  - Removed dead `bson.ObjectId` import (ObjectId handling lives in handlers.py).
  - Added force-join channel management: get / add / remove from `settings` collection.
  - Added get_fuzzy_suggestions(): broad OR-regex fallback search for smart suggestions.
"""
import re
import logging
from datetime import datetime, timedelta

from config import ITEMS_PER_PAGE

logger = logging.getLogger(__name__)


# ── User Tracking ─────────────────────────────────────────────────────────────

async def track_user(db, user_id: int, first_name: str) -> None:
    """
    Upsert a user document.
    $setOnInsert → joined_at written only on first insert (preserves origin timestamp).
    $set         → first_name and last_active always refreshed.
    Called at the top of ALL three handler paths (message / callback / inline)
    so every interaction is counted, not just /start.
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
    """Fetch full user document, or None if not found."""
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
    Strict AND-search used as the primary lookup.
    Single char → prefix match.  Multiple words → every word must appear.
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
    Broad OR-search used as a fallback when the strict AND-search finds nothing.
    Returns up to `limit` files whose display_name contains ANY word from the query.
    Single-character tokens are skipped to avoid massive result sets.

    Example: query "Muhammed Rashid" (misspelled) → AND-search misses →
             OR-search on ["Muhammed", "Rashid"] → finds "Muhammad Rashid" etc.
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
    """Return (message_text, inline_keyboard) for the requested catalog page."""
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
    """Return a Markdown stats summary for the admin panel."""
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
#
# Channels are stored as individual documents in the `settings` collection:
#   { "type": "force_channel", "username": "Al_madih", "url": "https://t.me/Al_madih" }
#
# Using one-doc-per-channel (rather than a single array doc) lets us use
# atomic $set / deleteOne without read-modify-write races.

async def get_force_channels(db) -> list[dict]:
    """
    Return all active force-join channels.
    Returns [] if none configured → bot runs in open-access mode.
    """
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
    """
    Add a channel to the force-join list.
    username: with or without leading @, e.g. "Al_madih" or "@Al_madih".
    Returns True if newly inserted, False if it already existed.
    """
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
    """Remove a channel from the force-join list. Returns True if deleted."""
    try:
        username = username.lstrip("@").strip()
        result   = await db.settings.delete_one(
            {"type": "force_channel", "username": username}
        )
        return result.deleted_count > 0
    except Exception:
        logger.exception("remove_force_channel failed username=%s", username)
        return False
