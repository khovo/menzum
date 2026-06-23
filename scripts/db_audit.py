#!/usr/bin/env python3
"""
scripts/db_audit.py — Al-Madih DRY-RUN database audit (READ-ONLY).

Does NOT modify MongoDB or send any Telegram messages. It only:
  A) EXPORT  — dumps all audio + all PDFs to CSV (reliable backup).
  B) HEALTH  — Telegram getFile on every file_id (OK / SHORT / TOO_BIG / BROKEN).
  C) TITLES  — rule-based suggestions for audio titles (artist / clean title /
               is_real_menzuma; genre stays manual). No network, no API keys.
  D) REPORT  — audit-report.csv with a recommended_action per item.
  E) SUMMARY — totals + counts per status to stdout.

Env: MONGO_URL (required), BOT_TOKEN (required for health).
Usage: python scripts/db_audit.py [--limit 50]
"""
import os
import sys
import csv
import json
import time
import signal
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone

try:
    from pymongo import MongoClient
except Exception as e:  # pragma: no cover
    print(f"FATAL: pymongo not installed: {e}", file=sys.stderr)
    sys.exit(1)

DB_NAME = "MenzumaDB"
MONGO_URL = os.environ.get("MONGO_URL")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ── Telegram getFile rate limiting ────────────────────────────────────────────
TG_MAX_PER_SEC = 15
TG_MIN_GAP = 1.0 / TG_MAX_PER_SEC      # ~0.067s between calls
TG_MAX_RETRIES = 4                     # cap 429 retries per getFile
TG_RETRY_CAP = 60                      # never sleep more than this on a single 429
PROGRESS_EVERY = 25                    # print a progress line every N items
_last_tg_call = [0.0]
_DEADLINE = [None]                     # monotonic time after which we stop processing


def _past_deadline():
    return _DEADLINE[0] is not None and time.monotonic() > _DEADLINE[0]


