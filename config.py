"""
config.py
---------
Single source of truth for all environment variables and constants.

CHANGES FROM v1:
  - REMOVED FORCE_CHANNEL_USERNAME / FORCE_CHANNEL_URL.
    Force-join channels are now stored in MongoDB (settings collection)
    and managed dynamically via the Admin Panel. No redeploy needed to
    add or remove a channel.
  - Added CHANNELS_CACHE_TTL: how long the in-memory copy of the channel
    list stays valid before re-fetching from DB (keeps Mongo round-trips low
    while still reacting to channel changes within ~30 seconds).
"""
import os

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str | None = os.environ.get("BOT_TOKEN")
ADMIN_ID: str | None  = os.environ.get("ADMIN_ID")

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URL: str | None = os.environ.get("MONGO_URL")
DB_NAME = "MenzumaDB"

# ── Pagination ────────────────────────────────────────────────────────────────
ITEMS_PER_PAGE = 10

# ── In-Memory Cache TTLs (seconds) ───────────────────────────────────────────
MEMBERSHIP_CACHE_TTL   = 60   # per-user getChatMember result
INLINE_EMPTY_CACHE_TTL = 60   # latest-20 inline results for empty query
CHANNELS_CACHE_TTL     = 30   # force-join channel list from settings collection
