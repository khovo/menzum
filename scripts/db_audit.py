#!/usr/bin/env python3
"""
scripts/db_audit.py — Al-Madih DRY-RUN database audit (READ-ONLY).

Does NOT modify MongoDB or send any Telegram messages. It only:
  A) EXPORT  — dumps all audio + all PDFs to CSV (reliable backup).
  B) HEALTH  — Telegram getFile on every file_id (OK / SHORT / TOO_BIG / BROKEN).
  C) TITLES  — Gemini suggestions for audio titles (artist / clean title /
               is_real_menzuma / genre). SUGGESTIONS ONLY — never written back.
  D) REPORT  — audit-report.csv with a recommended_action per item.
  E) SUMMARY — totals + counts per status to stdout.

Env: MONGO_URL (required), BOT_TOKEN (required for health), GEMINI_API_KEY
(optional; titles are left blank if missing). Usage: python scripts/db_audit.py [--limit 50]
"""
import os
import sys
import csv
import json
import time
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash-latest")

# ── Telegram getFile rate limiting ────────────────────────────────────────────
TG_MAX_PER_SEC = 15
TG_MIN_GAP = 1.0 / TG_MAX_PER_SEC      # ~0.067s between calls
GEMINI_BATCH = 30
GEMINI_GAP = 4.0                       # delay between Gemini batches (free-tier RPM)
_last_tg_call = [0.0]


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
        if e.code == 429 and attempt < 5:
            retry_after = int(body.get("parameters", {}).get("retry_after", 3))
            print(f"[429] getFile rate-limited, sleeping {retry_after}s (attempt {attempt+1}) file_id={str(file_id)[:12]}…")
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


# ── C) TITLES (Gemini, batched) ───────────────────────────────────────────────
def _empty_suggestion(title):
    return {"artist": "", "clean_title": title, "is_real_menzuma": "", "genre_guess": "unknown"}


def gemini_batch(titles, attempt=0):
    """Return a list of suggestion dicts (one per title). Never raises."""
    if not GEMINI_API_KEY:
        return [_empty_suggestion(t) for t in titles]

    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    prompt = (
        "You analyze Amharic Islamic audio titles (menzuma/nasheed). For EACH numbered "
        "title return one JSON object. Reply with ONLY a JSON array, same order, no prose.\n"
        "Each object: {\"artist\": string, \"clean_title\": string, "
        "\"is_real_menzuma\": boolean, \"genre_guess\": one of "
        "[\"eshq\",\"abret\",\"katbare\",\"raya\",\"unknown\"]}.\n"
        "- artist = reciter name if present in the title, else \"\".\n"
        "- clean_title = title with filenames (e.g. 'sh selman 3.mp3'), channel tags and "
        "emojis stripped.\n"
        "- is_real_menzuma = false if it is a filename, speech/conversation, or has no real "
        "title; true otherwise.\n\nTitles:\n" + numbered
    )
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "response_mime_type": "application/json"},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1].lstrip("json").strip() if "```" in text else text
        arr = json.loads(text)
        out = []
        for i, t in enumerate(titles):
            o = arr[i] if i < len(arr) and isinstance(arr[i], dict) else {}
            out.append({
                "artist": str(o.get("artist", "") or ""),
                "clean_title": str(o.get("clean_title", t) or t),
                "is_real_menzuma": o.get("is_real_menzuma", ""),
                "genre_guess": str(o.get("genre_guess", "unknown") or "unknown"),
            })
        return out
    except urllib.error.HTTPError as e:
        if e.code == 429 and attempt < 4:
            print(f"[429] Gemini rate-limited, sleeping 30s (attempt {attempt+1})")
            time.sleep(30)
            return gemini_batch(titles, attempt + 1)
        print(f"[gemini FAIL] HTTP {e.code} — leaving {len(titles)} titles blank")
        return [_empty_suggestion(t) for t in titles]
    except Exception as e:
        print(f"[gemini ERROR] {e} — leaving {len(titles)} titles blank")
        return [_empty_suggestion(t) for t in titles]


def analyze_titles(titles):
    results = []
    for start in range(0, len(titles), GEMINI_BATCH):
        chunk = titles[start:start + GEMINI_BATCH]
        results.extend(gemini_batch(chunk))
        print(f"[TITLES] analyzed {min(start + GEMINI_BATCH, len(titles))}/{len(titles)}")
        if start + GEMINI_BATCH < len(titles):
            time.sleep(GEMINI_GAP)
    return results


def recommended_action(status, is_real_menzuma):
    if status in ("BROKEN", "TOO_BIG"):
        return "HIDE"
    if status == "SHORT" or is_real_menzuma is False:
        return "REVIEW"
    return "KEEP"


def main():
    ap = argparse.ArgumentParser(description="Al-Madih DRY-RUN DB audit (read-only).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Health/title/audit only the first N of each collection (0 = all). Export is always full.")
    args = ap.parse_args()

    if not MONGO_URL:
        print("FATAL: MONGO_URL not set", file=sys.stderr)
        sys.exit(1)
    if not BOT_TOKEN:
        print("WARN: BOT_TOKEN not set — health checks will all report BROKEN")
    if not GEMINI_API_KEY:
        print("WARN: GEMINI_API_KEY not set — title suggestions left blank")

    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    started = datetime.now(timezone.utc).isoformat()
    print(f"[START] {started}  limit={args.limit or 'ALL'}  model={GEMINI_MODEL}")

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
    for d in audit_audio:
        status, detail = health_check(d, is_audio=True)
        audio_health.append((d, status, detail))
        add_status(status)
    pdf_health = []
    for d in audit_pdfs:
        status, detail = health_check(d, is_audio=False)
        pdf_health.append((d, status, detail))
        add_status(status)

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
