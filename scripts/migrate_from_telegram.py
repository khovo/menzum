#!/usr/bin/env python3
"""
scripts/migrate_from_telegram.py — migrate audio + PDFs from Telegram to R2.

Downloads every file in `files` (audio) and `pdfs` from Telegram (via file_id),
uploads it to Cloudflare R2, and stamps the doc with a new `r2_url` field.
`file_id` is NEVER removed — this is purely additive, so the bot's existing
Telegram-delivery paths keep working unchanged.

SAFE TO RE-RUN: any doc that already has `r2_url` is skipped, so a partial or
interrupted run can just be re-run to pick up where it left off.

DRY-RUN by default (lists what would be migrated, touches nothing). Pass
--confirm APPLY to actually download/upload/write — same safety pattern as
scripts/db_audit_apply.py and scripts/genre_tag.py in this repo.

Env (via real environment or a local .env file — see .env.example):
  MONGO_URL, BOT_TOKEN,
  R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
  R2_BUCKET_NAME (default "almadih-files"), R2_PUBLIC_URL

Usage:
  python scripts/migrate_from_telegram.py                    # dry-run preview
  python scripts/migrate_from_telegram.py --confirm APPLY    # do the migration
  python scripts/migrate_from_telegram.py --confirm APPLY --limit 20   # test first
"""
import os
import sys
import time
import argparse
import urllib.request
import urllib.error
import urllib.parse
import io

try:
    from pymongo import MongoClient
except Exception as e:  # pragma: no cover
    print(f"FATAL: pymongo not installed: {e}", file=sys.stderr)
    sys.exit(1)

try:
    import boto3
    from botocore.config import Config as BotoConfig
except Exception as e:  # pragma: no cover
    print(f"FATAL: boto3 not installed ({e}). Install with: pip install boto3", file=sys.stderr)
    sys.exit(1)


# ── .env support (no extra dependency — only fills vars not already set) ─────
def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)


_load_dotenv()

DB_NAME = "MenzumaDB"
MONGO_URL = os.environ.get("MONGO_URL")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "almadih-files")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL")

CONFIRM_TOKEN = "APPLY"

# ── Telegram getFile rate limiting (same pattern as scripts/db_audit.py) ─────
TG_MAX_PER_SEC = 15
TG_MIN_GAP = 1.0 / TG_MAX_PER_SEC
TG_MAX_RETRIES = 4
TG_RETRY_CAP = 60
_last_tg_call = [0.0]

DEFAULT_EXT = {"audio": ".mp3", "pdf": ".pdf"}
CONTENT_TYPES = {
    ".mp3": "audio/mpeg", ".oga": "audio/ogg", ".ogg": "audio/ogg",
    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/mp4",
    ".wav": "audio/wav", ".opus": "audio/opus",
    ".pdf": "application/pdf",
}


def _throttle() -> None:
    gap = time.monotonic() - _last_tg_call[0]
    if gap < TG_MIN_GAP:
        time.sleep(TG_MIN_GAP - gap)
    _last_tg_call[0] = time.monotonic()


def telegram_get_file_path(file_id: str, attempt: int = 0):
    """Resolve file_id -> Telegram file_path. Returns (path, None) or (None, error)."""
    _throttle()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={urllib.parse.quote(str(file_id))}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok") and data.get("result", {}).get("file_path"):
            return data["result"]["file_path"], None
        return None, data.get("description", "unknown error")
    except urllib.error.HTTPError as e:
        body = {}
        try:
            import json
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            pass
        desc = body.get("description", f"HTTP {e.code}")
        if e.code == 429 and attempt < TG_MAX_RETRIES:
            retry_after = min(int(body.get("parameters", {}).get("retry_after", 3)), TG_RETRY_CAP)
            print(f"  [429] getFile rate-limited, sleeping {retry_after}s (attempt {attempt+1}/{TG_MAX_RETRIES})", flush=True)
            time.sleep(retry_after)
            return telegram_get_file_path(file_id, attempt + 1)
        return None, desc
    except Exception as e:
        return None, str(e)


def telegram_download(file_path: str):
    """Download the file bytes for a resolved Telegram file_path. Returns (bytes, None) or (None, error)."""
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            return resp.read(), None
    except Exception as e:
        return None, str(e)


def upload_to_r2(s3, key: str, data: bytes, content_type: str):
    s3.put_object(Bucket=R2_BUCKET_NAME, Key=key, Body=data, ContentType=content_type)
    return f"{R2_PUBLIC_URL.rstrip('/')}/{key}"


