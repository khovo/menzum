"""
db.py
-----
All MongoDB Motor async operations live here.
If you ever swap the database engine, this is the ONLY file you touch.

BUG FIX — Statistics (30 vs 250 users):
  track_user() was previously only called on /start.  Users who sent their
  first message via inline query, direct search, or a callback (without ever
  pressing /start) were NEVER inserted into the users collection, so
  count_documents({}) under-reported massively.

  Fix:  track_user() is now called at the *top* of every interaction path
  inside handlers.py — message, callback, and inline query alike.
  The upsert logic itself ($setOnInsert for joined_at) is correct and
  idempotent, so calling it multiple times per user is safe.
"""
import re
import logging
from datetime import datetime, timedelta
from bson import ObjectId

from config import ITEMS_PER_PAGE

logger = logging.getLogger(__name__)


# ── User Tracking ─────────────────────────────────────────────────────────────

async def track_user(db, user_id: int, first_name: str) -> None:
    """
    Upsert a user document.

    - $setOnInsert  → joined_at is written ONLY on the very first insert,
                      preserving the original join timestamp on all subsequent calls.
    - $set          → first_name and last_active are always refreshed.

    The _id is stored as int throughout the codebase for consistency.
    """
    try:
        now = datetime.now()
        await db.users.update_one(
            {"_id": int(user_id)},
            {
                "$set": {"first_name": first_name, "last_active": now},
                "$setOnInsert": {"joined_at": now},
            },
            upsert=True,
        )
    except Exception:
        logger.exception("track_user failed for user_id=%s", user_id)


# ── Favorites ─────────────────────────────────────────────────────────────────

async def toggle_favorite(db, user_id: int, file_id: str) -> bool:
    """Toggle a file_id in the user's favorites list.  Returns True if added."""
    try:
        user = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
        target_id  = user["_id"] if user else int(user_id)
        favorites  = user.get("favorites", []) if user else []

        if file_id in favorites:
            await db.users.update_one(
                {"_id": target_id}, {"$pull": {"favorites": file_id}}
            )
            return False
        else:
            await db.users.update_one(
                {"_id": target_id}, {"$addToSet": {"favorites": file_id}}
            )
            return True
    except Exception:
        logger.exception("toggle_favorite failed")
        return False


# ── Generic User Read/Write ───────────────────────────────────────────────────

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
    Build a MongoDB query dict from free-form text.
    - Single character → prefix match (fast for Amharic first-letter lookups).
    - Multiple words   → $and of per-word regex (all words must appear in name).
    """
    if not query_text:
        return {}
    query_text = query_text.strip()
    if len(query_text) == 1:
        return {
            "display_name": {
                "$regex": f"^{re.escape(query_text)}",
                "$options": "i",
            }
        }
    words = query_text.split()
    conditions = [
        {"display_name": {"$regex": re.escape(w), "$options": "i"}} for w in words
    ]
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


# ── Catalog Pagination ────────────────────────────────────────────────────────

async def get_catalog_page(db, page: int) -> tuple[str, dict]:
    """
    Return (message_text, inline_keyboard) for the requested catalog page.
    Items are sorted newest-first (_id descending).
    """
    limit  = ITEMS_PER_PAGE
    skip   = (page - 1) * limit
    total  = await db.files.count_documents({"file_id": {"$exists": True}})
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
        clean = doc.get("display_name", "Unknown").replace("`", "")
        msg_text += f"{idx}. `{clean}`\n"
        idx += 1

    nav_row = []
    if page > 1:
        nav_row.append({"text": "⬅️ Back", "callback_data": f"pg_{page - 1}"})
    nav_row.append({"text": "❌ ዝጋ", "callback_data": "pg_close"})
    if page < total_pages:
        nav_row.append({"text": "Next ➡️", "callback_data": f"pg_{page + 1}"})

    keyboard = {"inline_keyboard": [nav_row]}
    return msg_text, keyboard


# ── Admin Statistics ──────────────────────────────────────────────────────────

async def get_daily_stats(db) -> str:
    """Return a Markdown-formatted stats summary for the admin panel."""
    try:
        now      = datetime.now()
        last_24h = now - timedelta(hours=24)
        new_users    = await db.users.count_documents({"joined_at":    {"$gte": last_24h}})
        active_users = await db.users.count_documents({"last_active":  {"$gte": last_24h}})
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
