/**
 * POST /api/notifications/send   { message, target: "all"|"app"|"bot", dry_run? }
 *
 * Sends a Telegram sendMessage broadcast to users, reimplementing
 * handlers/broadcast_engine.py's _execute_broadcast chunking / throttling /
 * circuit-breaker pattern in JS (same constants: 25-message chunks, a short
 * sleep between sends, abort after 10 consecutive non-429 failures). The
 * Python bot's own broadcast_engine.py is untouched — this is a separate,
 * simpler broadcast path (plain text only, no BML markup) that runs from
 * the admin panel's own Vercel project.
 *
 * Requires PERMISSIONS.NOTIFICATIONS.
 *
 * CAUTION: this runs synchronously inside one serverless invocation — there
 * is no background job queue in this codebase to hand a long broadcast off
 * to. On a large user base it can approach the function's execution time
 * limit; `maxDuration` below raises the cap where the hosting plan allows
 * it, but very large audiences should be sent with a narrower `target` or
 * split up manually.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { PERMISSIONS } = require("../../../lib/roles");

const BOT_TOKEN = process.env.BOT_TOKEN;
const CHUNK_SIZE = 25;
const CHUNK_SLEEP_MS = 25;
const CIRCUIT_BREAKER = 10;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function sendMessage(chatId, text) {
  const res = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "Markdown" }),
  });
  return res.json();
}

module.exports = withAdminAuth(async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }
  if (!BOT_TOKEN) {
    return res.status(503).json({ ok: false, error: "BOT_TOKEN not configured." });
  }

  const { message, target = "all", dry_run } = req.body || {};
  if (!message || !String(message).trim()) {
    return res.status(400).json({ ok: false, error: "Message text is required." });
  }
  if (!["all", "app", "bot"].includes(target)) {
    return res.status(400).json({ ok: false, error: "target must be one of: all, app, bot." });
  }

  try {
    const { db } = await connectToDatabase();
    const filter = target === "app" ? { source: "app" } : target === "bot" ? { source: { $ne: "app" } } : {};
    const userDocs = await db.collection("users").find(filter, { projection: { _id: 1 } }).toArray();
    const userIds = userDocs.map((u) => u._id);

    if (dry_run) {
      return res.status(200).json({ ok: true, dry_run: true, targetCount: userIds.length });
    }

    let delivered = 0;
    let failed = 0;
    let consecutive = 0;
    let aborted = false;

    for (let i = 0; i < userIds.length; i++) {
      if (consecutive >= CIRCUIT_BREAKER) {
        aborted = true;
        break;
      }
      const uid = userIds[i];
      try {
        let result = await sendMessage(uid, message);
        if (result.ok === false) {
          const errCode = result.error_code || 0;
          if (errCode === 429) {
            const retryAfter = (result.parameters && result.parameters.retry_after) || 5;
            // eslint-disable-next-line no-await-in-loop
            await sleep(retryAfter * 1000);
            // eslint-disable-next-line no-await-in-loop
            result = await sendMessage(uid, message);
            if (result.ok) { delivered += 1; consecutive = 0; } else { failed += 1; consecutive += 1; }
          } else if (errCode === 400 || errCode === 403) {
            // Blocked bot / chat not found — a per-user dead end, not a
            // systemic failure, so it doesn't feed the circuit breaker.
            failed += 1;
            consecutive = 0;
          } else {
            failed += 1;
            consecutive += 1;
          }
        } else {
          delivered += 1;
          consecutive = 0;
        }
      } catch (err) {
        failed += 1;
        consecutive += 1;
      }

      // eslint-disable-next-line no-await-in-loop
      if ((i + 1) % CHUNK_SIZE === 0) await sleep(CHUNK_SLEEP_MS * CHUNK_SIZE);
      // eslint-disable-next-line no-await-in-loop
      else await sleep(CHUNK_SLEEP_MS);
    }

    return res.status(200).json({
      ok: true,
      delivered,
      failed,
      targetCount: userIds.length,
      aborted,
    });
  } catch (err) {
    console.error("api/notifications/send.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
}, { permission: PERMISSIONS.NOTIFICATIONS });

module.exports.default = module.exports;
// Raise the execution time budget where the hosting plan honors it (Vercel
// Hobby caps at 10s regardless; Pro defaults to 60s but allows more).
module.exports.config = { maxDuration: 60 };
