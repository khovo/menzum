"""
handlers.py
-----------
Pure business logic.
"""
import asyncio
import logging
import os
import re
import random
import time
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient

from config import BOT_TOKEN, MONGO_URL, DB_NAME, ADMIN_ID
from db import (
    track_and_get_user,
    save_last_menu_msg_id,
    save_pending_start,
    toggle_favorite,
    get_user_data,
    set_user_state,
    build_search_query,
    get_fuzzy_suggestions,
    get_catalog_page,
    get_daily_stats,
    get_force_channels,
    add_force_channel,
    remove_force_channel,
    add_track_to_building_playlist,
    create_playlist,
    get_playlist,
    increment_playlist_plays,
)
from utils import (
    check_membership,
    invalidate_membership_cache,
    invalidate_all_membership_cache,
    get_channels_cache,
    set_channels_cache,
    invalidate_channels_cache,
    send_message,
    send_audio,
    send_media_group,
    edit_message_text,
    delete_message,
    answer_callback_query,
    answer_inline_query,
    copy_message,
    get_inline_empty_cache,
    set_inline_empty_cache,
    get_not_found_kb,
    get_fuzzy_suggestions_kb,
    get_playlist_fuzzy_kb,
    get_playlist_builder_kb,
    get_subscription_kb,
    get_channel_mgmt_kb,
)

logger = logging.getLogger(__name__)

BOT_USERNAME = os.environ.get("BOT_USERNAME", "Almadihbot")

WELCOME_TEXT = (
    "<tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji> አሰላሙ አለይኩም! ወደ Al-Madih ቦት እንኳን በደህና መጡ። <tg-emoji emoji-id=\"5769143090103193926\">🌙</tg-emoji>\n\n"
    "<tg-emoji emoji-id=\"5337110598926766115\">⭐️</tg-emoji> የሚፈልጉትን መንዙማ ወይም ነሺዳ ርዕስ አሁኑኑ ጽፈው ይላኩ። <tg-emoji emoji-id=\"5384110834068783570\">💬</tg-emoji>\n\n"
    "<tg-emoji emoji-id=\"5384111778961588478\">⚡️</tg-emoji> ፈልግ (Search)\n"
    "<tg-emoji emoji-id=\"5384485342332093352\">⚡️</tg-emoji> ማውጫ (Catalog)\n"
    "<tg-emoji emoji-id=\"4904882772637648609\">⏰</tg-emoji> ፕሌይሊስት (Playlist)\n"
    "<tg-emoji emoji-id=\"5116368680279606270\">♥️</tg-emoji> ተወዳጆች (Favorites)"
)

def _is_admin(user_id) -> bool:
    return str(user_id) == str(ADMIN_ID)

def _normalize_text(text: str) -> str:
    return text.replace("️", "").replace("︎", "")

_ADMIN_KB_TEXTS = {
    "📊 Statistics",
    "📅 Daily Stats",
    "📢 Broadcast",
    "📂 Total Files",
    "🔧 Manage Channels",
}

# ─────────────────────────────────────────────────────────────────────────────
#  CUSTOM LOCAL HELPERS FOR HTML TEXT & REACTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _get_main_menu_kb_local() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "🌐 Open Al-Madih", "web_app": {"url": "https://almadih.vercel.app/"}}],
            [
                {"text": "🔍 ፈልግ (Search)", "switch_inline_query_current_chat": ""},
                {"text": "📂 ማውጫ (Catalog)", "callback_data": "pg_1"},
            ],
            [
                {"text": "🎧 ፕሌይሊስት (Playlist)", "callback_data": "pl_start"},
                {"text": "❤️ ተወዳጆች (Favorites)", "switch_inline_query_current_chat": "#favorites"},
            ]
        ]
    }

async def _send_html_message(session, chat_id, text: str, reply_markup=None) -> dict | None:
    if not BOT_TOKEN: return None
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload) as resp:
            return await resp.json()
    except Exception:
        return None

async def _edit_html_message(session, chat_id, message_id: int, text: str, reply_markup=None) -> dict | None:
    if not BOT_TOKEN: return None
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        async with session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json=payload) as resp:
            return await resp.json()
    except Exception:
        return None

