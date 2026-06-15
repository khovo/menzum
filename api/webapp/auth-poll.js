/**
 * api/webapp/auth-poll.js
 * -----------------------
 * POST /api/webapp/auth-poll   (no auth — exchanges a nonce for a token)
 *
 * Step 2 of the mobile "Login with Telegram" flow. The app calls this every few
 * seconds with the nonce from auth-start until the user has tapped Start in the
 * bot.
 *
 * REQUEST:  { "nonce": "ab12…" }
 *
 * RESPONSE 200 (still waiting):  { "ok": true, "status": "pending" }
 * RESPONSE 200 (linked):
 *   { "ok": true, "status": "linked", "token": "<jwt>",
 *     "user": { "id": 123, "first_name": "Ahmed", "username": "ahmed", "photo_url": null } }
 * RESPONSE 404: unknown nonce · 410: expired · 503: JWT_SECRET not set
 *
 * On success the nonce is consumed (deleted). The JWT is valid for 90 days.
 */
const { connectToDatabase } = require("./_db");
const { setCors } = require("./_auth");
const { sign, isConfigured } = require("./_jwt");

const NONCE_TTL_MS = 10 * 60 * 1000; // 10 minutes

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }
  if (!isConfigured()) {
    return res.status(503).json({ ok: false, error: "JWT_SECRET not configured on server." });
  }

  const { nonce } = req.body || {};
  if (!nonce || typeof nonce !== "string") {
    return res.status(400).json({ ok: false, error: "Missing nonce." });
  }

  try {
    const { db } = await connectToDatabase();
    const doc = await db.collection("login_sessions").findOne({ _id: nonce });

    if (!doc) {
      return res.status(404).json({ ok: false, error: "Unknown or already-used login code." });
    }
    if (Date.now() - new Date(doc.created_at).getTime() > NONCE_TTL_MS) {
      await db.collection("login_sessions").deleteOne({ _id: nonce });
      return res.status(410).json({ ok: false, error: "Login request expired. Please try again." });
    }
    if (doc.status !== "linked" || !doc.user_id) {
      return res.status(200).json({ ok: true, status: "pending" });
    }

    // Linked → issue token and consume the nonce.
    const token = sign({ uid: doc.user_id });
    await db.collection("login_sessions").deleteOne({ _id: nonce });

    return res.status(200).json({
      ok: true,
      status: "linked",
      token,
      user: {
        id: doc.user_id,
        first_name: doc.first_name || "User",
        username: doc.username || null,
        photo_url: doc.photo_url || null,
      },
    });
  } catch (err) {
    console.error("auth-poll.js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
};
