/**
 * api/webapp/auth.js
 * ------------------
 * POST /api/webapp/auth   (one endpoint, several actions via the body `action`)
 *
 * Auth hub for the mobile app + the existing Mini App. Folded into a single
 * function to stay under Vercel Hobby's 12-function limit.
 *
 *  • { "action": "start" }                 → begin "Login with Telegram":
 *        returns { nonce, deep_link, expires_in }. App opens deep_link; the user
 *        taps Start in Telegram and the bot links the nonce to their account.
 *  • { "action": "poll", "nonce": "…" }    → poll until linked:
 *        { status: "pending" } | { status: "linked", token, user }
 *  • { "action": "refresh" }  (Bearer/tma) → { token }  (fresh 90-day JWT)
 *  • { "initData": "…" }   (no action)     → Mini App startup: returns profile
 *        (UNCHANGED — this is what the in-Telegram Mini App calls).
 *
 * No auth needed for start/poll. refresh needs a valid token/initData.
 */
const crypto = require("crypto");
const { connectToDatabase } = require("./_db");
const { validateInitData, setCors, resolveUser, jwtSign, jwtConfigured } = require("./_auth");

const BOT_USERNAME = process.env.BOT_USERNAME || "Almadihbot";
const NONCE_TTL_MS = 10 * 60 * 1000; // 10 minutes

module.exports = async function handler(req, res) {
  setCors(res);
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const body = req.body || {};
  const action = body.action;

  try {
    // ── action: start ────────────────────────────────────────────────────────
    if (action === "start") {
      const { db } = await connectToDatabase();
      const nonce = crypto.randomBytes(8).toString("hex");
      await db.collection("login_sessions").insertOne({
        _id: nonce, status: "pending", created_at: new Date(),
      });
      return res.status(200).json({
        ok: true,
        nonce,
        deep_link: `https://t.me/${BOT_USERNAME}?start=login_${nonce}`,
        expires_in: 600,
      });
    }

    // ── action: poll ─────────────────────────────────────────────────────────
    if (action === "poll") {
      if (!jwtConfigured()) {
        return res.status(503).json({ ok: false, error: "JWT_SECRET not configured on server." });
      }
      const nonce = body.nonce;
      if (!nonce || typeof nonce !== "string") {
        return res.status(400).json({ ok: false, error: "Missing nonce." });
      }
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
      const token = jwtSign({ uid: doc.user_id });
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
    }

    // ── action: refresh ──────────────────────────────────────────────────────
    if (action === "refresh") {
      if (!jwtConfigured()) {
        return res.status(503).json({ ok: false, error: "JWT_SECRET not configured on server." });
      }
      const user = resolveUser(req);
      if (!user) {
        return res.status(401).json({ ok: false, error: "Invalid or missing token." });
      }
      return res.status(200).json({ ok: true, token: jwtSign({ uid: parseInt(user.id, 10) }) });
    }

    // ── default: Mini App startup validation (unchanged) ──────────────────────
    const { initData } = body;
    const { valid, user: tgUser, error } = validateInitData(initData);
    if (!valid) {
      return res.status(401).json({ ok: false, error });
    }

    const { db } = await connectToDatabase();
    const userId = parseInt(tgUser.id, 10);
    const dbUser = await db.collection("users").findOne(
      { _id: userId },
      { projection: { favorites: 1, baraka_points: 1 } }
    );

    return res.status(200).json({
      ok: true,
      user: {
        id: userId,
        first_name: tgUser.first_name || "User",
        last_name: tgUser.last_name || "",
        username: tgUser.username || null,
        favorites_count: dbUser?.favorites?.length ?? 0,
        baraka_points: dbUser?.baraka_points ?? 0,
      },
    });
  } catch (err) {
    console.error("auth.js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
};
