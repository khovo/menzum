"""
handlers/admin_commands.py
--------------------------
Advanced admin slash-commands + their confirmation callbacks.

Gated by the async is_admin() (root ADMIN_ID or any co-admin) in message_handler
and callback_handler — these functions assume the caller is already an admin.

Commands:
  Multi-admin  : /addadmin /removeadmin /listadmins
  Audio        : /editaudio /deleteaudio /findaudio
  PDF          : /editpdf /removepdf /listpdfs
  Users        : /userinfo /banuser /unbanuser /listbanned
  Bot control  : /maintenance /dbstats
  Export       : /exportalldb
Callbacks: del_audio_confirm_<id> / del_audio_cancel / del_pdf_confirm_<id> / del_pdf_cancel
"""
import logging
from datetime import datetime

from config import ADMIN_ID
from db import (
    add_admin,
    remove_admin,
    list_admins,
    rename_audio,
    get_audio_by_file_id,
    delete_audio_by_id,
    find_audio,
    find_pdf,
    rename_pdf,
    delete_pdf_by_id,
    list_pdfs,
    get_user_data,
    ban_user,
    unban_user,
    is_banned,
    list_banned,
    set_maintenance,
    get_db_stats,
    get_all_users_for_export,
    unhide_by_id,
    unhide_by_file_id,
)
from utils import (
    send_message,
    send_document_bytes,
    edit_message_text,
    answer_callback_query,
)
from .broadcast_engine import release_broadcast_lock

logger = logging.getLogger(__name__)

_TELEGRAM_TEXT_LIMIT = 3500


# ── small helpers ─────────────────────────────────────────────────────────────

def _fmt_dt(value) -> str:
    """Format a stored datetime as YYYY-MM-DD; tolerate missing/odd values."""
    try:
        return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else (str(value) if value else "—")
    except Exception:
        return "—"


def _csv_field(value) -> str:
    """CSV-escape a single field (quote when it contains a comma/quote/newline)."""
    s = str(value if value is not None else "")
    s = s.replace("\r", " ").replace("\n", " ")
    if "," in s or '"' in s:
        s = '"' + s.replace('"', '""') + '"'
    return s


def _is_int(token: str) -> bool:
    return bool(token) and token.lstrip("-").isdigit()


async def _send_long(session, chat_id, text: str) -> None:
    """Send text, splitting on line boundaries to stay under Telegram's limit."""
    if len(text) <= _TELEGRAM_TEXT_LIMIT:
        await send_message(session, chat_id, text)
        return
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > _TELEGRAM_TEXT_LIMIT:
            if chunk:
                await send_message(session, chat_id, chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await send_message(session, chat_id, chunk)


def _confirm_kb(confirm_data: str, cancel_data: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ Confirm Delete", "callback_data": confirm_data},
        {"text": "❌ Cancel",         "callback_data": cancel_data},
    ]]}


# ── command router ──────────────────────────────────────────────────────────

async def handle_admin_command(session, db, message, chat_id, user_id, text, msg_id) -> bool:
    """Dispatch an admin slash-command. Returns True if it was handled."""
    if not text or not text.startswith("/"):
        return False

    head, _, rest = text.partition(" ")
    cmd = head.lower().split("@")[0]   # strip any @botusername suffix
    arg = rest.strip()

    handler = _COMMANDS.get(cmd)
    if not handler:
        return False
    await handler(session, db, message, chat_id, user_id, arg)
    return True


# ── Multi-admin ──────────────────────────────────────────────────────────────

async def _cmd_addadmin(session, db, message, chat_id, user_id, arg):
    parts = arg.split(maxsplit=1)
    if not parts or not _is_int(parts[0]):
        await send_message(session, chat_id, "Usage: `/addadmin <user_id> [display_name]`")
        return
    target  = int(parts[0])
    display = parts[1].strip() if len(parts) > 1 else str(target)
    if str(target) == str(ADMIN_ID):
        await send_message(session, chat_id, "⚠️ That user is already the root admin.")
        return
    if await add_admin(db, target, display, user_id):
        await send_message(session, chat_id, f"✅ Admin added: {display} (`{target}`)")
    else:
        await send_message(session, chat_id, "❌ Failed to add admin. Please retry.")


async def _cmd_removeadmin(session, db, message, chat_id, user_id, arg):
    if not _is_int(arg):
        await send_message(session, chat_id, "Usage: `/removeadmin <user_id>`")
        return
    target = int(arg)
    if str(target) == str(ADMIN_ID):
        await send_message(session, chat_id, "⚠️ Cannot remove the root admin.")
        return
    if await remove_admin(db, target):
        await send_message(session, chat_id, f"✅ Removed admin `{target}`")
    else:
        await send_message(session, chat_id, "⚠️ Not found")


