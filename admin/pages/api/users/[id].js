/**
 * GET /api/users/:id           — detail: profile, listen history, favorites
 * PUT /api/users/:id  { action: "ban"|"unban", reason? }
 *     Writes to the `banned_users` collection (ban_user/unban_user in db.py),
 *     NOT a `banned` field on the user doc — this is what the bot's
 *     is_banned() actually checks, so Ban/Unban here has real effect.
 */
const { ObjectId } = require("mongodb");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");

async function handleGet(req, res, db, userId) {
  const user = await db.collection("users").findOne({ _id: userId });
  if (!user) {
    return res.status(404).json({ ok: false, error: "User not found." });
  }

  const [bannedDoc, favTracks, favPdfs] = await Promise.all([
    db.collection("banned_users").findOne({ _id: userId }),
    (user.favorites || []).length
      ? db.collection("files")
          .find({ file_id: { $in: user.favorites } }, { projection: { display_name: 1 } })
          .toArray()
      : [],
    (user.pdf_favorites || []).length
      ? db.collection("pdfs")
          .find(
            {
              _id: {
                $in: (user.pdf_favorites || [])
                  .map((x) => { try { return new ObjectId(x); } catch { return null; } })
                  .filter(Boolean),
              },
            },
            { projection: { title: 1 } }
          )
          .toArray()
      : [],
  ]);

  return res.status(200).json({
    ok: true,
    user: {
      id: user._id,
      first_name: user.first_name || "Unknown",
      joined_at: user.joined_at || null,
      last_active: user.last_active || null,
      total_plays: user.total_plays || 0,
      state: user.state || "idle",
      banned: !!bannedDoc,
      ban_reason: bannedDoc?.reason || null,
      banned_at: bannedDoc?.banned_at || null,
    },
    listen_history: (user.listen_history || []).map((h) => ({
      track_id: h.track_id,
      name: h.name,
      played_at: h.played_at,
    })),
    favorites: favTracks.map((t) => ({ id: t._id.toString(), name: t.display_name || "Unknown" })),
    pdf_favorites: favPdfs.map((p) => ({ id: p._id.toString(), title: p.title || "Untitled" })),
  });
}

async function handlePut(req, res, db, userId) {
  const { action, reason } = req.body || {};
  if (action === "ban") {
    await db.collection("banned_users").updateOne(
      { _id: userId },
      {
        $set: { reason: reason || "", banned_by: "admin_panel" },
        $setOnInsert: { banned_at: new Date() },
      },
      { upsert: true }
    );
    return res.status(200).json({ ok: true, banned: true });
  }
  if (action === "unban") {
    await db.collection("banned_users").deleteOne({ _id: userId });
    return res.status(200).json({ ok: true, banned: false });
  }
  return res.status(400).json({ ok: false, error: 'action must be "ban" or "unban".' });
}

module.exports = withAdminAuth(async function handler(req, res) {
  const idParam = req.query.id;
  const userId = parseInt(idParam, 10);
  if (!idParam || Number.isNaN(userId)) {
    return res.status(400).json({ ok: false, error: "Invalid user id." });
  }

  try {
    const { db } = await connectToDatabase();
    if (req.method === "GET") return handleGet(req, res, db, userId);
    if (req.method === "PUT") return handlePut(req, res, db, userId);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/users/[id].js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
