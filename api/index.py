"""
api/index.py
------------
Vercel Serverless Entry Point.

This file is intentionally dumb — it does ONE job: receive HTTP from Vercel,
hand the JSON payload to process_telegram_update(), and return 'ok'.

Rules for keeping this file this thin:
  ✅  Import and call — nothing else.
  ❌  No business logic here.
  ❌  No DB calls here.
  ❌  No Telegram API calls here.
  ❌  No webhook setup calls (Vercel handles routing via vercel.json).

Why api/index.py specifically?
  Vercel's Python runtime looks for a callable named `app` (or a handler)
  inside api/index.py by convention.  Placing our Flask app here means
  vercel.json can route /* → api/index.py cleanly.
"""
import sys
import os
import hmac
import logging

# ---------------------------------------------------------------------------
# Path fix: allow `import config`, `import handlers`, etc. from the project
# root when Vercel executes this file from the /api subdirectory.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request
from config import TELEGRAM_WEBHOOK_SECRET
from handlers import process_telegram_update
from utils import run_async

logging.basicConfig(level=logging.ERROR)

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
@app.route("/api/webhook", methods=["GET", "POST"])
def telegram_webhook():
    if request.method == "POST":
        # Telegram echoes back whatever secret_token was set via setWebhook on
        # every update it delivers. Without this check, anyone who finds this
        # URL can POST a hand-crafted Update — including one claiming
        # from.id == ADMIN_ID — and it gets processed as a real admin command.
        # Fails closed: a missing/unset secret rejects every request rather
        # than silently skipping the check, so misconfiguration can't degrade
        # into "no auth" the way it did before this fix.
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not TELEGRAM_WEBHOOK_SECRET or not hmac.compare_digest(provided, TELEGRAM_WEBHOOK_SECRET):
            logging.warning("Webhook request rejected: missing or invalid secret token")
            return "unauthorized", 401

        try:
            data = request.get_json(force=True)
            if data:
                run_async(process_telegram_update(data))
            return "ok", 200
        except Exception:
            logging.exception("Webhook handler error")
            return "error", 500

    # GET — health check / status page
    return "Al-Madih Bot Running ⚡🚀", 200


# Local development runner
if __name__ == "__main__":
    app.run(debug=True, port=5000)
