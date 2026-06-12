"""
handlers/inline_handler.py
--------------------------
handle_inline_query() — inline-mode search, favorites (#favorites), and the
cached "latest 20" empty-query result set.
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
            for doc in docs:
                results.append({"type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"], "caption": f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", "reply_markup": {"inline_keyboard": [[{"text": "💔 Remove", "callback_data": f"fav_{str(doc['_id'])}"}]]}})
        else:
            results.append({"type": "article", "id": "no_favorites", "title": "No Favorites Yet", "input_message_content": {"message_text": "No favorites saved yet."}})
    elif not query:
        cached = get_inline_empty_cache()
        if cached is not None:
            await answer_inline_query(session, query_id, cached, cache_time=300)
            return
        docs = await db.files.find({"file_id": {"$exists": True}}, {"file_id": 1, "display_name": 1}).sort("_id", -1).limit(20).to_list(length=20)
        for doc in docs:
            results.append({"type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"], "caption": f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}})
        set_inline_empty_cache(results)
    else:
        sq   = build_search_query(query)
        docs = await db.files.find(sq, {"file_id": 1, "display_name": 1}).limit(20).to_list(length=20)
        for doc in docs:
            results.append({"type": "audio", "id": str(doc["_id"]), "audio_file_id": doc["file_id"], "caption": f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", "reply_markup": {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}})

    await answer_inline_query(session, query_id, results, cache_time=300)
