#!/usr/bin/env python3
"""
scripts/genre_tag.py — auto-detect genre from audio title keywords.

Same approach as the neshida detection: scan display_name for genre keywords
(Amharic or Latin spelling, case-insensitive) and set the `genre` field where a
keyword matches. Only touches UNTAGGED docs (genre missing/null) so manual tags
are never overwritten; docs with no keyword match are left untagged.

DRY-RUN by default (counts only, no writes). Pass --confirm APPLY to write.
Reports per-genre counts after running. Env: MONGO_URL.

  python scripts/genre_tag.py                 # preview counts, no writes
  python scripts/genre_tag.py --confirm APPLY # set genre where keywords match
"""
import os
import sys
import argparse

try:
    from pymongo import MongoClient
except Exception as e:  # pragma: no cover
    print(f"FATAL: pymongo not installed: {e}", file=sys.stderr)
    sys.exit(1)

DB_NAME = "MenzumaDB"
MONGO_URL = os.environ.get("MONGO_URL")
CONFIRM_TOKEN = "APPLY"

# genre -> case-insensitive title regex (Amharic | Latin), priority order.
GENRE_PATTERNS = [
    ("eshq",    "ኢሽቅ|eshq"),
    ("abret",   "አብሬት|abret"),
    ("katbare", "ቃጥባሬ|katbare"),
    ("raya",    "የራያ|raya"),
]


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Auto-tag audio genre from title keywords (dry-run unless --confirm APPLY).")
    ap.add_argument("--confirm", default="", help='Must be "APPLY" to write; otherwise dry-run counts only.')
    args = ap.parse_args()
    write_enabled = (args.confirm.strip() == CONFIRM_TOKEN)

    if not MONGO_URL:
        print("FATAL: MONGO_URL not set", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"FATAL: cannot connect to MongoDB: {e}", file=sys.stderr)
        sys.exit(1)
    db = client[DB_NAME]

    print(f"===== MODE: {'APPLY (writes)' if write_enabled else 'DRY-RUN (no writes)'} =====")

    # Q5: the admin panel now also stores genre as an EMPTY array ([]) for "no
    # category selected" (multi-category support), not just missing/null. A
    # plain `{"genre": None}` filter doesn't match an empty array in Mongo
    # (distinct BSON types), so those docs would silently never get
    # auto-tagged. $in covers both shapes; an already-tagged doc (a real
    # string or a non-empty array) still isn't touched either way.
    UNTAGGED = {"$in": [None, []]}

    counts = {}
    for genre, pattern in GENRE_PATTERNS:
        # Untagged audio whose title matches this genre's keyword. The UNTAGGED
        # clause means an already-tagged doc — manual or set by an earlier
        # genre in this loop — is never overwritten (first match wins).
        flt = {
            "file_id": {"$exists": True},
            "genre": UNTAGGED,
            "display_name": {"$regex": pattern, "$options": "i"},
        }
        if write_enabled:
            res = db.files.update_many(flt, {"$set": {"genre": genre}})
            counts[genre] = res.modified_count
        else:
            counts[genre] = db.files.count_documents(flt)
        print(f"  {genre:8} ({pattern}) -> {counts[genre]}")

    total = sum(counts.values())
    untagged = db.files.count_documents({"file_id": {"$exists": True}, "genre": UNTAGGED})
    print("\n===== SUMMARY =====")
    for g, c in counts.items():
        print(f"{g:8}: {c}")
    print(f"matched total: {total}")
    print(f"still untagged: {untagged}")
    if not write_enabled:
        print("DRY-RUN — no docs changed. Re-run with --confirm APPLY to set genre.")
    else:
        print("APPLIED — genre set on matched untagged docs (existing tags untouched).")
    client.close()


if __name__ == "__main__":
    main()
