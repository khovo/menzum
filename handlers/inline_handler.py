"""
handlers/inline_handler.py
--------------------------
handle_inline_query() — inline-mode search, favorites (#favorites), and the
cached "latest 20" empty-query result set.

WHY ARTICLE RESULTS (not InlineQueryResultCachedAudio):
  Telegram rejects an entire answerInlineQuery batch with "Bad Request:
  ...AUDIO_TITLE_EMPTY" when a cached-audio result points at a file whose audio
  metadata has no title — and InlineQueryResultCachedAudio has no `title` field
  we can set (the title is read from the file). Many tracks here (and anything
  ingested from voice notes) have no embedded title, so the whole inline
  response was being discarded and the user saw nothing.

  Instead we return InlineQueryResultArticle, whose `title` we control (the
  track's display_name → never empty). Selecting a result posts a small message
  with a ▶ Play button (callback_data play_<id>); tapping it delivers the actual
  audio via the bot's existing play_ handler. This is reliable regardless of the
  file's metadata.
"""
import os
import logging

from db import track_and_get_user, build_search_query, is_banned, get_maintenance
from utils import (
    answer_inline_query,
    get_inline_empty_cache,
    set_inline_empty_cache,
)
from .helpers import BOT_USERNAME, is_admin

logger = logging.getLogger(__name__)

# Base URL of the bot project (which also serves the Node thumbnail proxy at
# /api/webapp/thumb). The proxy 302-redirects to the track's Telegram CDN cover
# image, or 404s when the track has no thumbnail. Override via API_BASE if the
# deployment domain changes.
_THUMB_BASE = os.environ.get("API_BASE", "https://menzum.vercel.app").rstrip("/")


def _track_result(doc: dict, secondary_text: str = "❤️ Fav") -> dict | None:
    """Build an InlineQueryResultArticle for a track, or None if the doc is
    missing a required field. The article's `title` is the track name (never
    empty) which sidesteps Telegram's AUDIO_TITLE_EMPTY rejection. Selecting it
    posts a message with a ▶ Play button that delivers the audio via the bot."""
    file_id = doc.get("file_id")
    doc_id  = doc.get("_id")
    if not file_id or not doc_id:
        return None
    doc_id = str(doc_id)
    name   = doc.get("display_name") or "Unknown"
    result = {
        "type":  "article",
        "id":    doc_id,
        "title": name,
        "description": "▶️ ለማጫወት ይንኩ",
        "input_message_content": {
            "message_text": f"🎵 {name}\n\n@{BOT_USERNAME}",
        },
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "▶️ Play / አጫውት", "callback_data": f"play_{doc_id}"},
                {"text": secondary_text,    "callback_data": f"fav_{doc_id}"},
            ]]
        },
    }
    # Show the track's cover image (via the Node thumbnail proxy) when one exists.
    if doc.get("thumb_file_id"):
        result["thumbnail_url"] = f"{_THUMB_BASE}/api/webapp/thumb?id={doc_id}"
    return result


async def handle_inline_query(session, db, iq: dict, channels: list[dict]) -> None:
    query_id   = iq["id"]
    query      = iq.get("query", "").strip().lower()
    user_info  = iq.get("from", {})
    user_id    = user_info.get("id")
    first_name = user_info.get("first_name", "User")

    await track_and_get_user(db, user_id, first_name)

    # Non-admins get no inline results while banned or during maintenance.
    if not await is_admin(db, user_id):
        if await is_banned(db, user_id) or await get_maintenance(db):
            await answer_inline_query(session, query_id, [], cache_time=5)
            return

    results: list = []

    if query.startswith("#favorites"):
        user    = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
        fav_ids = (user or {}).get("favorites", [])
        if fav_ids:
            docs = await db.files.find({"file_id": {"$in": fav_ids}}, {"file_id": 1, "display_name": 1, "thumb_file_id": 1}).limit(50).to_list(length=50)
            results = [r for r in (_track_result(doc, "💔 Remove") for doc in docs) if r]
        if not results:
            results = [{"type": "article", "id": "no_favorites", "title": "No Favorites Yet", "input_message_content": {"message_text": "No favorites saved yet."}}]

    elif not query:
        cached = get_inline_empty_cache()
        if cached:
            await answer_inline_query(session, query_id, cached, cache_time=300)
            return
        docs = await db.files.find({"file_id": {"$exists": True}}, {"file_id": 1, "display_name": 1, "thumb_file_id": 1}).sort("_id", -1).limit(20).to_list(length=20)
        results = [r for r in (_track_result(doc) for doc in docs) if r]
        if results:  # never cache an empty list — would not serve, and avoids poisoning
            set_inline_empty_cache(results)

    else:
        sq   = build_search_query(query)
        docs = await db.files.find(sq, {"file_id": 1, "display_name": 1, "thumb_file_id": 1}).limit(20).to_list(length=20)
        results = [r for r in (_track_result(doc) for doc in docs) if r]

    resp = await answer_inline_query(session, query_id, results, cache_time=300)
    if isinstance(resp, dict) and resp.get("ok") is False:
        logger.warning("answerInlineQuery rejected id=%s: %s", query_id, resp.get("description"))
