"""
config.py
---------
Single source of truth for all environment variables and constants.
Every other module imports from here — no magic strings elsewhere.
"""
import os

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str | None = os.environ.get("BOT_TOKEN")
ADMIN_ID: str | None  = os.environ.get("ADMIN_ID")

FORCE_CHANNEL_USERNAME = "Al_madih"
FORCE_CHANNEL_URL      = "https://t.me/Al_madih"

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URL: str | None = os.environ.get("MONGO_URL")
DB_NAME = "MenzumaDB"

# ── Pagination ────────────────────────────────────────────────────────────────
ITEMS_PER_PAGE = 10

# ── In-Memory Cache ───────────────────────────────────────────────────────────
# TTL in seconds for membership checks (avoids hammering Telegram's getChatMember)
MEMBERSHIP_CACHE_TTL = 60

# TTL in seconds for the empty-query inline results cache
INLINE_EMPTY_CACHE_TTL = 60