async def _cmd_listadmins(session, db, message, chat_id, user_id, arg):
    admins = await list_admins(db)
    lines = ["👮 *Admins*", f"• 👑 Root — `{ADMIN_ID}`"]
    for a in admins:
        lines.append(f"• {a.get('display_name', '?')} — `{a['_id']}`")
    if not admins:
        lines.append("_No co-admins yet._")
    await _send_long(session, chat_id, "\n".join(lines))


# ── Audio management ─────────────────────────────────────────────────────────

def _replied_audio(message) -> dict | None:
    reply = message.get("reply_to_message") or {}
    return reply.get("audio") or reply.get("voice")


async def _cmd_editaudio(session, db, message, chat_id, user_id, arg):
    audio = _replied_audio(message)
    if not audio or not arg:
        await send_message(session, chat_id, "⚠️ Reply to an audio message with `/editaudio <new name>`")
        return
    file_id = audio.get("file_id")
    if file_id and await rename_audio(db, file_id, arg):
        await send_message(session, chat_id, f"✅ Renamed to: `{arg}`")
    else:
        await send_message(session, chat_id, "⚠️ That audio isn't in the database.")


async def _cmd_unhide(session, db, message, chat_id, user_id, arg):
    """Admin override: un-hide an audio/PDF (reply to it, or /unhide <id>)."""
    reply = message.get("reply_to_message") or {}
    media = reply.get("audio") or reply.get("voice") or reply.get("document")
    if media and media.get("file_id"):
        result = await unhide_by_file_id(db, media["file_id"])
    elif arg and len(arg.strip()) == 24:
        result = await unhide_by_id(db, arg.strip())
    else:
        await send_message(session, chat_id, "⚠️ Reply to an audio/PDF with `/unhide`, or use `/unhide <id>`.")
        return
    if result:
        kind, title = result
        await send_message(session, chat_id, f"✅ Unhidden ({kind}): `{title}`\n_It will appear in search & lists again._")
    else:
        await send_message(session, chat_id, "⚠️ Not found in the database (check the id, or that you replied to a saved item).")


async def _cmd_deleteaudio(session, db, message, chat_id, user_id, arg):
    audio = _replied_audio(message)
    if not audio:
        await send_message(session, chat_id, "⚠️ Reply to an audio message with `/deleteaudio`")
        return
    file_id = audio.get("file_id")
    doc = await get_audio_by_file_id(db, file_id) if file_id else None
    if not doc:
        await send_message(session, chat_id, "⚠️ That audio isn't in the database.")
        return
    # callback_data is capped at 64 bytes — audio file_ids are far too long, so we
    # key the confirmation on the (24-char) Mongo _id and delete by _id on confirm.
    doc_id = str(doc["_id"])
    name   = doc.get("display_name", "Unknown")
    await send_message(
        session, chat_id,
        f"🗑 Delete this audio?\n`{name}`\n\n_This cannot be undone._",
        reply_markup=_confirm_kb(f"del_audio_confirm_{doc_id}", "del_audio_cancel"),
    )


async def _cmd_findaudio(session, db, message, chat_id, user_id, arg):
    if not arg:
        await send_message(session, chat_id, "Usage: `/findaudio <search term>`")
        return
    docs = await find_audio(db, arg, limit=5)
    if not docs:
        await send_message(session, chat_id, f"😔 No matches for `{arg}`.")
        return
    lines = [f"🔎 *Results for* `{arg}`:"]
    for d in docs:
        lines.append(f"• `{d.get('display_name', 'Unknown')}`\n  id: `{d['_id']}`")
    await _send_long(session, chat_id, "\n".join(lines))


# ── PDF management ───────────────────────────────────────────────────────────

async def _cmd_editpdf(session, db, message, chat_id, user_id, arg):
    if "|" not in arg:
        await send_message(session, chat_id, "Usage: `/editpdf <object_id_or_partial_title> | <new title>`")
        return
    ident, _, new_title = arg.partition("|")
    ident, new_title = ident.strip(), new_title.strip()
    if not ident or not new_title:
        await send_message(session, chat_id, "Usage: `/editpdf <object_id_or_partial_title> | <new title>`")
        return
    doc = await find_pdf(db, ident)
    if not doc:
        await send_message(session, chat_id, "⚠️ PDF not found.")
        return
    if await rename_pdf(db, str(doc["_id"]), new_title):
        await send_message(session, chat_id, f"✅ PDF renamed to: `{new_title}`")
    else:
        await send_message(session, chat_id, "❌ Failed to rename PDF.")