def _csv_safe(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


# ── A) EXPORT ─────────────────────────────────────────────────────────────────
def export_collection(coll, path):
    docs = list(coll.find({}))
    keys = []
    for d in docs:
        for k in d.keys():
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for d in docs:
            w.writerow({k: _csv_safe(d.get(k)) for k in keys})
    print(f"[EXPORT] {path}: {len(docs)} rows, {len(keys)} columns")
    return docs


# ── B) HEALTH (Telegram getFile, throttled, 429-aware) ────────────────────────
def telegram_getfile(file_id, attempt=0):
    """Return (ok, result_dict_or_None, error_text). Honors 429 retry_after."""
    if not BOT_TOKEN:
        return False, None, "BOT_TOKEN not set"

    # Throttle to <= TG_MAX_PER_SEC calls/sec.
    gap = time.monotonic() - _last_tg_call[0]
    if gap < TG_MIN_GAP:
        time.sleep(TG_MIN_GAP - gap)
    _last_tg_call[0] = time.monotonic()

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={urllib.parse.quote(str(file_id))}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok"):
            return True, data.get("result", {}), ""
        return False, None, data.get("description", "unknown error")
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            pass
        desc = body.get("description", f"HTTP {e.code}")
        if e.code == 429 and attempt < TG_MAX_RETRIES:
            retry_after = min(int(body.get("parameters", {}).get("retry_after", 3)), TG_RETRY_CAP)
            print(f"[429] getFile rate-limited, sleeping {retry_after}s (attempt {attempt+1}/{TG_MAX_RETRIES}) file_id={str(file_id)[:12]}…", flush=True)
            time.sleep(retry_after)
            return telegram_getfile(file_id, attempt + 1)
        print(f"[getFile FAIL] {desc} file_id={str(file_id)[:12]}…")
        return False, None, desc
    except Exception as e:
        print(f"[getFile ERROR] {e} file_id={str(file_id)[:12]}…")
        return False, None, str(e)


def health_check(doc, is_audio):
    """Return (status, detail). status in OK/SHORT/TOO_BIG/BROKEN."""
    file_id = doc.get("file_id")
    if not file_id:
        return "BROKEN", "no file_id"
    ok, result, err = telegram_getfile(file_id)
    if not ok:
        if "too big" in (err or "").lower():
            return "TOO_BIG", err
        return "BROKEN", err
    # OK. Audio SHORT flag uses a stored duration if the doc has one
    # (getFile does not return duration).
    if is_audio:
        dur = doc.get("duration")
        try:
            if dur is not None and float(dur) < 60:
                return "SHORT", f"duration={dur}s"
        except (TypeError, ValueError):
            pass
    return "OK", ""


# ── C) TITLES (rule-based heuristics — NO network, NO Gemini) ─────────────────
import re

_NOT_MENZUMA = (".mp3", "unknown", "coming soon", "በቅርብ ቀን ይጠብቁ")
_LETTER_RE = re.compile(r"[A-Za-zሀ-፿]")          # Latin + Ethiopic letters


def _empty_suggestion(title):
    return {"artist": "", "clean_title": title, "is_real_menzuma": "", "genre_guess": "unknown"}


def guess_artist(title):
    """Extract a reciter name from common markers, else ''."""
    t = title or ""
    m = re.search(r"\{([^}]+)\}", t)                       # { name }
    if m:
        return m.group(1).strip()
    m = re.search(r"\|\|?([^|]+?)\|\|?", t)                # |name| or ||name||
    if m and _LETTER_RE.search(m.group(1)):
        return m.group(1).strip()
    m = re.search(r"ማዲህ\s+([^\s|{}@]+(?:\s+[^\s|{}@]+)?)", t)   # "ማዲህ <name>"
    if m:
        return m.group(1).strip()
    m = re.search(r"\bby\s+([^\n|{}@]+)", t, re.I)         # "by <name>"
    if m:
        return m.group(1).strip()[:40]
    m = re.search(r"@(\w+)", t)                            # @handle
    if m:
        return m.group(1).strip()
    return ""


def is_real_menzuma(title):
    """False for filenames / placeholders / emoji-only titles; True otherwise."""
    t = (title or "").strip()
    low = t.lower()
    if any(tok in low for tok in _NOT_MENZUMA):
        return False
    if len(_LETTER_RE.findall(t)) < 3:                     # mostly emojis/symbols
        return False
    return True


def clean_title(title):
    """Strip emojis/symbols, @handles, and 'Find telegram ...' channel tags."""
    t = title or ""
    t = re.sub(r"@\w+", "", t)
    t = re.sub(r"find telegram.*$", "", t, flags=re.I)
    # keep letters/digits/space/Ethiopic + basic punctuation; drop emojis & symbols
    t = re.sub(r"[^\w\sሀ-፿.,!?'\"-]", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -|_.\t")
    return t.strip()


def analyze_titles(titles):
    """Pure, instant, offline classification — one dict per title."""
    out = []
    for t in titles:
        out.append({
            "artist": guess_artist(t),
            "clean_title": clean_title(t) or t,
            "is_real_menzuma": is_real_menzuma(t),
            "genre_guess": "unknown",   # genre tagging stays manual via the bot
        })
    return out


def recommended_action(status, is_real_menzuma):
    if status in ("BROKEN", "TOO_BIG"):
        return "HIDE"
    if status == "SHORT" or is_real_menzuma is False:
        return "REVIEW"
    return "KEEP"


def main():
    # Line-buffer stdout/stderr so progress shows live in CI (not only at the end).
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Al-Madih DRY-RUN DB audit (read-only).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Health/title/audit only the first N of each collection (0 = all). Export is always full.")
    ap.add_argument("--max-seconds", type=int, default=1500,
                    help="Overall safeguard: stop processing after this many seconds and write partial results (default 1500).")
    args = ap.parse_args()

    if not MONGO_URL:
        print("FATAL: MONGO_URL not set", file=sys.stderr)
        sys.exit(1)
    if not BOT_TOKEN:
        print("WARN: BOT_TOKEN not set — health checks will all report BROKEN")
    print("[TITLES] using offline rule-based heuristics (no Gemini, no network)")

    # Overall soft deadline (loops check it) + a hard SIGALRM backstop.
    if args.max_seconds and args.max_seconds > 0:
        _DEADLINE[0] = time.monotonic() + args.max_seconds
        if hasattr(signal, "SIGALRM"):
            def _hard_timeout(signum, frame):
                print(f"FATAL: hard timeout after {args.max_seconds + 120}s — aborting.", file=sys.stderr, flush=True)
                os._exit(2)
            signal.signal(signal.SIGALRM, _hard_timeout)
            signal.alarm(args.max_seconds + 120)  # backstop beyond the soft deadline

    # Fail fast if Mongo is unreachable instead of hanging.
    client = MongoClient(
        MONGO_URL,
        serverSelectionTimeoutMS=10000,
        connectTimeoutMS=10000,
        socketTimeoutMS=120000,
    )
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"FATAL: cannot connect to MongoDB: {e}", file=sys.stderr)
        sys.exit(1)
    db = client[DB_NAME]
    started = datetime.now(timezone.utc).isoformat()
    print(f"[START] {started}  limit={args.limit or 'ALL'}  max_seconds={args.max_seconds}")

    # A) EXPORT (always full — this is the backup)
    audio_docs = export_collection(db.files, "full-export-audio.csv")
    pdf_docs = export_collection(db.pdfs, "full-export-pdfs.csv")

    audit_audio = audio_docs[:args.limit] if args.limit else audio_docs
    audit_pdfs = pdf_docs[:args.limit] if args.limit else pdf_docs

    # B) HEALTH
    rows = []           # accumulated audit rows
    status_counts = {}

    def add_status(s):
        status_counts[s] = status_counts.get(s, 0) + 1

    print(f"[HEALTH] checking {len(audit_audio)} audio + {len(audit_pdfs)} pdfs…")
    audio_health = []
    for i, d in enumerate(audit_audio, 1):
        if _past_deadline():
            print(f"[HEALTH] deadline reached at audio {i}/{len(audit_audio)} — stopping early", flush=True)
            break
        status, detail = health_check(d, is_audio=True)
        audio_health.append((d, status, detail))
        add_status(status)
        if i % PROGRESS_EVERY == 0:
            print(f"[HEALTH] audio {i}/{len(audit_audio)}", flush=True)
    pdf_health = []
    for i, d in enumerate(audit_pdfs, 1):
        if _past_deadline():
            print(f"[HEALTH] deadline reached at pdf {i}/{len(audit_pdfs)} — stopping early", flush=True)
            break
        status, detail = health_check(d, is_audio=False)
        pdf_health.append((d, status, detail))
        add_status(status)
        if i % PROGRESS_EVERY == 0:
            print(f"[HEALTH] pdf {i}/{len(audit_pdfs)}", flush=True)

    # C) TITLES (audio only — menzuma analysis)
    titles = [str(d.get("display_name") or "") for d, _, _ in audio_health]
    suggestions = analyze_titles(titles) if titles else []

    # D) REPORT
    for i, (d, status, detail) in enumerate(audio_health):
        s = suggestions[i] if i < len(suggestions) else _empty_suggestion(titles[i])
        rows.append({
            "type": "audio",
            "id": str(d.get("_id", "")),
            "current_title": d.get("display_name", ""),
            "health_status": status,
            "artist_guess": s["artist"],
            "clean_title_suggestion": s["clean_title"],
            "is_real_menzuma": s["is_real_menzuma"],
            "genre_guess": s["genre_guess"],
            "recommended_action": recommended_action(status, s["is_real_menzuma"]),
        })
    for d, status, detail in pdf_health:
        rows.append({
            "type": "pdf",
            "id": str(d.get("_id", "")),
            "current_title": d.get("title", d.get("file_name", "")),
            "health_status": status,
            "artist_guess": "",
            "clean_title_suggestion": "",
            "is_real_menzuma": "",
            "genre_guess": "",
            "recommended_action": "HIDE" if status in ("BROKEN", "TOO_BIG") else "KEEP",
        })

    cols = ["type", "id", "current_title", "health_status", "artist_guess",
            "clean_title_suggestion", "is_real_menzuma", "genre_guess", "recommended_action"]
    with open("audit-report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("[REPORT] audit-report.csv:", len(rows), "rows")

    # E) SUMMARY
    action_counts = {}
    for r in rows:
        action_counts[r["recommended_action"]] = action_counts.get(r["recommended_action"], 0) + 1
    print("\n===== SUMMARY =====")
    print(f"Audio total: {len(audio_docs)} (audited {len(audit_audio)})")
    print(f"PDF total:   {len(pdf_docs)} (audited {len(audit_pdfs)})")
    print("Health status counts:", json.dumps(status_counts, sort_keys=True))
    print("Recommended actions: ", json.dumps(action_counts, sort_keys=True))
    print("DRY RUN — no database writes were performed.")
    client.close()


if __name__ == "__main__":
    main()
