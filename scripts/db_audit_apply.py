#!/usr/bin/env python3
"""
scripts/db_audit_apply.py — APPLY step for the Al-Madih audit.

This is the ONLY script allowed to write to MongoDB, and only a SOFT-DELETE:
it sets {hidden: true} (never deletes documents). Writes happen ONLY when run
with --confirm APPLY; any other value (or none) is a dry-run preview that makes
zero DB changes.

Flow (reuses db_audit.py logic):
  0) EXPORT backup first — full-export-audio.csv + full-export-pdfs.csv (safety net).
  1) HEALTH check every audio + PDF (Telegram getFile).
  2) TOO_BIG / BROKEN  -> soft-delete: $set hidden=true (+ reason/time). Logged
     to hidden-log.csv BEFORE the change (audit trail).
  3) REVIEW (audio with is_real_menzuma=false) -> NOT touched; written to
     review-needed.csv for manual decision later.
  4) Summary to stdout.

Env: MONGO_URL, BOT_TOKEN.  Usage:
  python scripts/db_audit_apply.py                 # dry-run preview (no writes)
  python scripts/db_audit_apply.py --confirm APPLY # actually sets hidden=true
"""
import os
import sys
import csv
import argparse
import time
from datetime import datetime, timezone

# Reuse the validated read-only audit logic (same dir).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_audit as audit  # noqa: E402

try:
    from pymongo import MongoClient
except Exception as e:  # pragma: no cover
    print(f"FATAL: pymongo not installed: {e}", file=sys.stderr)
    sys.exit(1)

CONFIRM_TOKEN = "APPLY"


def _write_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[ARTIFACT] {path}: {len(rows)} rows", flush=True)


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Al-Madih audit APPLY (soft-delete; write-guarded).")
    ap.add_argument("--confirm", default="",
                    help='Must be exactly "APPLY" to write hidden=true. Anything else = dry-run preview.')
    ap.add_argument("--limit", type=int, default=0, help="Process first N per collection (0 = all). Export is always full.")
    ap.add_argument("--max-seconds", type=int, default=1500, help="Overall safeguard deadline.")
    args = ap.parse_args()

    write_enabled = (args.confirm.strip() == CONFIRM_TOKEN)

    if not audit.MONGO_URL:
        print("FATAL: MONGO_URL not set", file=sys.stderr)
        sys.exit(1)
    if not audit.BOT_TOKEN:
        print("WARN: BOT_TOKEN not set — every item would look BROKEN; refusing to apply.")
        if write_enabled:
            print("FATAL: refusing to hide everything because BOT_TOKEN is missing.", file=sys.stderr)
            sys.exit(1)

    mode = "APPLY (writes enabled)" if write_enabled else "DRY-RUN (no DB writes)"
    print(f"===== MODE: {mode} =====", flush=True)

    if args.max_seconds and args.max_seconds > 0:
        audit._DEADLINE[0] = time.monotonic() + args.max_seconds

    client = MongoClient(audit.MONGO_URL, serverSelectionTimeoutMS=10000,
                         connectTimeoutMS=10000, socketTimeoutMS=120000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"FATAL: cannot connect to MongoDB: {e}", file=sys.stderr)
        sys.exit(1)
    db = client[audit.DB_NAME]
    now = datetime.now(timezone.utc)

    # 0) EXPORT backup first (always).
    audio_docs = audit.export_collection(db.files, "full-export-audio.csv")
    pdf_docs = audit.export_collection(db.pdfs, "full-export-pdfs.csv")

    audit_audio = audio_docs[:args.limit] if args.limit else audio_docs
    audit_pdfs = pdf_docs[:args.limit] if args.limit else pdf_docs

    hidden_rows, review_rows = [], []
    hidden_count = 0

    def process(docs, coll, is_audio, title_key):
        nonlocal hidden_count
        kind = "audio" if is_audio else "pdf"
        for i, d in enumerate(docs, 1):
            if audit._past_deadline():
                print(f"[{kind}] deadline reached at {i}/{len(docs)} — stopping early", flush=True)
                break
            title = str(d.get(title_key) or d.get("file_name") or "")
            status, detail = audit.health_check(d, is_audio=is_audio)
            doc_id = str(d.get("_id"))

            if status in ("TOO_BIG", "BROKEN"):
                action = "HIDDEN" if write_enabled else "WOULD_HIDE"
                # Log BEFORE changing (audit trail).
                print(f"[{action}] {kind} id={doc_id} status={status} title={title!r} detail={detail!r}", flush=True)
                hidden_rows.append({"type": kind, "id": doc_id, "title": title,
                                    "health_status": status, "detail": detail, "action": action})
                if write_enabled:
                    coll.update_one(
                        {"_id": d["_id"]},
                        {"$set": {"hidden": True, "hidden_reason": status, "hidden_at": now}},
                    )
                    hidden_count += 1
            elif is_audio and audit.is_real_menzuma(title) is False:
                # Soft "needs review" — NEVER auto-hidden.
                review_rows.append({"type": kind, "id": doc_id, "title": title,
                                    "health_status": status,
                                    "artist_guess": audit.guess_artist(title),
                                    "clean_title_suggestion": audit.clean_title(title) or title,
                                    "reason": "is_real_menzuma=false"})
            if i % audit.PROGRESS_EVERY == 0:
                print(f"[{kind}] {i}/{len(docs)}", flush=True)

    print(f"[HEALTH] processing {len(audit_audio)} audio + {len(audit_pdfs)} pdfs…", flush=True)
    process(audit_audio, db.files, True, "display_name")
    process(audit_pdfs, db.pdfs, False, "title")

    _write_csv("hidden-log.csv",
               ["type", "id", "title", "health_status", "detail", "action"], hidden_rows)
    _write_csv("review-needed.csv",
               ["type", "id", "title", "health_status", "artist_guess", "clean_title_suggestion", "reason"], review_rows)

    print("\n===== SUMMARY =====")
    print(f"Mode:                 {mode}")
    print(f"Audio/PDF audited:    {len(audit_audio)} / {len(audit_pdfs)}")
    print(f"Hide candidates:      {len(hidden_rows)} (TOO_BIG/BROKEN)")
    print(f"Actually hidden now:  {hidden_count}")
    print(f"Review-needed (kept): {len(review_rows)}")
    if not write_enabled:
        print('DRY-RUN — no documents changed. Re-run with --confirm APPLY to soft-delete.')
    else:
        print("APPLIED — soft-deleted via hidden=true (no documents removed).")
    client.close()


if __name__ == "__main__":
    main()