async def _react_to_message(session, chat_id: int, message_id: int, emoji: str):
    if not BOT_TOKEN: return
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}]
    }
    try:
        async with session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction", json=payload) as resp:
            await resp.read()
    except Exception as e:
        print(f"Failed to set reaction: {e}")


async def _channel_mgmt_menu_text(db) -> str:
    channels = await get_force_channels(db)
    text = "📢 *Channel Management*\n\n"
    if channels:
        text += "\n".join(f"• `@{ch['username']}`" for ch in channels) + "\n"
    else:
        text += "No channels configured. Bot is in open access mode.\n"
    return text + "\nWhat would you like to do?"

# ─────────────────────────────────────────────────────────────────────────────
#  AL-MADIH ELITE BROADCAST ENGINE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────────────────────

async def _send_menu(session, db, chat_id, user_id: int, user_data: dict | None) -> None:
    result  = await _send_html_message(session, chat_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
    if result and result.get("ok"):
        await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])

async def _deliver_playlist(session, db, chat_id, playlist: dict) -> None:
    tracks = playlist.get("tracks", [])
    if not tracks:
        await send_message(session, chat_id, "⚠️ ፕሌይሊስቱ ባዶ ነው! ቢያንስ አንድ መንዙማ ያክሉ።")
        return

    playlist_id = playlist["_id"]
    creator_id  = playlist.get("creator_id", "")

    if len(tracks) == 1:
        t  = tracks[0]
        kb = {"inline_keyboard": [[{"text": "❤️ Fav", "switch_inline_query_current_chat": t["name"][:30]}]]}
        res = await send_audio(
            session, chat_id, t["file_id"],
            f"🎵 {t['name']}\n\n📋 Playlist by user {creator_id}\n@{BOT_USERNAME}",
            reply_markup=kb,
        )
        if res and res.get("ok"):
            await _react_to_message(session, chat_id, res["result"]["message_id"], "🥰")
    else:
        media = []
        for i, t in enumerate(tracks):
            item = {"type": "audio", "media": t["file_id"]}
            if i == 0:
                item["caption"]    = (
                    f"🎧 *Playlist* — {len(tracks)} tracks\n"
                    f"📋 Shared via @{BOT_USERNAME}"
                )
                item["parse_mode"] = "Markdown"
            media.append(item)
        res = await send_media_group(session, chat_id, media)
        if res and res.get("ok") and isinstance(res.get("result"), list) and len(res["result"]) > 0:
            await _react_to_message(session, chat_id, res["result"][0]["message_id"], "🥰")

    await increment_playlist_plays(db, playlist_id)

