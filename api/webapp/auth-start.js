/**
 * api/webapp/auth-start.js
 * ------------------------
 * POST /api/webapp/auth-start   (no auth — this is how login begins)
 *
 * Step 1 of the mobile "Login with Telegram" flow.
 *   - Generates a one-time `nonce` and stores it (status: "pending").
 *   - Returns a Telegram deep link `t.me/<bot>?start=login_<nonce>`.
 * The app opens the deep link; when the user taps Start, the bot links the nonce
 * to their Telegram identity. The app then polls /api/webapp/auth-poll.
 *
 * RESPONSE 200:
 *   { "ok": true, "nonce": "ab12…", "deep_link": "https://t.me/Almadihbot?start=login_ab12…", "expires_in": 600 }
 */
const { connectToDatabase } = require("./_db");
const { setCors } = require("./_auth");
const crypto = require("crypto");

const BOT_USERNAME = process.env.BOT_USERNAME || "Almadihbot";

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const { db } = await connectToDatabase();
    const nonce = crypto.randomBytes(8).toString("hex"); // 16 hex chars

    await db.collection("login_sessions").insertOne({
      _id: nonce,
      status: "pending",
      created_at: new Date(),
    });

    return res.status(200).json({
      ok: true,
      nonce,
      deep_link: `https://t.me/${BOT_USERNAME}?start=login_${nonce}`,
      expires_in: 600, // seconds (10 minutes)
    });
  } catch (err) {
    console.error("auth-start.js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
};