def migrate_collection(db, s3, coll_name: str, kind: str, title_field: str, limit: int, write_enabled: bool, index_start: int, index_total: int):
    coll = db[coll_name]
    query = {"file_id": {"$exists": True}, "r2_url": {"$exists": False}}
    docs = list(coll.find(query).limit(limit) if limit else coll.find(query))

    success, failed = [], []
    for doc in docs:
        idx = index_start + success.__len__() + failed.__len__() + 1
        title = str(doc.get(title_field) or "Untitled")[:60]
        file_id = doc["file_id"]

        file_path, err = telegram_get_file_path(file_id)
        if err:
            print(f"[{idx}/{index_total}] {title} → ❌ failed: getFile {err}", flush=True)
            failed.append((title, str(doc["_id"]), f"getFile: {err}"))
            continue

        ext = os.path.splitext(file_path)[1] or DEFAULT_EXT[kind]
        key = f"{'audio' if kind == 'audio' else 'pdfs'}/{doc['_id']}{ext}"
        content_type = CONTENT_TYPES.get(ext.lower(), "application/octet-stream")

        if not write_enabled:
            print(f"[{idx}/{index_total}] {title} → would upload to {key} (dry-run)", flush=True)
            success.append((title, str(doc["_id"])))
            continue

        data, err = telegram_download(file_path)
        if err:
            print(f"[{idx}/{index_total}] {title} → ❌ failed: download {err}", flush=True)
            failed.append((title, str(doc["_id"]), f"download: {err}"))
            continue

        try:
            r2_url = upload_to_r2(s3, key, data, content_type)
        except Exception as e:
            print(f"[{idx}/{index_total}] {title} → ❌ failed: R2 upload {e}", flush=True)
            failed.append((title, str(doc["_id"]), f"r2 upload: {e}"))
            continue

        try:
            # Additive only — file_id is NEVER touched, so Telegram delivery keeps working.
            coll.update_one({"_id": doc["_id"]}, {"$set": {"r2_url": r2_url}})
        except Exception as e:
            print(f"[{idx}/{index_total}] {title} → ❌ failed: db update {e}", flush=True)
            failed.append((title, str(doc["_id"]), f"db update: {e}"))
            continue

        print(f"[{idx}/{index_total}] {title} → uploaded ✅", flush=True)
        success.append((title, str(doc["_id"])))

    return success, failed


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Migrate Telegram-hosted audio/PDFs to Cloudflare R2 (dry-run unless --confirm APPLY).")
    ap.add_argument("--confirm", default="", help='Must be "APPLY" to actually download/upload/write. Otherwise dry-run preview only.')
    ap.add_argument("--limit", type=int, default=0, help="Process only the first N docs per collection (0 = all).")
    args = ap.parse_args()
    write_enabled = (args.confirm.strip() == CONFIRM_TOKEN)

    missing = [name for name, val in (
        ("MONGO_URL", MONGO_URL), ("BOT_TOKEN", BOT_TOKEN),
        ("R2_ENDPOINT_URL", R2_ENDPOINT_URL), ("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
        ("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY), ("R2_PUBLIC_URL", R2_PUBLIC_URL),
    ) if not val]
    if missing:
        print(f"FATAL: missing required env vars: {', '.join(missing)} (set them or put them in a .env file)", file=sys.stderr)
        sys.exit(1)

    print(f"===== MODE: {'APPLY (writes + uploads)' if write_enabled else 'DRY-RUN (no writes, no uploads)'} =====", flush=True)

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000, socketTimeoutMS=120000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"FATAL: cannot connect to MongoDB: {e}", file=sys.stderr)
        sys.exit(1)
    db = client[DB_NAME]

    s3 = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )

    audio_total = db.files.count_documents({"file_id": {"$exists": True}, "r2_url": {"$exists": False}})
    pdf_total = db.pdfs.count_documents({"file_id": {"$exists": True}, "r2_url": {"$exists": False}})
    audio_n = min(audio_total, args.limit) if args.limit else audio_total
    pdf_n = min(pdf_total, args.limit) if args.limit else pdf_total
    grand_total = audio_n + pdf_n
    print(f"Audio to migrate: {audio_n} (of {audio_total} pending)  |  PDFs to migrate: {pdf_n} (of {pdf_total} pending)", flush=True)

    audio_success, audio_failed = migrate_collection(
        db, s3, "files", "audio", "display_name", args.limit, write_enabled, 0, grand_total,
    )
    pdf_success, pdf_failed = migrate_collection(
        db, s3, "pdfs", "pdf", "title", args.limit, write_enabled, len(audio_success) + len(audio_failed), grand_total,
    )

    all_success = audio_success + pdf_success
    all_failed = audio_failed + pdf_failed

    print("\n===== SUMMARY =====")
    print(f"Mode: {'APPLY' if write_enabled else 'DRY-RUN'}")
    print(f"Total success: {len(all_success)}")
    print(f"Total failed:  {len(all_failed)}")
    if all_failed:
        print("\nFailed files:")
        for title, doc_id, reason in all_failed:
            print(f"  ❌ {title} (id={doc_id}) — {reason}")
    if not write_enabled:
        print("\nDRY-RUN — nothing was downloaded, uploaded, or written. Re-run with --confirm APPLY to migrate.")
    client.close()


if __name__ == "__main__":
    main()