async def _cmd_removepdf(session, db, message, chat_id, user_id, arg):
    if not arg:
        await send_message(session, chat_id, "Usage: `/removepdf <object_id>`")
        return
    doc = await find_pdf(db, arg)
    if not doc:
        await send_message(session, chat_id, "⚠️ PDF not found.")
        return
    oid   = str(doc["_id"])
    title = doc.get("title", "Untitled")
    await send_message(
        session, chat_id,
        f"🗑 Delete this PDF?\n`{title}`\n\n_This cannot be undone._",
        reply_markup=_confirm_kb(f"del_pdf_confirm_{oid}", "del_pdf_cancel"),
    )


async def _cmd_listpdfs(session, db, message, chat_id, user_id, arg):
    pdfs = await list_pdfs(db)
    if not pdfs:
        await send_message(session, chat_id, "📄 No PDFs in the library.")
        return
    lines = [f"📄 *PDFs ({len(pdfs)})*"]
    for p in pdfs:
        lines.append(f"• {p.get('title', 'Untitled')}\n  id: `{p['_id']}` · ⬇️ {p.get('download_count', 0)}")
    await _send_long(session, chat_id, "\n".join(lines))


# ── User management ──────────────────────────────────────────────────────────

async def _cmd_userinfo(session, db, message, chat_id, user_id, arg):
    if not _is_int(arg):
        await send_message(session, chat_id, "Usage: `/userinfo <user_id>`")
        return
    target = int(arg)
    u = await get_user_data(db, target)
    if not u:
        await send_message(session, chat_id, "⚠️ User not found.")
        return
    banned = await is_banned(db, target)
    text = (
        "👤 *User Info*\n"
        f"Name: {u.get('first_name', '—')}\n"
        f"ID: `{target}`\n"
        f"Joined: {_fmt_dt(u.get('joined_at'))}\n"
        f"Last Active: {_fmt_dt(u.get('last_active'))}\n"
        f"Total Plays: {u.get('total_plays', 0)}\n"
        f"Favorites: {len(u.get('favorites', []))}\n"
        f"State: {u.get('state', 'idle') or 'idle'}\n"
        f"Banned: {'Yes' if banned else 'No'}"
    )
    await send_message(session, chat_id, text)


async def _cmd_banuser(session, db, message, chat_id, user_id, arg):
    parts = arg.split(maxsplit=1)
    if not parts or not _is_int(parts[0]):
        await send_message(session, chat_id, "Usage: `/banuser <user_id> [reason]`")
        return
    target = int(parts[0])
    reason = parts[1].strip() if len(parts) > 1 else ""
    if str(target) == str(ADMIN_ID):
        await send_message(session, chat_id, "⚠️ Cannot ban the root admin.")
        return
    if await ban_user(db, target, reason, user_id):
        await send_message(session, target, "⛔ You have been restricted from using Al-Madih.")
        await send_message(session, chat_id, f"✅ Banned user `{target}`")
    else:
        await send_message(session, chat_id, "❌ Failed to ban user.")


async def _cmd_unbanuser(session, db, message, chat_id, user_id, arg):
    if not _is_int(arg):
        await send_message(session, chat_id, "Usage: `/unbanuser <user_id>`")
        return
    if await unban_user(db, int(arg)):
        await send_message(session, chat_id, f"✅ Unbanned user `{arg}`")
    else:
        await send_message(session, chat_id, "⚠️ Not found")


async def _cmd_listbanned(session, db, message, chat_id, user_id, arg):
    banned = await list_banned(db)
    if not banned:
        await send_message(session, chat_id, "✅ No banned users.")
        return
    lines = [f"⛔ *Banned Users ({len(banned)})*"]
    for b in banned:
        reason = b.get("reason") or "no reason"
        lines.append(f"• `{b['_id']}` — {reason}")
    await _send_long(session, chat_id, "\n".join(lines))


# ── Bot control ──────────────────────────────────────────────────────────────

async def _cmd_maintenance(session, db, message, chat_id, user_id, arg):
    mode = arg.strip().lower()
    if mode == "on":
        await set_maintenance(db, True)
        await send_message(session, chat_id, "🔧 Maintenance mode: *ON* — bot closed for non-admins")
    elif mode == "off":
        await set_maintenance(db, False)
        await send_message(session, chat_id, "✅ Maintenance mode: *OFF* — bot is live")
    else:
        await send_message(session, chat_id, "Usage: `/maintenance on`  |  `/maintenance off`")


async def _cmd_clearbroadcastlock(session, db, message, chat_id, user_id, arg):
    """
    H3 escape hatch: a broadcast killed mid-send by the platform's function
    timeout never reaches release_broadcast_lock, leaving the lock stuck until
    it ages past BROADCAST_LOCK_TTL_SECONDS (broadcast_engine.py). This clears
    it immediately instead of waiting. Defaults to the caller's own lock;
    pass a user_id to clear a different admin's stuck lock.
    """
    target = int(arg) if _is_int(arg) else user_id
    await release_broadcast_lock(db, target)
    await send_message(session, chat_id, f"✅ Broadcast lock cleared for `{target}`.")


