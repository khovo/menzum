/**
 * api/webapp/auth.js
 * ------------------
 * POST /api/webapp/auth
 *
 * The Mini App calls this endpoint on startup to:
 *   1. Prove its initData is valid (so the server trusts the user_id)
 *   2. Receive back the user's profile (name, baraka_points, favorites count)
 *      needed to render the header and personalise the home screen
 *
 * This is the ONLY endpoint that accepts initData in the request BODY
 * (because the Mini App calls it before it has a user object to put in the header).
 * All other endpoints use the Authorization header via the withAuth middleware.
 *
 * REQUEST:
 *   POST /api/webapp/auth
 *   Content-Type: application/json
 *   { "initData": "<raw initData string from window.Telegram.WebApp.initData>" }
 *
 * RESPONSE 200:
 *   {
 *     "ok": true,
 *     "user": {
 *       "id": 123456789,
 *       "first_name": "Ahmed",
 *       "favorites_count": 12,
 *       "baraka_points": 0
 *     }
 *   }
 *
 * RESPONSE 401:
 *   { "ok": false, "error": "Hash mismatch — invalid initData." }
 */

const { validateInitData } = require("./_auth");
const { connectToDatabase } = require("./_db");

module.exports = async function handler(req, res) {
  // CORS
  res.setHeader("Access-Control-Allow-Origin",  "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const { initData } = req.body || {};
  const { valid, user: tgUser, error } = validateInitData(initData);

  if (!valid) {
    return res.status(401).json({ ok: false, error });
  }

  // Fetch the user's existing data from MongoDB (favorites count, points, etc.)
  try {
    const { db } = await connectToDatabase();
    const userId  = parseInt(tgUser.id, 10);

    const dbUser  = await db.collection("users").findOne(
      { _id: userId },
      { projection: { favorites: 1, baraka_points: 1 } }
    );

    return res.status(200).json({
      ok:   true,
      user: {
        id:             userId,
        first_name:     tgUser.first_name  || "User",
        last_name:      tgUser.last_name   || "",
        username:       tgUser.username    || null,
        favorites_count: dbUser?.favorites?.length ?? 0,
        baraka_points:   dbUser?.baraka_points      ?? 0,
      },
    });

  } catch (err) {
    console.error("auth.js DB error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
};