async def handle_callback(session, db, cb: dict, channels: list[dict]) -> None:
    user       = cb["from"]
    user_id    = user["id"]
    cb_id      = cb["id"]
    data_str   = cb.get("data", "")
    chat_id    = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    first_name = user.get("first_name", "User")

    user_data  = await track_and_get_user(db, user_id, first_name)

    # ── Hook & Lock: Enforce join ONLY when trying to play audio or download PDF ──
    if data_str.startswith("play_") or data_str.startswith("pdf_dl_"):
        if not _is_admin(user_id) and not await check_membership(session, user_id, channels):
            await answer_callback_query(session, cb_id, "⚠️ እባክዎ መጀመሪያ ቻናሉን ይቀላቀሉ!", show_alert=True)
            await send_message(
                session, chat_id,
                "የፈለጉት መንዙማ ወይም PDF ፋይል ለማግኘት በመጀመሪያ ስለ ቦቱ አጠቃቀም መረጃ ሚለቀቅበት channel ይቀላቀሉ!",
                reply_markup=get_subscription_kb(channels)
            )
            return

    if data_str != "check_subscription" and not _is_admin(user_id):
        # We bypass global gatekeeper here, we only gatekeep specific actions like playback
        pass

    if data_str == "check_subscription":
        invalidate_membership_cache(user_id)
        if await check_membership(session, user_id, channels):
            await answer_callback_query(session, cb_id, "✅ እንኳን ደህና መጡ!")
            pending = user_data.get("pending_start")
            if pending and pending.startswith("pl_"):
                await save_pending_start(db, user_id, None)
                playlist = await get_playlist(db, pending)
                if playlist:
                    await edit_message_text(
                        session, chat_id, message_id,
                        f"🎧 *Playing playlist* `{pending}` — {len(playlist.get('tracks', []))} tracks\n\n@{BOT_USERNAME}",
                    )
                    await _deliver_playlist(session, db, chat_id, playlist)
                    result = await _send_html_message(session, chat_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
                    if result and result.get("ok"):
                        await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
                    return
            await _edit_html_message(session, chat_id, message_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
        else:
            await answer_callback_query(session, cb_id, "❌ አሁንም አልተቀላቀሉም! ቻናሉን Join ይበሉ", show_alert=True)
        return

    if data_str == "pl_start":
        await set_user_state(db, user_id, "playlist_builder", {"building_playlist": [], "pl_ctrl_msg_id": message_id})
        await edit_message_text(
            session, chat_id, message_id,
            "🎧 *የፕሌይሊስት ማዘጋጃ (Playlist Builder)* — 0/10\n\nየመንዙማውን ስም ይፈልጉ እና ➕ የሚለውን በመጫን ወደ ስብስብዎ ያክሉ።\n\n_እስከ 10 መንዙማ መምረጥ ይችላሉ። ሲጨርሱ ✅ Save የሚለውን ይጫኑ።_",
            reply_markup=get_playlist_builder_kb(0),
        )
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("pl_add_"):
        doc_id = data_str.split("pl_add_")[1]
        count  = await add_track_to_building_playlist(db, user_id, doc_id)
        if count == -2:
            await answer_callback_query(session, cb_id, "⚠️ Already in playlist!", show_alert=False)
            return
        if count == -1:
            await answer_callback_query(session, cb_id, "🎵 ከ 10 በላይ መንዙማ መጨመር አይቻልም!", show_alert=True)
            return

        await answer_callback_query(session, cb_id, f"➕ Added! ({count}/10)")
        user_data = await get_user_data(db, user_id)
        ctrl_msg_id = (user_data or {}).get("pl_ctrl_msg_id")
        if ctrl_msg_id:
            await edit_message_text(
                session, chat_id, ctrl_msg_id,
                f"🎧 *የፕሌይሊስት ማዘጋጃ (Playlist Builder)* — {count}/10\n\nየመንዙማውን ስም ይፈልጉ እና ➕ የሚለውን በመጫን ወደ ስብስብዎ ያክሉ።\n\n_እስከ 10 መንዙማ መምረጥ ይችላሉ። ሲጨርሱ ✅ Save የሚለውን ይጫኑ።_",
                reply_markup=get_playlist_builder_kb(count),
            )
        return

    if data_str == "pl_done":
        user_data   = await get_user_data(db, user_id)
        doc_ids     = (user_data or {}).get("building_playlist", [])
        if not doc_ids:
            await answer_callback_query(session, cb_id, "⚠️ ቢያንስ አንድ መንዙማ ያክሉ!", show_alert=True)
            return

        await answer_callback_query(session, cb_id, "⏳ Saving playlist...")
        playlist_id = await create_playlist(db, user_id, doc_ids)
        await set_user_state(db, user_id, "idle", {"building_playlist": [], "pl_ctrl_msg_id": None})

        if not playlist_id:
            await _edit_html_message(session, chat_id, message_id, "❌ Failed to save playlist.", reply_markup=_get_main_menu_kb_local())
            return

        deep_link = f"https://t.me/{BOT_USERNAME}?start={playlist_id}"
        share_text = f"✅ *Playlist Saved!*\n\n🔗 *Share this link:*\n`{deep_link}`\n\n_ይህን ሊንክ የሚጫን ማንኛውም ሰው ያዘጋጁትን Playlist ወዲያውኑ ማዳመጥ ይችላል!_"
        await edit_message_text(
            session, chat_id, message_id, share_text,
            reply_markup={"inline_keyboard": [[{"text": "🏠 Main Menu", "callback_data": "pg_close"}]]},
        )
        return

    if data_str == "pl_cancel":
        await set_user_state(db, user_id, "idle", {"building_playlist": [], "pl_ctrl_msg_id": None})
        await _edit_html_message(session, chat_id, message_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
        await answer_callback_query(session, cb_id, "❌ Playlist cancelled.")
        return

    if data_str.startswith("play_"):
        doc_id = data_str.split("play_")[1]
        try:
            file_doc = None
            if len(doc_id) == 24:
                try:
                    file_doc = await db.files.find_one(
                        {"_id": ObjectId(doc_id)},
                        {"file_id": 1, "display_name": 1},
                    )
                except InvalidId:
                    file_doc = None

            if file_doc and file_doc.get("file_id"):
                kb = {
                    "inline_keyboard": [
                        [{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{doc_id}"}],
                        [{"text": "❤️ Fav", "callback_data": f"fav_{doc_id}"}],
                    ]
                }
                res = await send_audio(
                    session, chat_id, file_doc.get("file_id"),
                    f"🎵 {file_doc.get('display_name', 'Unknown')}\n\n@{BOT_USERNAME}",
                    reply_markup=kb,
                )
                if res and res.get("ok"):
                    await _react_to_message(session, chat_id, res["result"]["message_id"], "🥰")
                await answer_callback_query(session, cb_id)
            else:
                await answer_callback_query(session, cb_id, "⚠️ File not found", show_alert=True)
        except Exception:
            logger.exception("play_ callback failed for doc_id=%s", doc_id)
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    if data_str.startswith("pdf_dl_"):
        pdf_id = data_str.replace("pdf_dl_", "")
        try:
            pdf_doc = await db.pdfs.find_one({"_id": ObjectId(pdf_id)})
            if pdf_doc and "file_id" in pdf_doc:
                bot_token = os.environ.get("BOT_TOKEN")
                url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                payload = {
                    "chat_id": chat_id,
                    "document": pdf_doc["file_id"],
                    "caption": f"📄 {pdf_doc.get('title', '')}\n\n✨ @{BOT_USERNAME}"
                }
                res_http = await session.post(url, json=payload)
                res_data = await res_http.json()
                if res_data and res_data.get("ok"):
                    await _react_to_message(session, chat_id, res_data["result"]["message_id"], "🥰")
                await db.pdfs.update_one({"_id": ObjectId(pdf_id)}, {"$inc": {"download_count": 1}})
            else:
                await answer_callback_query(session, cb_id, "❌ ይቅርታ፣ ፋይሉ አልተገኘም!", show_alert=True)
                return
        except Exception as e:
            logger.error(f"PDF DL Error: {e}")
        
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("pg_"):
        if data_str == "pg_close":
            await _edit_html_message(session, chat_id, message_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
        else:
            new_page = int(data_str.split("_")[1])
            text, kb = await get_catalog_page(db, new_page)
            await edit_message_text(session, chat_id, message_id, text, reply_markup=kb)
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("fav_"):
        doc_id = data_str.split("fav_")[1]
        try:
            file_doc = None
            if len(doc_id) == 24:
                try:
                    file_doc = await db.files.find_one(
                        {"_id": ObjectId(doc_id)},
                        {"_id": 1, "file_id": 1},
                    )
                except InvalidId:
                    file_doc = None

            if file_doc:
                added = await toggle_favorite(db, user_id, file_doc["file_id"])
                await answer_callback_query(session, cb_id, "❤️ Saved" if added else "💔 Removed")
            else:
                await answer_callback_query(session, cb_id, "⚠️ Missing")
        except Exception:
            logger.exception("fav_ callback failed for doc_id=%s", doc_id)
            await answer_callback_query(session, cb_id, "❌ Error")
        return

    if data_str.startswith("report_"):
        doc_id = data_str.split("report_")[1]
        try:
            file_doc = await db.files.find_one({"_id": ObjectId(doc_id)}, {"display_name": 1})
            if file_doc:
                await send_message(session, ADMIN_ID, f"🚨 Report: `{file_doc.get('display_name')}`\nID: `{doc_id}`")
                await answer_callback_query(session, cb_id, "✅ Reported!", show_alert=True)
        except Exception:
            pass
        return

    if data_str.startswith("broadcast_") and _is_admin(user_id):
        if data_str == "broadcast_confirm":
            admin_data = await get_user_data(db, user_id)
            msg_id_bc  = (admin_data or {}).get("broadcast_msg_id")
            markup_bc  = (admin_data or {}).get("broadcast_markup")
            
            if msg_id_bc:
                await set_user_state(db, user_id, "idle")
                await edit_message_text(session, chat_id, message_id, "🚀 *Broadcasting queued...* processing in background.")
                
                # Fetch all user IDs from the users collection
                all_users = await db.users.find({}, {"_id": 1}).to_list(length=None)
                recipient_ids = [u["_id"] for u in all_users]
                
                # Insert a new document into the broadcast_queue collection
                await db.broadcast_queue.insert_one({
                    "admin_chat_id": chat_id,
                    "msg_id": msg_id_bc,
                    "reply_markup": markup_bc,
                    "status": "pending",
                    "recipient_ids": recipient_ids,
                    "last_processed_index": 0,
                    "sent_count": 0,
                    "failed_count": 0,
                    "created_at": datetime.now(timezone.utc)
                })
                
                await send_message(session, chat_id, "✅ Broadcast queued successfully. It will be sent in the background.")

        elif data_str == "broadcast_cancel":
            await edit_message_text(session, chat_id, message_id, "❌ Broadcast cancelled.")
            await set_user_state(db, user_id, "idle")

        elif data_str == "broadcast_edit_markup":
            await set_user_state(db, user_id, "broadcast_markup_wait")
            await send_message(session, chat_id, _bml_syntax_guide())

        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("admin_ch_") and _is_admin(user_id):
        if data_str == "admin_ch_menu":
            text = await _channel_mgmt_menu_text(db)
            await edit_message_text(session, chat_id, message_id, text, reply_markup=get_channel_mgmt_kb())
            await answer_callback_query(session, cb_id)
            return

        if data_str == "admin_ch_add":
            await set_user_state(db, user_id, "admin_add_channel_wait")
            await edit_message_text(
                session, chat_id, message_id,
                "📢 *Add Force-Join Channel*\n\nSend the channel username _(without @)_.\nExample: `Al_madih`",
                reply_markup={"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "admin_ch_menu"}]]},
            )
            await answer_callback_query(session, cb_id)
            return

        if data_str == "admin_ch_list":
            ch_list = await get_force_channels(db)
            if not ch_list:
                await answer_callback_query(session, cb_id, "No channels configured yet!", show_alert=True)
                return
            remove_buttons = [[{"text": f"❌ @{ch['username']}", "callback_data": f"admin_ch_del_{ch['username']}"}] for ch in ch_list]
            remove_buttons.append([{"text": "🔙 Back", "callback_data": "admin_ch_menu"}])
            await edit_message_text(
                session, chat_id, message_id,
                "🗑 *Remove a Channel*\nTap a channel to delete it from the force-join list.",
                reply_markup={"inline_keyboard": remove_buttons},
            )
            await answer_callback_query(session, cb_id)
            return

        if data_str.startswith("admin_ch_del_"):
            username = data_str.split("admin_ch_del_")[1]
            deleted  = await remove_force_channel(db, username)
            invalidate_channels_cache()
            invalidate_all_membership_cache()
            await answer_callback_query(session, cb_id, f"✅ @{username} removed." if deleted else f"⚠️ @{username} not found.")
            ch_list = await get_force_channels(db)
            if ch_list:
                remove_buttons = [[{"text": f"❌ @{ch['username']}", "callback_data": f"admin_ch_del_{ch['username']}"}] for ch in ch_list]
                remove_buttons.append([{"text": "🔙 Back", "callback_data": "admin_ch_menu"}])
                await edit_message_text(
                    session, chat_id, message_id,
                    "🗑 *Remove a Channel*\nTap a channel to delete it.",
                    reply_markup={"inline_keyboard": remove_buttons},
                )
            else:
                await edit_message_text(session, chat_id, message_id, await _channel_mgmt_menu_text(db), reply_markup=get_channel_mgmt_kb())
            return

        if data_str == "admin_ch_close":
            await edit_message_text(session, chat_id, message_id, "✅ Channel management closed.")
            await answer_callback_query(session, cb_id)
            return

async def handle_message(session, db, message: dict, channels: list[dict]) -> None:
    chat_id    = message.get("chat", {}).get("id")
    user_info  = message.get("from", {})
    user_id    = user_info.get("id")
    text       = _normalize_text(message.get("text", ""))
    msg_id     = message.get("message_id")
    first_name = user_info.get("first_name", "User")

    user_data = await track_and_get_user(db, user_id, first_name)
    state     = user_data.get("state")

    if not _is_admin(user_id):
        if not await check_membership(session, user_id, channels):
            parts       = text.split(" ", 1) if text.startswith("/start") else []
            start_param = parts[1].strip() if len(parts) > 1 else None
            if start_param:
                await save_pending_start(db, user_id, start_param)
            await send_message(
                session, chat_id,
                "**⚠️ አሰላሙ አለይኩም! ቦቱን ለመጠቀም እባክዎ መጀመሪያ ቻናላችንን ይቀላቀሉ።**",
                reply_markup=get_subscription_kb(channels),
            )
            return

    if text and (text == "/start" or text.startswith("/start ")):
        await delete_message(session, chat_id, msg_id)
        old_menu_id = user_data.get("last_menu_msg_id")
        if old_menu_id:
            await delete_message(session, chat_id, old_menu_id)

        parts       = text.split(" ", 1)
        start_param = parts[1].strip() if len(parts) > 1 else None
        if start_param and start_param.startswith("pl_"):
            playlist = await get_playlist(db, start_param)
            if playlist:
                await send_message(session, chat_id, f"🎧 *Playing playlist* `{start_param}` — {len(playlist.get('tracks', []))} tracks\n\n@{BOT_USERNAME}")
                await _deliver_playlist(session, db, chat_id, playlist)
                result = await _send_html_message(session, chat_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
                if result and result.get("ok"):
                    await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
                return

        result = await _send_html_message(session, chat_id, WELCOME_TEXT, reply_markup=_get_main_menu_kb_local())
        if result and result.get("ok"):
            await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
        return

    if text in ("/list", "📂 Catalog (List)"):
        await delete_message(session, chat_id, msg_id)
        old_menu_id = (user_data or {}).get("last_menu_msg_id")
        if old_menu_id:
            await delete_message(session, chat_id, old_menu_id)
        msg_text, kb = await get_catalog_page(db, 1)
        result = await send_message(session, chat_id, msg_text, reply_markup=kb)
        if result and result.get("ok"):
            await save_last_menu_msg_id(db, user_id, result["result"]["message_id"])
        return

    if text == "🔧 Manage Channels" and _is_admin(user_id):
        mgmt_text = await _channel_mgmt_menu_text(db)
        result = await send_message(session, chat_id, mgmt_text, reply_markup=get_channel_mgmt_kb())
        if not result or result.get("ok") is not True:
            await send_message(session, chat_id, "API Error showing menu: " + str(result)[:200])
        return

    if state == "playlist_builder" and text and not text.startswith("/") and not (_is_admin(user_id) and text in _ADMIN_KB_TEXTS):
        await _react_to_message(session, chat_id, msg_id, "👀")
        sq  = build_search_query(text)
        doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})
        if doc:
            kb = {"inline_keyboard": [[{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{str(doc['_id'])}"}], [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}
            res = await send_audio(session, chat_id, doc["file_id"], f"{doc.get('display_name')}\n\n@{BOT_USERNAME}", reply_markup=kb)
            if res and res.get("ok"):
                await _react_to_message(session, chat_id, res["result"]["message_id"], "🥰")
        else:
            suggestions = await get_fuzzy_suggestions(db, text, limit=5)
            if suggestions:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ በቀጥታ አልተገኘም።\n\n_ወደ ፕሌይሊስትዎ ለመጨመር ➕ ይጫኑ፦_", reply_markup=get_playlist_fuzzy_kb(suggestions))
            else:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ አልተገኘም።\nእባክዎ የተለየ ቃል ጽፈው ይሞክሩ።", reply_markup=get_not_found_kb())
        return

    if _is_admin(user_id):
        if "document" in message:
            doc = message.get("document")
            fname = doc.get("file_name", "")
            
            if fname.lower().endswith((".pdf", ".txt", ".doc", ".docx", ".epub")):
                cap = message.get("caption", "").split("\n")[0].strip()
                import os
                clean_fname = os.path.splitext(fname)[0].strip()
                title = cap if cap else clean_fname
                
                try:
                    await db.pdfs.update_one(
                        {"title": {"$regex": re.escape(title), "$options": "i"}},
                        {"$set": {"file_id": doc["file_id"], "title": title, "download_count": 0}},
                        upsert=True,
                    )
                    await send_message(session, chat_id, f"✅ Document Saved to DB:\n📄 `{title}`")
                except Exception as db_err:
                    logger.error("db.pdfs.update_one failed: %s", db_err)
                    await send_message(session, chat_id, f"❌ DB error saving Document `{title}`. Please retry.")
                return

        if state == "admin_add_channel_wait":
            if text and not text.startswith("/"):
                username = text.lstrip("@").strip()
                added    = await add_force_channel(db, username)
                invalidate_channels_cache()
                invalidate_all_membership_cache()
                result_text = f"✅ `@{username}` added!" if added else f"⚠️ `@{username}` already exists."
                await send_message(
                    session, chat_id, result_text,
                    reply_markup={"inline_keyboard": [[{"text": "📢 Manage Channels", "callback_data": "admin_ch_menu"}]]},
                )
                await set_user_state(db, user_id, "idle")
            else:
                await send_message(session, chat_id, "⚠️ Please send a plain username, e.g. `Al_madih`.")
            return

        if state == "broadcast_wait" and text not in _ADMIN_KB_TEXTS and msg_id:
            await set_user_state(
                db, user_id, "broadcast_markup_wait",
                {"broadcast_msg_id": msg_id},
            )
            await send_message(session, chat_id, _bml_syntax_guide())
            return

        if state == "broadcast_markup_wait" and text not in _ADMIN_KB_TEXTS:
            admin_data = await get_user_data(db, user_id)
            bc_msg_id  = (admin_data or {}).get("broadcast_msg_id")

            if not bc_msg_id:
                await send_message(session, chat_id, "⚠️ Session lost. Please start over with 📢 Broadcast.")
                await set_user_state(db, user_id, "idle")
                return

            skip_markup = text.strip().lower() in ("/skip", "skip")
            resolved_keyboard = None
            parse_errors: list[str] = []

            if not skip_markup:
                resolved_keyboard, parse_errors = await _parse_bml(db, text)

            reply_markup = {"inline_keyboard": resolved_keyboard} if resolved_keyboard else None

            await set_user_state(
                db, user_id, "broadcast_preview",
                {"broadcast_markup": reply_markup},
            )

            if parse_errors:
                warn_text = "⚠️ *Parse warnings (buttons with errors were skipped):*\n" + "\n".join(f"• {e}" for e in parse_errors)
                await send_message(session, chat_id, warn_text)

            await send_message(session, chat_id, "👁 *Live preview — this is exactly what users will receive:*")
            await copy_message(session, chat_id, chat_id, bc_msg_id, reply_markup=reply_markup)

            button_note = f"\n✅ *{sum(len(r) for r in resolved_keyboard)} button(s) attached across {len(resolved_keyboard)} row(s).*" if resolved_keyboard else "\n_(No buttons attached)_"

            await send_message(
                session, chat_id,
                f"Ready to broadcast to all users?{button_note}",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "✅ Send to everyone", "callback_data": "broadcast_confirm"}, {"text": "✏️ Edit buttons", "callback_data": "broadcast_edit_markup"}],
                        [{"text": "❌ Cancel", "callback_data": "broadcast_cancel"}],
                    ]
                },
            )
            return

        if text == "/admin":
            await send_message(
                session, chat_id, "⚙️ *Admin Panel*",
                reply_markup={
                    "keyboard": [[{"text": "📊 Statistics"}, {"text": "📅 Daily Stats"}], [{"text": "📢 Broadcast"}, {"text": "📂 Total Files"}], [{"text": "🔧 Manage Channels"}]],
                    "resize_keyboard": True,
                },
            )
            return

        if text == "📊 Statistics":
            u = await db.users.count_documents({})
            f = await db.files.count_documents({})
            await send_message(session, chat_id, f"👥 Users: `{u}`\n📂 Files: `{f}`")
            return

        if text == "📅 Daily Stats":
            await send_message(session, chat_id, await get_daily_stats(db))
            return

        if text == "📢 Broadcast":
            await set_user_state(db, user_id, "broadcast_wait")
            await send_message(
                session, chat_id,
                "📢 *Step 1 of 2 — Broadcast Content*\n\n"
                "Send the message you want to broadcast.\n"
                "Supported: text, photo, video, document, audio — anything Telegram supports.\n\n"
                "_After sending your content, I'll ask you to attach buttons (optional)._",
            )
            return

        if text == "📂 Total Files":
            f_count = await db.files.count_documents({})
            await send_message(session, chat_id, f"📂 Total Files in DB: `{f_count}`")
            return

        if "audio" in message or "voice" in message:
            f    = message.get("audio") or message.get("voice")
            cap  = message.get("caption", "").split("\n")[0].strip()
            name = cap if cap else f.get("file_name", "Unknown")
            if len(name) > 3:
                thumb_file_id = (message.get("audio", {}).get("thumbnail", {}).get("file_id") or message.get("audio", {}).get("thumb", {}).get("file_id")) 
                update_fields = {"file_id": f["file_id"], "display_name": name}
                if thumb_file_id: update_fields["thumb_file_id"] = thumb_file_id
                try:
                    await db.files.update_one({"display_name": {"$regex": re.escape(name), "$options": "i"}}, {"$set": update_fields}, upsert=True)
                    thumb_status = " 🖼" if thumb_file_id else ""
                    await send_message(session, chat_id, f"✅ Saved: `{name}`{thumb_status}")
                except Exception as db_err:
                    logger.error("db.files.update_one failed: %s", db_err)
                    await send_message(session, chat_id, f"❌ DB error saving `{name}`. Please retry.")
            return

    if text and not text.startswith("/"):
        await _react_to_message(session, chat_id, msg_id, "👀")
        sq  = build_search_query(text)
        doc = await db.files.find_one(sq, {"file_id": 1, "display_name": 1})

        if doc:
            matched_file_name = doc.get('display_name', 'Unknown')
            if not _is_admin(user_id) and not await check_membership(session, user_id, channels):
                hostage_msg = (
                    f"🎵 *{matched_file_name}* ተገኝቷል!\n\n"
                    "የፈለጉት መንዙማ ወይም PDF ፋይል ለማግኘት በመጀመሪያ ስለ ቦቱ አጠቃቀም መረጃ ሚለቀቅበት channel ይቀላቀሉ!"
                )
                await _send_html_message(session, chat_id, hostage_msg, reply_markup=get_subscription_kb(channels))
            else:
                kb = {"inline_keyboard": [[{"text": "➕ Add to Playlist", "callback_data": f"pl_add_{str(doc['_id'])}"}], [{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}
                res = await send_audio(session, chat_id, doc["file_id"], f"{matched_file_name}\n\n@{BOT_USERNAME}", reply_markup=kb)
                if res and res.get("ok"):
                    await _react_to_message(session, chat_id, res["result"]["message_id"], "🥰")
        else:
            suggestions = await get_fuzzy_suggestions(db, text, limit=5)
            if suggestions:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ በቀጥታ አልተገኘም።\n\n_ምናልባት ከታች ያሉት ሊሆኑ ይችላሉ? አንዱን ይምረጡ፦_", reply_markup=get_fuzzy_suggestions_kb(suggestions))
            else:
                await send_message(session, chat_id, "😔 የፈለጉት መንዙማ አልተገኘም።\nእባክዎ የተለየ ቃል ጽፈው ይሞክሩ ወይም 'ሙሉ ዝርዝር' የሚለውን ይጫኑ።", reply_markup=get_not_found_kb())


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

async def process_telegram_update(data: dict) -> None:
    if not MONGO_URL or not BOT_TOKEN:
        logger.error("MONGO_URL or BOT_TOKEN not set — aborting.")
        return

    db_client = AsyncIOMotorClient(MONGO_URL)
    db        = db_client[DB_NAME]

    async with aiohttp.ClientSession() as session:
        try:
            channels = get_channels_cache()
            if channels is None:
                channels = await get_force_channels(db)
                set_channels_cache(channels)

            if "callback_query" in data:
                await handle_callback(session, db, data["callback_query"], channels)
            elif "message" in data:
                await handle_message(session, db, data["message"], channels)
            elif "inline_query" in data:
                await handle_inline_query(session, db, data["inline_query"], channels)

        except Exception:
            logger.exception("Unhandled error in process_telegram_update")
        finally:
            db_client.close()


