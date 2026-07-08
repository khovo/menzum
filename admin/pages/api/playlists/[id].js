/**
 * GET    /api/playlists/:id                       — full detail incl. track list
 * PUT    /api/playlists/:id  { title?, featured? } — admin-only curation fields
 *        (the bot's own playlist schema — db.py's create_playlist() — has no
 *        `title`; this adds it as an additive, admin-panel-only field that
 *        existing bot reads simply ignore)
 * DELETE /api/playlists/:id                        — hard delete
 *
 * Unlike files/pdfs, playlists aren't covered by the soft-delete (`hidden`)
 * convention documented in CLAUDE.md — they're ephemeral, user-generated
 * share links rather than catalog content, so removing a spam/junk one
 * outright is the appropriate moderation action here.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { PERMISSIONS } = require("../../../lib/roles");

async function handleGet(req, res, db, id) {
  const doc = await db.collection("playlists").findOne({ _id: id });
  if (!doc) return res.status(404).json({ ok: false, error: "Playlist not found." });
  return res.status(200).json({
    ok: true,
    playlist: {
      id: doc._id,
      title: doc.title || null,
      creator_id: doc.creator_id,
      tracks: (doc.tracks || []).map((t) => ({ name: t.name || "Unknown" })),
      play_count: doc.play_count || 0,
      featured: !!doc.featured,
      created_at: doc.created_at || null,
    },
  });
}

async function handlePut(req, res, db, id) {
  const { title, featured } = req.body || {};
  const update = {};
  if (title !== undefined) update.title = title ? String(title).trim() : null;
  if (featured !== undefined) update.featured = !!featured;
  if (Object.keys(update).length === 0) {
    return res.status(400).json({ ok: false, error: "Nothing to update." });
  }
  const result = await db.collection("playlists").updateOne({ _id: id }, { $set: update });
  if (result.matchedCount === 0) return res.status(404).json({ ok: false, error: "Playlist not found." });
  return res.status(200).json({ ok: true });
}

async function handleDelete(req, res, db, id) {
  const result = await db.collection("playlists").deleteOne({ _id: id });
  if (result.deletedCount === 0) return res.status(404).json({ ok: false, error: "Playlist not found." });
  return res.status(200).json({ ok: true });
}

module.exports = withAdminAuth(async function handler(req, res) {
  const { id } = req.query;
  if (!id) return res.status(400).json({ ok: false, error: "Invalid id." });

  try {
    const { db } = await connectToDatabase();
    if (req.method === "GET") return await handleGet(req, res, db, id);
    if (req.method === "PUT") return await handlePut(req, res, db, id);
    if (req.method === "DELETE") return await handleDelete(req, res, db, id);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/playlists/[id].js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
}, { permission: PERMISSIONS.PLAYLISTS });

module.exports.default = module.exports;