async def _cmd_dbstats(session, db, message, chat_id, user_id, arg):
    s = await get_db_stats(db)
    if not s:
        await send_message(session, chat_id, "❌ Could not read database stats.")
        return
    text = (
        "📊 *Database Stats*\n"
        "```\n"
        f"👥 Users:     {s.get('users', 0):>6,}\n"
        f"🎵 Audio:     {s.get('files', 0):>6,}\n"
        f"📄 PDFs:      {s.get('pdfs', 0):>6,}\n"
        f"🎧 Playlists: {s.get('playlists', 0):>6,}\n"
        f"⛔ Banned:    {s.get('banned', 0):>6,}\n"
        f"👤 Co-Admins: {s.get('admins', 0):>6,}\n"
        "```"
    )
    await send_message(session, chat_id, text)


# ── Export ───────────────────────────────────────────────────────────────────

async def _cmd_exportalldb(session, db, message, chat_id, user_id, arg):
    users = await get_all_users_for_export(db)
    date  = datetime.now().strftime("%Y-%m-%d")

    header_lines = [
        f"# Al-Madih users export — {date} — {len(users)} users",
        "user_id,first_name,joined_at,last_active,total_plays,favorites_count,state",
    ]
    rows = []
    for u in users:
        rows.append(",".join([
            _csv_field(u.get("_id", "")),
            _csv_field(u.get("first_name", "")),
            _csv_field(_fmt_dt(u.get("joined_at"))),
            _csv_field(_fmt_dt(u.get("last_active"))),
            _csv_field(u.get("total_plays", 0)),
            _csv_field(len(u.get("favorites", []))),
            _csv_field(u.get("state", "") or ""),
        ]))
    content  = ("\n".join(header_lines + rows) + "\n").encode("utf-8")
    filename = f"almadih_users_export_{date}.txt"

    res = await send_document_bytes(session, chat_id, filename, content, caption=f"📦 Al-Madih export — {len(users)} users")
    if res and res.get("ok"):
        await send_message(session, chat_id, f"✅ Exported {len(users)} users")
    else:
        await send_message(session, chat_id, "❌ Export failed. Please retry.")


# ── confirmation callbacks (del_audio_* / del_pdf_*) ──────────────────────────

async def handle_admin_delete_callback(session, db, data_str, chat_id, message_id, cb_id) -> None:
    if data_str in ("del_audio_cancel", "del_pdf_cancel"):
        await edit_message_text(session, chat_id, message_id, "❌ Cancelled.")
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("del_audio_confirm_"):
        doc_id = data_str[len("del_audio_confirm_"):]
        name   = await delete_audio_by_id(db, doc_id)
        if name is not None:
            await edit_message_text(session, chat_id, message_id, f"🗑 Deleted: `{name}`")
        else:
            await edit_message_text(session, chat_id, message_id, "⚠️ Audio not found (already deleted?).")
        await answer_callback_query(session, cb_id)
        return

    if data_str.startswith("del_pdf_confirm_"):
        oid   = data_str[len("del_pdf_confirm_"):]
        title = await delete_pdf_by_id(db, oid)
        if title is not None:
            await edit_message_text(session, chat_id, message_id, f"🗑 PDF deleted: `{title}`")
        else:
            await edit_message_text(session, chat_id, message_id, "⚠️ PDF not found.")
        await answer_callback_query(session, cb_id)
        return

    await answer_callback_query(session, cb_id)


# command name → handler (defined after all handlers exist)
_COMMANDS = {
    "/addadmin":    _cmd_addadmin,
    "/removeadmin": _cmd_removeadmin,
    "/listadmins":  _cmd_listadmins,
    "/editaudio":   _cmd_editaudio,
    "/deleteaudio": _cmd_deleteaudio,
    "/unhide":      _cmd_unhide,
    "/findaudio":   _cmd_findaudio,
    "/editpdf":     _cmd_editpdf,
    "/removepdf":   _cmd_removepdf,
    "/listpdfs":    _cmd_listpdfs,
    "/userinfo":    _cmd_userinfo,
    "/banuser":     _cmd_banuser,
    "/unbanuser":   _cmd_unbanuser,
    "/listbanned":  _cmd_listbanned,
    "/maintenance": _cmd_maintenance,
    "/dbstats":     _cmd_dbstats,
    "/clearbroadcastlock": _cmd_clearbroadcastlock,
    "/exportalldb": _cmd_exportalldb,
}
