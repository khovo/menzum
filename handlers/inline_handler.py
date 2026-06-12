"""
handlers/inline_handler.py
--------------------------
handle_inline_query() — inline-mode search, favorites (#favorites), and the
cached "latest 20" empty-query result set.

ROBUSTNESS NOTE (why _audio_result exists):
  answerInlineQuery is all-or-nothing — if a SINGLE result object is malformed
  (e.g. a track whose `file_id` is missing or null), Telegram silently rejects
  the ENTIRE response and the user sees zero results.  The previous code used
  direct `doc["file_id"]` access, which (a) raised KeyError on docs with no
  file_id (crashing the whole handler before it could answer), and (b) emitted
  `audio_file_id: null` for docs with a null file_id (poisoning the batch).
  _audio_result() builds a valid InlineQueryResultCachedAudio or returns None,
  and callers drop the None's — so one bad track can never blank out the rest.
"""
import logging

from db import track_and_get_user, build_search_query
from utils import (
    answer_inline_query,
    get_inline_empty_cache,
    set_inline_empty_cache,
)
from .helpers import BOT_USERNAME

logger = logging.getLogger(__name__)


def _audio_result(doc: dict, fav_text: str = "❤️ Fav") -> dict | None:
    """Build a valid InlineQueryResultCachedAudio, or None if the doc is missing
    a required field. Skipping invalid docs prevents Telegram from silently
    rejecting the whole answerInlineQuery batch."""
    file_id = doc.get("file_id")
    doc_id  = doc.get("_id")
    if not file_id or not doc_id:
        return None
    doc_id = str(doc_id)
    return {
        "type":          "audio",
        "id":            doc_id,
        "audio_file_id": file_id,
        "caption":       f"{doc.get('display_name', 'Unknown')}\n\n@{BOT_USERNAME}",
        "reply_markup":  {"inline_keyboard": [[{"text": fav_text, "callback_data": f"fav_{doc_id}"}]]},
    }


async def handle_inline_query(session, db, iq: dict, channels: list[dict]) -> None:
    query_id   = iq["id"]
    query      = iq.get("query", "").strip().lower()
    user_info  = iq.get("from", {})
    user_id    = user_info.get("id")
    first_name = user_info.get("first_name", "User")

    await track_and_get_user(db, user_id, first_name)
    results: list = []

    if query.startswith("#favorites"):
        user    = await db.users.find_one({"_id": int(user_id)}, {"favorites": 1})
        fav_ids = (user or {}).get("favorites", [])
        if fav_ids:
            docs = await db.files.find({"file_id": {"$in": fav_ids}}, {"file_id": 1, "display_name": 1}).limit(50).to_list(length=50)
            results = [r for r in (_audio_result(doc, "💔 Remove") for doc in docs) if r]
        if not results:
            results = [{"type": "article", "id": "no_favorites", "title": "No Favorites Yet", "input_message_content": {"message_text": "No favorites saved yet."}}]

    elif not query:
        cached = get_inline_empty_cache()
        if cached:
            await answer_inline_query(session, query_id, cached, cache_time=300)
            return
        docs = await db.files.find({"file_id": {"$exists": True}}, {"file_id": 1, "display_name": 1}).sort("_id", -1).limit(20).to_list(length=20)
        results = [r for r in (_audio_result(doc) for doc in docs) if r]
        if results:  # never cache an empty list — would not serve, and avoids poisoning
            set_inline_empty_cache(results)

    else:
        sq   = build_search_query(query)
        docs = await db.files.find(sq, {"file_id": 1, "display_name": 1}).limit(20).to_list(length=20)
        results = [r for r in (_audio_result(doc) for doc in docs) if r]

    resp = await answer_inline_query(session, query_id, results, cache_time=300)
    if isinstance(resp, dict) and resp.get("ok") is False:
        logger.warning("answerInlineQuery rejected id=%s: %s", query_id, resp.get("description"))
