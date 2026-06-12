"""
handlers/broadcast_engine.py
----------------------------
Al-Madih elite broadcast engine + Broadcast Markup Language (BML).

Holds:
  - _BML_TOKEN_RE / _BML_MACRO_RE — the BML grammar
  - _resolve_macro()  — expands macros like {trending:5} into inline buttons
  - _parse_bml()      — turns a BML string into a Telegram inline_keyboard
  - _bml_syntax_guide() — the admin-facing help text
  - _execute_broadcast() — chunked, throttled, circuit-breaking fan-out send

Imported by callback_handler (broadcast confirm/edit) and admin_handlers
(broadcast content/markup state machine).
"""
import asyncio
import re
import random
import logging
from datetime import datetime, timezone

from utils import copy_message

logger = logging.getLogger(__name__)

_BML_TOKEN_RE = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<type>url|app|cb|switch|switch_cur):(?P<value>[^)]*)\)"
)
_BML_MACRO_RE = re.compile(
    r"\{(?P<macro>latest_tracks|trending|latest_pdfs|random_track):?(?P<arg>\d*)\}"
)


async def _resolve_macro(db, macro: str, arg: str) -> list[dict]:
    n = max(1, min(int(arg), 8)) if arg.isdigit() else 3
    try:
        if macro == "latest_tracks":
            docs = await (
                db.files
                .find({"file_id": {"$exists": True}}, {"_id": 1, "display_name": 1})
                .sort("_id", -1)
                .limit(n)
                .to_list(length=n)
            )
            return [{"text": f"🎵 {doc.get('display_name', 'Track')[:40]}", "callback_data": f"play_{doc['_id']}"} for doc in docs]

        if macro == "trending":
            pipeline = [
                {"$match": {"listen_history": {"$exists": True, "$not": {"$size": 0}}}},
                {"$unwind": "$listen_history"},
                {"$match": {"listen_history.played_at": {"$gte": datetime(datetime.now(timezone.utc).year, datetime.now(timezone.utc).month, 1, tzinfo=timezone.utc)}}},
                {"$group": {"_id": "$listen_history.track_id", "plays": {"$sum": 1}, "name": {"$first": "$listen_history.name"}}},
                {"$sort": {"plays": -1}},
                {"$limit": n},
            ]
            cursor = db.users.aggregate(pipeline)
            docs   = await cursor.to_list(length=n)
            buttons = []
            for doc in docs:
                try:
                    file_doc = await db.files.find_one({"display_name": {"$regex": re.escape(doc.get("name", "")), "$options": "i"}}, {"_id": 1})
                    oid = str(file_doc["_id"]) if file_doc else doc["_id"]
                    buttons.append({"text": f"🔥 {doc.get('name', 'Track')[:38]} ({doc['plays']}▶)", "callback_data": f"play_{oid}"})
                except Exception:
                    continue
            return buttons

        if macro == "latest_pdfs":
            docs = await (
                db.pdfs
                .find({}, {"_id": 1, "title": 1})
                .sort("approved_at", -1)
                .limit(n)
                .to_list(length=n)
            )
            return [{"text": f"📄 {doc.get('title', 'PDF')[:40]}", "callback_data": f"pdf_dl_{doc['_id']}"} for doc in docs]

        if macro == "random_track":
            count = await db.files.count_documents({"file_id": {"$exists": True}})
            if count == 0: return []
            skip  = random.randint(0, max(0, count - 1))
            doc   = await db.files.find_one({"file_id": {"$exists": True}}, {"_id": 1, "display_name": 1}, skip=skip)
            if not doc: return []
            return [{"text": f"🎲 {doc.get('display_name', 'Discover')[:42]}", "callback_data": f"play_{doc['_id']}"}]

    except Exception as exc:
        logger.warning("_resolve_macro(%s) failed: %s", exc)
    return []


