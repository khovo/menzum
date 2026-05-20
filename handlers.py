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
)

logger = logging.getLogger(__name__)

# Cache of bot username to avoid getMe API round-trips
BOT_USERNAME = "MenzumaBot"


# ── Admin Panel Configurations ───────────────────────────────────────────────

_ADMIN_KB_TEXTS = ["📊 Stats", "📢 Broadcast", "📁 Upload Menzuma", "💾 Backup", "🛠 Maintenance Mode"]


async def _is_admin(db, user_id: int) -> bool:
    """Check if the user matches the system ADMIN_ID config or has admin role in DB."""
    if str(user_id) == str(ADMIN_ID):
        return True
    try:
        u = await get_user_data(db, user_id)
        if u and u.get("role") == "admin":
            return True
    except Exception:
        pass
    return False


def _get_admin_keyboard() -> dict:
    """Returns the ReplyKeyboardMarkup markup for administrators."""
    return {
        "keyboard": [
            [{"text": "📊 Stats"}, {"text": "📢 Broadcast"}],
            [{"text": "📁 Upload Menzuma"}],
            [{"text": "💾 Backup"}, {"text": "🛠 Maintenance Mode"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


async def send_backup_file(session: aiohttp.ClientSession, chat_id: int, backup_str: str) -> bool:
    """Sends the serialized users backup string as a JSON file attachment via Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field("caption", "💾 Al-Madih Database Users Backup (JSON)")
    data.add_field("document", backup_str.encode("utf-8"), filename="users_backup.json", content_type="application/json")
    try:
        async with session.post(url, data=data) as r:
            resp = await r.json()
            return resp.get("ok", False)
    except Exception:
        logger.exception("Failed to send backup document via API.")
        return False


# ── Message Parsing Helpers ───────────────────────────────────────────────────

def parse_bml_broadcast(text: str) -> list[dict]:
    """
    Parses "Broadcast Markup Language" (BML) for advanced messages.
    Syntax:
      - [TITLE]: Large premium block headers
      - [IMG](url): Prepends layout with a banner image
      - [BTN](text | url): Adds quick-access action buttons (max 2 per row)
    """
    blocks = []
    current_text = []
    image_url = None
    buttons = []

    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[TITLE]"):
            title_text = stripped[7:].strip()
            current_text.append(f"<b>🌟 {title_text.upper()} 🌟</b>\n")
        elif stripped.startswith("[IMG]"):
            # Format: [IMG](url)
            match = re.match(r"^\[IMG\]\((.*?)\)", stripped)
            if match:
                image_url = match.group(1).strip()
        elif stripped.startswith("[BTN]"):
            # Format: [BTN](Label | URL)
            match = re.match(r"^\[BTN\]\((.*?)\|(.*?)\)", stripped)
            if match:
                btn_lbl = match.group(1).strip()
                btn_url = match.group(2).strip()
                buttons.append({"text": btn_lbl, "url": btn_url})
        else:
            current_text.append(line)

    body = "\n".join(current_text).strip()
    return [{
        "body":      body,
        "image_url": image_url,
        "buttons":   buttons
    }]


def get_bml_markup(buttons: list) -> dict | None:
    """Maps list of parsed button objects into Telegram InlineKeyboardMarkup format."""
    if not buttons:
        return None
    keyboard = []
    row = []
    for btn in buttons:
        row.append({"text": btn["text"], "url": btn["url"]})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return {"inline_keyboard": keyboard}


# ── Core Update Handlers ──────────────────────────────────────────────────────

async def handle_message(session: aiohttp.ClientSession, db, message: dict, channels: list) -> None:
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    if not chat_id or not user_id:
        return

    # Basic tracking
    username   = message.get("from", {}).get("username")
    first_name = message.get("from", {}).get("first_name")
    user_doc   = await track_and_get_user(db, user_id, username, first_name)

    # ── Global Access Middleware (Ban check) ──
    if user_doc and user_doc.get("is_banned"):
        return

    # Admin Panel Gate
    is_admin_user = await _is_admin(db, user_id)

    # ── Global Access Middleware (Maintenance check) ──
    from db import is_maintenance_active
    if await is_maintenance_active(db) and not is_admin_user:
        await send_message(session, chat_id, "⚠️ ቦቱ በአጭር ጊዜ ጥገና ላይ ነው። እባክዎ ትንሽ ቆይተው ይሞክሩ.")
        return

    text = message.get("text", "").strip()

    # ── Force Join Verification ──────────────────────────────────────────────
    not_joined = []
    if not is_admin_user and channels:
        for ch in channels:
            cached_status = check_membership(user_id, ch["channel_id"])
            if cached_status is None:
                # Real API check
                is_member = False
                try:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
                    async with session.get(url, params={"chat_id": ch["channel_id"], "user_id": user_id}) as r:
                        resp = await r.json()
                        if resp.get("ok"):
                            status = resp["result"].get("status", "")
                            is_member = status in ("member", "administrator", "creator")
                except Exception:
                    logger.exception("Force join API check failed for %s", ch["channel_id"])
                    is_member = True # fail-safe bypass on network errors

                invalidate_membership_cache(user_id, ch["channel_id"])
                # update cache
                if is_member:
                    # Cache true for 12 hours
                    check_membership(user_id, ch["channel_id"]) # read triggers cache initialization, we can set manually
                    # Let's mock a fast key store
                    from utils import _MEMBERSHIP_CACHE
                    _MEMBERSHIP_CACHE[(user_id, ch["channel_id"])] = (True, time.time() + 43200)
                else:
                    not_joined.append(ch)
            elif not cached_status:
                not_joined.append(ch)

    if not_joined:
        # Save payload if they used a deep link
        if text.startswith("/start ") and len(text) > 7:
            param = text[7:].strip()
            await save_pending_start(db, user_id, param)

        kb = []
        for ch in not_joined:
            username_clean = ch["channel_id"].replace("@", "")
            kb.append([{"text": f"📢 {ch['title']}", "url": f"https://t.me/{username_clean}"}])
        
        kb.append([{"text": "✅ ተቀላቅያለሁ (Check Joined)", "callback_data": "verify_channels"}])
        
        await send_message(
            session,
            chat_id,
            "⚠️ <b>ይቅርታ!</b> ቦቱን ለመጠቀም መጀመሪያ የኛን ቻናሎች መቀላቀል አለብዎት።\n\n"
            "<i>Please join our channels below and tap Verify to proceed.</i>",
            reply_markup={"inline_keyboard": kb}
        )
        return

    # ── State-Machine Router (Interactive Admin Actions) ──────────────────────
    user_state = user_doc.get("state") if user_doc else None

    if is_admin_user and user_state:
        # 1. PENDING BROADCAST
        if user_state == "state_pending_broadcast":
            await set_user_state(db, user_id, None)
            if text == "❌ Cancel":
                await send_message(session, chat_id, "❌ Broadcast cancelled.", reply_markup=_get_admin_keyboard())
                return

            blocks = parse_bml_broadcast(text)
            if not blocks:
                await send_message(session, chat_id, "⚠️ Invalid message formatting. Broadcast aborted.", reply_markup=_get_admin_keyboard())
                return

            block = blocks[0]
            markup = get_bml_markup(block["buttons"])

            # Async trigger delivery
            users_list = await db.users.find({}, {"_id": 1}).to_list(length=None)
            success_count = 0
            fail_count = 0

            status_msg = await send_message(session, chat_id, "⏳ Delivery initiated. Progress: 0%")

            for i, target_user in enumerate(users_list):
                target_id = target_user["_id"]
                try:
                    if block["image_url"]:
                        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                        payload = {"chat_id": target_id, "photo": block["image_url"], "caption": block["body"], "parse_mode": "HTML"}
                        if markup:
                            payload["reply_markup"] = markup
                        async with session.post(url, json=payload) as r:
                            res = await r.json()
                            if res.get("ok"):
                                success_count += 1
                            else:
                                fail_count += 1
                    else:
                        res = await send_message(session, target_id, block["body"], reply_markup=markup)
                        if res:
                            success_count += 1
                        else:
                            fail_count += 1
                except Exception:
                    fail_count += 1

                # Update live stats every 10%
                if len(users_list) > 10 and (i + 1) % max(1, len(users_list) // 10) == 0:
                    pct = int(((i + 1) / len(users_list)) * 100)
                    await edit_message_text(session, chat_id, status_msg["message_id"], f"⏳ Delivery progress: {pct}%...")

            await edit_message_text(
                session,
                chat_id,
                status_msg["message_id"],
                f"📢 <b>Broadcast Complete!</b>\n\n"
                f"✅ Successful: <code>{success_count}</code>\n"
                f"❌ Failed/Blocked: <code>{fail_count}</code>"
            )
            return

        # 2. PENDING FORCE JOIN CHANNEL ID
        if user_state == "state_pending_force_join_id":
            if text == "❌ Cancel":
                await set_user_state(db, user_id, None)
                await send_message(session, chat_id, "❌ Action cancelled.", reply_markup=_get_admin_keyboard())
                return

            # Clean name
            clean_id = text.strip()
            if not clean_id.startswith("@") and not clean_id.startswith("-100"):
                clean_id = f"@{clean_id}"

            # Ask for Title
            await set_user_state(db, user_id, f"fj_title_{clean_id}")
            await send_message(
                session,
                chat_id,
                f"Now enter the readable <b>Title</b> or Label for <code>{clean_id}</code>:",
                reply_markup={"keyboard": [[{"text": "❌ Cancel"}]], "resize_keyboard": True}
            )
            return

        # 3. PENDING FORCE JOIN CHANNEL TITLE
        if user_state.startswith("fj_title_"):
            target_id = user_state[9:]
            if text == "❌ Cancel":
                await set_user_state(db, user_id, None)
                await send_message(session, chat_id, "❌ Action cancelled.", reply_markup=_get_admin_keyboard())
                return

            success = await add_force_channel(db, target_id, text.strip())
            await set_user_state(db, user_id, None)
            invalidate_channels_cache()
            
            if success:
                await send_message(session, chat_id, f"✅ Force-join target added:\nID: {target_id}\nTitle: {text}", reply_markup=_get_admin_keyboard())
            else:
                await send_message(session, chat_id, "❌ Failed to add. Check system logs.", reply_markup=_get_admin_keyboard())
            return

        # 4. PENDING REMOVE FORCE JOIN
        if user_state == "state_pending_force_remove":
            if text == "❌ Cancel":
                await set_user_state(db, user_id, None)
                await send_message(session, chat_id, "❌ Action cancelled.", reply_markup=_get_admin_keyboard())
                return

            success = await remove_force_channel(db, text.strip())
            await set_user_state(db, user_id, None)
            invalidate_channels_cache()

            if success:
                await send_message(session, chat_id, f"✅ Target `{text}` removed successfully.", reply_markup=_get_admin_keyboard())
            else:
                await send_message(session, chat_id, "❌ Target not found in the force-join configuration.", reply_markup=_get_admin_keyboard())
            return

    # ── Handle Admin Keyboard Panel Actions ───────────────────────────────────
    if is_admin_user:
        # ── Advanced Hybrid Slash Admin Commands ──
        if text.startswith("/ban "):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_str = parts[1].strip()
                try:
                    target_id = int(target_str)
                    from db import toggle_ban_user
                    await toggle_ban_user(db, target_id, True)
                    await send_message(session, chat_id, f"✅ <b>User {target_id} has been successfully banned.</b>")
                except ValueError:
                    await send_message(session, chat_id, "⚠️ Invalid user ID format. Must be an integer.")
            else:
                await send_message(session, chat_id, "Usage: <code>/ban <user_id></code>")
            return

        elif text.startswith("/unban "):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_str = parts[1].strip()
                try:
                    target_id = int(target_str)
                    from db import toggle_ban_user
                    await toggle_ban_user(db, target_id, False)
                    await send_message(session, chat_id, f"✅ <b>User {target_id} has been unbanned.</b>")
                except ValueError:
                    await send_message(session, chat_id, "⚠️ Invalid user ID format. Must be an integer.")
            else:
                await send_message(session, chat_id, "Usage: <code>/unban <user_id></code>")
            return

        elif text.startswith("/msg "):
            parts = text.split(maxsplit=2)
            if len(parts) == 3:
                target_str = parts[1].strip()
                msg_body = parts[2].strip()
                try:
                    target_id = int(target_str)
                    res = await send_message(session, target_id, msg_body)
                    if res:
                        await send_message(session, chat_id, f"✅ Message delivered to <code>{target_id}</code>.")
                    else:
                        await send_message(session, chat_id, f"❌ Failed to deliver message to <code>{target_id}</code>.")
                except ValueError:
                    await send_message(session, chat_id, "⚠️ Invalid user ID format.")
            else:
                await send_message(session, chat_id, "Usage: <code>/msg <user_id> <text></code>")
            return

        elif text.startswith("/searchdb "):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                query_str = parts[1].strip()
                cursor = db.files.find({"display_name": {"$regex": query_str, "$options": "i"}})
                results = await cursor.to_list(length=50)
                if results:
                    resp_lines = [f"🔍 <b>Matches for '{query_str}':</b>"]
                    for r in results:
                        resp_lines.append(
                            f"• Name: <code>{r.get('display_name')}</code>\n"
                            f"  ID: <code>{r.get('_id')}</code> | Unique ID: <code>{r.get('file_unique_id')}</code>"
                        )
                    out_text = "\n\n".join(resp_lines)
                    if len(out_text) > 4000:
                        out_text = out_text[:4000] + "\n... (truncated)"
                    await send_message(session, chat_id, out_text)
                else:
                    await send_message(session, chat_id, "❌ No files matched that query.")
            else:
                await send_message(session, chat_id, "Usage: <code>/searchdb <text></code>")
            return

        elif text.startswith("/edit "):
            parts = text.split(maxsplit=2)
            if len(parts) == 3:
                doc_id = parts[1].strip()
                new_name = parts[2].strip()
                from db import update_file_name
                success = await update_file_name(db, doc_id, new_name)
                if success:
                    await send_message(session, chat_id, f"✅ File <code>{doc_id}</code> successfully renamed to <b>{new_name}</b>.")
                else:
                    await send_message(session, chat_id, f"❌ File <code>{doc_id}</code> not found or not modified.")
            else:
                await send_message(session, chat_id, "Usage: <code>/edit <doc_id> <new_name></code>")
            return

        elif text.startswith("/delete "):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                doc_id = parts[1].strip()
                from db import delete_media_file
                success = await delete_media_file(db, doc_id)
                if success:
                    await send_message(session, chat_id, f"✅ File <code>{doc_id}</code> successfully deleted from the catalog.")
                else:
                    await send_message(session, chat_id, f"❌ File <code>{doc_id}</code> not found.")
            else:
                await send_message(session, chat_id, "Usage: <code>/delete <doc_id></code>")
            return

        elif text.startswith("/addadmin "):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_str = parts[1].strip()
                try:
                    target_id = int(target_str)
                    from db import manage_admin_role
                    await manage_admin_role(db, target_id, True)
                    await send_message(session, chat_id, f"✅ User <code>{target_id}</code> promoted to administrator.")
                except ValueError:
                    await send_message(session, chat_id, "⚠️ Invalid user ID format.")
            else:
                await send_message(session, chat_id, "Usage: <code>/addadmin <user_id></code>")
            return

        elif text.startswith("/deladmin "):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_str = parts[1].strip()
                try:
                    target_id = int(target_str)
                    from db import manage_admin_role
                    await manage_admin_role(db, target_id, False)
                    await send_message(session, chat_id, f"✅ User <code>{target_id}</code> role revoked to regular user.")
                except ValueError:
                    await send_message(session, chat_id, "⚠️ Invalid user ID format.")
            else:
                await send_message(session, chat_id, "Usage: <code>/deladmin <user_id></code>")
            return

        elif text.startswith("/user "):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_str = parts[1].strip()
                try:
                    target_id = int(target_str)
                    target_user = await get_user_data(db, target_id)
                    if target_user:
                        username_lbl = f"@{target_user.get('username')}" if target_user.get("username") else "None"
                        first_name_lbl = target_user.get("first_name") or "None"
                        role_lbl = target_user.get("role", "user")
                        ban_status = "Banned 🔴" if target_user.get("is_banned") else "Active 🟢"
                        created_lbl = target_user.get("created_at") or target_user.get("joined_at") or "Unknown"
                        
                        user_info = (
                            f"👤 <b>User Stats Profile:</b>\n\n"
                            f"🆔 ID: <code>{target_id}</code>\n"
                            f"📛 First Name: {first_name_lbl}\n"
                            f"🗣 Username: {username_lbl}\n"
                            f"🛡 Role: <code>{role_lbl}</code>\n"
                            f"🚫 Status: <b>{ban_status}</b>\n"
                            f"📅 Join Date: <code>{created_lbl}</code>"
                        )
                        await send_message(session, chat_id, user_info)
                    else:
                        await send_message(session, chat_id, "❌ User not found in database.")
                except ValueError:
                    await send_message(session, chat_id, "⚠️ Invalid user ID format.")
            else:
                await send_message(session, chat_id, "Usage: <code>/user <user_id></code>")
            return

        # ── Advanced Hybrid Keyboard Command Handlers ──
        elif text == "💾 Backup":
            from db import generate_users_backup
            backup_json = await generate_users_backup(db)
            sent = await send_backup_file(session, chat_id, backup_json)
            if not sent:
                await send_message(session, chat_id, "❌ Failed to generate or send backup document.")
            return

        elif text == "🛠 Maintenance Mode":
            from db import toggle_maintenance
            new_status = await toggle_maintenance(db)
            status_str = "ON 🔴" if new_status else "OFF 🟢"
            await send_message(session, chat_id, f"🛠 Maintenance mode has been successfully toggled: <b>{status_str}</b>")
            return

        if text == "📊 Stats":
            users_c, files_c = await get_daily_stats(db)
            
            # Show force join status
            f_ch = await get_force_channels(db)
            ch_list_str = "\n".join([f"• <code>{c['channel_id']}</code> ({c['title']})" for c in f_ch]) if f_ch else "None"

            stats_body = (
                f"📈 <b>Baraka Analytics Panel</b>\n\n"
                f"👥 Total Users: <code>{users_c}</code>\n"
                f"🎵 Audio Catalog: <code>{files_c}</code>\n\n"
                f"⚙️ <b>Active Force-Join Gates:</b>\n"
                f"{ch_list_str}\n\n"
                f"👉 Use `/add_channel` or `/del_channel` to configure gates dynamically."
            )
            await send_message(session, chat_id, stats_body, reply_markup=_get_admin_keyboard())
            return

        elif text == "📢 Broadcast":
            await set_user_state(db, user_id, "state_pending_broadcast")
            await send_message(
                session,
                chat_id,
                "📝 <b>Compose your Broadcast:</b>\n\n"
                "Supports standard HTML formatting + premium <b>BML extensions</b>:\n"
                "• <code>[TITLE] Section Name</code>\n"
                "• <code>[IMG](https://url/banner.jpg)</code>\n"
                "• <code>[BTN](Label text | https://action_link.com)</code>\n\n"
                "Send your message now or tap Cancel.",
                reply_markup={"keyboard": [[{"text": "❌ Cancel"}]], "resize_keyboard": True}
            )
            return

        elif text == "📁 Upload Menzuma":
            await send_message(
                session,
                chat_id,
                "📥 <b>Upload Engine Activated</b>\n\n"
                "Simply forward or send your MP3 audio files or PDF book documents directly to me here.\n"
                "I will auto-parse titles and cache them safely.",
                reply_markup=_get_admin_keyboard()
            )
            return

        # Admin Slash Command Routing
        if text.startswith("/add_channel"):
            await set_user_state(db, user_id, "state_pending_force_join_id")
            await send_message(
                session,
                chat_id,
                "Enter the Telegram Channel ID (e.g., <code>@mychannel</code> or <code>-100xxxxx</code>):",
                reply_markup={"keyboard": [[{"text": "❌ Cancel"}]], "resize_keyboard": True}
            )
            return

        elif text.startswith("/del_channel"):
            await set_user_state(db, user_id, "state_pending_force_remove")
            await send_message(
                session,
                chat_id,
                "Enter the Channel ID you want to remove (e.g. <code>@mychannel</code>):",
                reply_markup={"keyboard": [[{"text": "❌ Cancel"}]], "resize_keyboard": True}
            )
            return

    # ── User Commands & Workflows ─────────────────────────────────────────────

    # 1. Start Commands & Deep Links
    if text.startswith("/start"):
        # Detect Deep Links
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            start_param = parts[1].strip()
            
            # CASE A: Shareable Playlists
            if start_param.startswith("pl_"):
                pl = await get_playlist(db, start_param)
                if pl:
                    # Increment atomic plays
                    await increment_playlist_plays(db, start_param)
                    
                    # Package track media group or deliver track sequence
                    tracks = pl.get("tracks", [])
                    pl_name = f"Shared Playlist ({len(tracks)} tracks)"
                    
                    await send_message(
                        session,
                        chat_id,
                        f"🎧 <b>Loading Shared Playlist:</b>\n"
                        f"👤 Creator ID: <code>{pl.get('creator_id')}</code>\n"
                        f"📊 Play count: <code>{pl.get('play_count', 0) + 1}</code>\n"
                        f"🔥 Tracks total: <code>{len(tracks)}</code>\n\n"
                        f"<i>Preparing stream delivery, please wait...</i>"
                    )
                    
                    # Direct file group delivery
                    media = []
                    for idx, t in enumerate(tracks):
                        media.append({
                            "type":    "audio",
                            "media":   t["file_id"],
                            "caption": f"{idx+1}. {t['name']}\n\n🏷 Shared via @{BOT_USERNAME}"
                        })
                    
                    # Break into batches of 10 (Telegram maximum limit)
                    for i in range(0, len(media), 10):
                        batch = media[i:i+10]
                        await send_media_group(session, chat_id, batch)
                    return
                else:
                    await send_message(session, chat_id, "⚠️ <b>Playlist Link Expired</b>\nThat playlist is no longer active.")
                    return

            # CASE B: Direct Track Sharing
            else:
                # Expect ObjectId or file_unique_id
                try:
                    # Check Object ID lookup first
                    query = {"_id": ObjectId(start_param)}
                except Exception:
                    query = {"file_unique_id": start_param}
                
                track = await db.files.find_one(query)
                if track:
                    if track.get("file_type") == "audio":
                        kb = {"inline_keyboard": [[{"text": "❤️ Add Favorite", "callback_data": f"fav_{track['_id']}"}]]}
                        await send_audio(
                            session,
                            chat_id,
                            track["file_id"],
                            caption=f"🎵 <b>{track.get('display_name')}</b>\n\n🏷 Enjoy streaming on @{BOT_USERNAME}",
                            reply_markup=kb
                        )
                    elif track.get("file_type") == "document":
                        await send_message(session, chat_id, f"📖 Loading Document: <b>{track.get('display_name')}</b>...")
                        # Deliver document file
                        payload = {"chat_id": chat_id, "document": track["file_id"], "caption": f"📖 {track.get('display_name')}\n\n@{BOT_USERNAME}"}
                        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
                        await session.post(url, json=payload)
                    return
                else:
                    await send_message(session, chat_id, "⚠️ Track/Book link not found. It may have been removed.")
                    return

        # Standard Launch menu fallback
        web_app_url = os.getenv("WEBAPP_URL", "https://menzum.vercel.app")
        # Build attractive inline buttons for interactive web app
        kb = {
            "inline_keyboard": [
                [{"text": "🚀 Open Al-Madih App", "web_app": {"url": web_app_url}}],
                [{"text": "📖 Read Islamic Books", "callback_data": "menu_books"}]
            ]
        }
        
        # Fresh menu delivery — clear previous inline clutter
        last_id = user_doc.get("last_menu_msg_id") if user_doc else None
        if last_id:
            await delete_message(session, chat_id, last_id)

        welcome_msg = await send_message(
            session,
            chat_id,
            f"🌙 <b>Welcome to Al-Madih (አል-መዲህ)</b> 🌙\n\n"
            f"The premier high-performance audio streaming platform built natively for Telegram.\n\n"
            f"• Stream over <b>1,150+ Menzumas</b> instantly\n"
            f"• Build custom shareable playlists\n"
            f"• Download & Read complete Islamic books\n\n"
            f"👉 Tap the button below to launch the streaming app!",
            reply_markup=kb
        )
        if welcome_msg:
            await save_last_menu_msg_id(db, user_id, welcome_msg["message_id"])
        return

    # Help commands
    if text == "/help":
        help_text = (
            "💡 <b>Need Help? Here is how to use the Bot:</b>\n\n"
            "1️⃣ Tap <b>Open Al-Madih App</b> to load the full player.\n"
            "2️⃣ Browse catalog, create dynamic playlists inside the app, and share them directly with your friends.\n"
            "3️⃣ Type what you want to search directly into this chat, or use <i>Inline Mode</i> inside other chats by typing <code>@MenzumaBot ...</code>"
        )
        await send_message(session, chat_id, help_text)
        return

    # ── Database Cache Handler (Upload Engine) ────────────────────────────────
    # Runs when admin sends files directly
    if is_admin_user:
        # 1. MP3 Audio Parser
        if "audio" in message:
            audio = message["audio"]
            file_id        = audio["file_id"]
            file_unique_id = audio["file_unique_id"]
            file_name      = audio.get("file_name", "audio.mp3")
            display_name   = audio.get("title") or audio.get("performer") or file_name
            file_size      = audio.get("file_size", 0)
            mime_type      = audio.get("mime_type", "audio/mpeg")

            # Extract thumb if present
            thumb_file_id = None
            if "thumb" in audio:
                thumb_file_id = audio["thumb"].get("file_id")

            # Save
            await db.files.update_one(
                {"file_unique_id": file_unique_id},
                {
                    "$set": {
                        "file_id":       file_id,
                        "file_name":     file_name,
                        "display_name":  display_name,
                        "file_size":     file_size,
                        "file_type":     "audio",
                        "mime_type":     mime_type,
                        "thumb_file_id": thumb_file_id,
                        "updated_at":    datetime.now()
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now()
                    }
                },
                upsert=True
            )
            await send_message(session, chat_id, f"✅ <b>Audio Cached Successfully!</b>\nName: <code>{display_name}</code>\nID: <code>{file_unique_id}</code>")
            return

        # 2. PDF Document Parser
        elif "document" in message:
            doc = message["document"]
            mime_type = doc.get("mime_type", "")
            if mime_type != "application/pdf" and not doc.get("file_name", "").endswith(".pdf"):
                await send_message(session, chat_id, "⚠️ Only PDF documents are supported under the document library parser.")
                return

            file_id        = doc["file_id"]
            file_unique_id = doc["file_unique_id"]
            file_name      = doc.get("file_name", "book.pdf")
            display_name   = file_name.replace(".pdf", "").replace("_", " ").replace("-", " ")
            file_size      = doc.get("file_size", 0)

            # Save to document catalog
            await db.files.update_one(
                {"file_unique_id": file_unique_id},
                {
                    "$set": {
                        "file_id":      file_id,
                        "file_name":    file_name,
                        "display_name": display_name,
                        "file_size":    file_size,
                        "file_type":    "document",
                        "mime_type":    "application/pdf",
                        "updated_at":   datetime.now()
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now()
                    }
                },
                upsert=True
            )
            await send_message(session, chat_id, f"✅ <b>Book Document Cached Successfully!</b>\nTitle: <code>{display_name}</code>\nID: <code>{file_unique_id}</code>")
            return

    # ── Plain-Text Search Router (Fallback) ───────────────────────────────────
    if text:
        # Perform indexed catalog regex matching
        sq = build_search_query(text)
        if sq:
            docs = await db.files.find(sq).limit(5).to_list(length=5)
            if docs:
                for doc in docs:
                    kb = {"inline_keyboard": [[{"text": "❤️ Fav", "callback_data": f"fav_{str(doc['_id'])}"}]]}
                    await send_audio(
                        session,
                        chat_id,
                        doc["file_id"],
                        caption=f"🎵 <b>{doc.get('display_name')}</b>\n\n🏷 Stream on @{BOT_USERNAME}",
                        reply_markup=kb
                    )
                return
            else:
                # No exact match — fetch fuzzy suggestions
                suggestions = await get_fuzzy_suggestions(db, text)
                if suggestions:
                    await send_message(
                        session,
                        chat_id,
                        "🔍 <b>No exact track match found.</b>\nDid you mean one of these?",
                        reply_markup=get_fuzzy_kb(suggestions)
                    )
                else:
                    await send_message(
                        session,
                        chat_id,
                        "⚠️ <b>No matches found</b>\nWe couldn't find any track or book matching that query. Try typing another title.",
                        reply_markup=get_not_found_kb()
                    )


async def handle_callback(session: aiohttp.ClientSession, db, callback: dict, channels: list) -> None:
    query_id = callback.get("id")
    chat_id  = callback.get("message", {}).get("chat", {}).get("id")
    user_id  = callback.get("from", {}).get("id")
    if not query_id or not user_id:
        return

    # ── Global Access Middleware (Ban check) ──
    user_doc = await get_user_data(db, user_id)
    if user_doc and user_doc.get("is_banned"):
        return

    # Admin Panel Gate
    is_admin_user = await _is_admin(db, user_id)

    # ── Global Access Middleware (Maintenance check) ──
    from db import is_maintenance_active
    if await is_maintenance_active(db) and not is_admin_user:
        await answer_callback_query(session, query_id, "⚠️ ቦቱ በአጭር ጊዜ ጥገና ላይ ነው። እባክዎ ትንሽ ቆይተው ይሞክሩ.", show_alert=True)
        return

    data = callback.get("data", "")

    # 1. Verification of force-join channels
    if data == "verify_channels":
        not_joined = []
        if channels:
            for ch in channels:
                is_member = False
                try:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
                    async with session.get(url, params={"chat_id": ch["channel_id"], "user_id": user_id}) as r:
                        resp = await r.json()
                        if resp.get("ok"):
                            status = resp["result"].get("status", "")
                            is_member = status in ("member", "administrator", "creator")
                except Exception:
                    is_member = True # Bypass error
                
                if is_member:
                    from utils import _MEMBERSHIP_CACHE
                    _MEMBERSHIP_CACHE[(user_id, ch["channel_id"])] = (True, time.time() + 43200)
                else:
                    not_joined.append(ch)

        if not_joined:
            await answer_callback_query(session, query_id, "⚠️ Still not subscribed to all channels! Please join and verify again.", show_alert=True)
        else:
            await answer_callback_query(session, query_id, "✅ Verification Successful!")
            
            # Retrieve pending deep link parameter
            user_doc = await get_user_data(db, user_id)
            pending = user_doc.get("pending_start") if user_doc else None
            
            # Clear pending state
            await db.users.update_one({"_id": user_id}, {"$unset": {"pending_start": ""}})
            
            # Send standard start message or fire deep link router
            start_payload = f"/start {pending}" if pending else "/start"
            # Route simulated message manually
            await handle_message(session, db, {
                "chat": {"id": chat_id},
                "from": {"id": user_id, "username": callback.get("from", {}).get("username"), "first_name": callback.get("from", {}).get("first_name")},
                "text": start_payload
            }, channels)
            
            # Delete joining instructions message to avoid confusion
            msg_id = callback.get("message", {}).get("message_id")
            if msg_id:
                await delete_message(session, chat_id, msg_id)
        return

    # 2. Toggle Favorites Action
    if data.startswith("fav_"):
        track_id_str = data[4:]
        res = await toggle_favorite(db, user_id, track_id_str)
        if res is True:
            await answer_callback_query(session, query_id, "❤️ Added to Favorites!")
        elif res is False:
            await answer_callback_query(session, query_id, "💔 Removed from Favorites!")
        else:
            await answer_callback_query(session, query_id, "❌ Error saving favorite. Track may be missing.")
        return

    # 3. Interactive Books Directory
    if data == "menu_books":
        # Find all documents (PDFs)
        books = await db.files.find({"file_type": "document"}).to_list(length=50)
        if not books:
            await answer_callback_query(session, query_id, "📚 The Book library is currently empty!")
            return

        kb_rows = []
        for b in books:
            # Inline button for direct load
            short_id = str(b["_id"])
            kb_rows.append([{"text": f"📖 {b.get('display_name')}", "callback_data": f"read_{short_id}"}])
        
        await edit_message_text(
            session,
            chat_id,
            callback["message"]["message_id"],
            "📚 <b>Al-Madih Islamic Library</b>\n\n"
            "Select any book below to view and read immediately inside Telegram:",
            reply_markup={"inline_keyboard": kb_rows}
        )
        return

    if data.startswith("read_"):
        book_id = data[5:]
        try:
            book_doc = await db.files.find_one({"_id": ObjectId(book_id)})
            if book_doc:
                await answer_callback_query(session, query_id, "📖 Loading Book Document...")
                payload = {"chat_id": chat_id, "document": book_doc["file_id"], "caption": f"📖 <b>{book_doc.get('display_name')}</b>\n\n🏷 Read with @{BOT_USERNAME}"}
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
                await session.post(url, json=payload)
            else:
                await answer_callback_query(session, query_id, "❌ Book not found!")
        except Exception:
            await answer_callback_query(session, query_id, "❌ Invalid request identifier!")
        return


async def handle_inline_query(session: aiohttp.ClientSession, db, inline_query: dict) -> None:
    query_id = inline_query.get("id")
    user_id  = inline_query.get("from", {}).get("id")
    query    = inline_query.get("query", "").strip()
    if not query_id or not user_id:
        return

    # ── Global Access Middleware (Ban check) ──
    user_doc = await get_user_data(db, user_id)
    if user_doc and user_doc.get("is_banned"):
        return

    # Admin Panel Gate
    is_admin_user = await _is_admin(db, user_id)

    # ── Global Access Middleware (Maintenance check) ──
    from db import is_maintenance_active
    if await is_maintenance_active(db) and not is_admin_user:
        await answer_inline_query(session, query_id, [])
        return

    # Direct indexed search query
    results = []
    sq = build_search_query(query) if query else {"file_type": "audio"}

    try:
        docs = await db.files.find(sq, {"file_id": 1, "display_name": 1}).limit(20).to_list(length=20)
        for doc in docs:
            results.append({
                "type":          "audio",
                "id":            str(doc["_id"]),
                "audio_file_id": doc["file_id"],
                "caption":       f"🎵 {doc.get('display_name')}\n\n🏷 Stream on @{BOT_USERNAME}"
            })
    except Exception:
        logger.exception("Inline query catalog lookup failed.")

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
                await handle_inline_query(session, db, data["inline_query"])
        except Exception:
            logger.exception("Failed to process incoming Telegram updates securely.")