async def _parse_bml(db, bml_text: str) -> tuple[list[list[dict]] | None, list[str]]:
    keyboard: list[list[dict]] = []
    errors:   list[str]        = []
    for line_no, raw_line in enumerate(bml_text.strip().splitlines(), start=1):
        line = raw_line.strip()
        if not line: continue
        macro_match = _BML_MACRO_RE.fullmatch(line)
        if macro_match:
            macro, arg = macro_match.group("macro"), macro_match.group("arg")
            buttons = await _resolve_macro(db, macro, arg)
            if not buttons:
                errors.append(f"Line {line_no}: macro `{{{macro}}}` returned no results.")
                continue
            for btn in buttons: keyboard.append([btn])
            continue

        row: list[dict] = []
        for seg in [s.strip() for s in line.split("|")]:
            m = _BML_TOKEN_RE.fullmatch(seg)
            if not m:
                errors.append(f"Line {line_no}: could not parse `{seg[:60]}`. Expected format: [Label](type:value)")
                continue
            label, btype, value = m.group("label").strip(), m.group("type"), m.group("value").strip()

            if btype == "url":
                if not value.startswith(("http://", "https://", "tg://")): errors.append(f"Line {line_no}: URL must start with http/https/tg://")
                else: row.append({"text": label, "url": value})
            elif btype == "app":
                if not value.startswith(("http://", "https://")): errors.append(f"Line {line_no}: WebApp URL must start with http/https")
                else: row.append({"text": label, "web_app": {"url": value}})
            elif btype == "cb":
                if len(value.encode()) > 64: errors.append(f"Line {line_no}: callback_data exceeds 64 bytes.")
                else: row.append({"text": label, "callback_data": value})
            elif btype == "switch": row.append({"text": label, "switch_inline_query": value})
            elif btype == "switch_cur": row.append({"text": label, "switch_inline_query_current_chat": value})

        if row: keyboard.append(row)
    return (keyboard if keyboard else None), errors


def _bml_syntax_guide() -> str:
    return (
        "📋 *Broadcast Button Syntax (BML)*\n\n"
        "Each line = one keyboard row. Use `|` to put buttons side by side.\n\n"
        "*Button types:*\n"
        "`[Label](url:https://...)` — link\n"
        "`[Label](app:https://...)` — Mini App\n"
        "`[Label](cb:callback_data)` — callback\n"
        "`[Label](switch:query)` — inline search\n"
        "`[Label](switch_cur:query)` — inline search in this chat\n\n"
        "*Smart macros (one per line):*\n"
        "`{latest_tracks:3}` — 3 newest tracks\n"
        "`{trending:5}` — 5 most played this month\n"
        "`{latest_pdfs:3}` — 3 newest approved PDFs\n"
        "`{random_track}` — one surprise track\n\n"
        "*Example:*\n"
        "`[📖 Open App](app:https://almadih.vercel.app) | [📢 Channel](url:https://t.me/Al_madih)`\n"
        "`{trending:3}`\n"
        "`[🔀 Share](switch:)`\n\n"
        "Send your BML now, or send /skip for no buttons."
    )


async def _execute_broadcast(session, db, admin_chat_id: int, msg_id: int, markup: dict | None) -> str:
    total, failed, consecutive = 0, 0, 0
    CIRCUIT_BREAKER, CHUNK_SLEEP, CHUNK_SIZE = 10, 0.025, 25

    all_user_ids = []
    async for u in db.users.find({}, {"_id": 1}): all_user_ids.append(u["_id"])
    total_target = len(all_user_ids)

    for i, uid in enumerate(all_user_ids):
        if consecutive >= CIRCUIT_BREAKER:
            return f"⚠️ Broadcast aborted at {total}/{total_target} — {CIRCUIT_BREAKER} consecutive errors triggered circuit breaker.\n✅ Delivered: {total}  ❌ Failed: {failed}"
        try:
            result = await copy_message(session, uid, admin_chat_id, msg_id, reply_markup=markup)
            if result and result.get("ok") is False:
                err_code = result.get("error_code", 0)
                if err_code == 429:
                    retry_after = result.get("parameters", {}).get("retry_after", 5)
                    await asyncio.sleep(retry_after)
                    result2 = await copy_message(session, uid, admin_chat_id, msg_id, reply_markup=markup)
                    if result2 and result2.get("ok"):
                        total += 1; consecutive = 0
                    else:
                        failed += 1; consecutive += 1
                    continue
                if err_code in (400, 403):
                    failed += 1; consecutive = 0
                    continue
                failed += 1; consecutive += 1
            else:
                total += 1; consecutive = 0
        except Exception as exc:
            logger.warning("Broadcast send to %s failed: %s", exc)
            failed += 1; consecutive += 1

        if (i + 1) % CHUNK_SIZE == 0: await asyncio.sleep(CHUNK_SLEEP * CHUNK_SIZE)
        else: await asyncio.sleep(CHUNK_SLEEP)

    return f"✅ Broadcast complete.\n📤 Delivered: *{total}* / {total_target}\n❌ Failed / blocked: {failed}"
