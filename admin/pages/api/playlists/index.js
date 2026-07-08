/**
 * GET /api/playlists?page=1&search=
 * Paginated list of user-created playlists (built via the bot's chat-based
 * playlist_builder flow — db.py's create_playlist()). Search matches the
 * playlist's short id or the creator's first_name.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { PERMISSIONS } = require("../../../lib/roles");

const PAGE_SIZE = 20;

async function handleGet(req, res, db) {
  const page = Math.max(1, parseInt(req.query.page, 10) || 1);
  const search = (req.query.search || "").trim();

  const filter = {};
  if (search) {
    filter._id = { $regex: search.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), $options: "i" };
  }

  const [items, total] = await Promise.all([
    db.collection("playlists")
      .find(filter)
      .sort({ created_at: -1 })
      .skip((page - 1) * PAGE_SIZE)
      .limit(PAGE_SIZE)
      .toArray(),
    db.collection("playlists").countDocuments(filter),
  ]);

  const creatorIds = [...new Set(items.map((p) => p.creator_id))];
  const creators = creatorIds.length
    ? await db.collection("users").find({ _id: { $in: creatorIds } }, { projection: { first_name: 1 } }).toArray()
    : [];
  const creatorMap = new Map(creators.map((c) => [c._id, c.first_name]));

  return res.status(200).json({
    ok: true,
    items: items.map((p) => ({
      id: p._id,
      title: p.title || null,
      creator_id: p.creator_id,
      creator_name: creatorMap.get(p.creator_id) || "Unknown",
      track_count: (p.tracks || []).length,
      play_count: p.play_count || 0,
      featured: !!p.featured,
      created_at: p.created_at || null,
    })),
    page,
    pageSize: PAGE_SIZE,
    total,
    totalPages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
  });
}

module.exports = withAdminAuth(async function handler(req, res) {
  try {
    const { db } = await connectToDatabase();
    if (req.method === "GET") return await handleGet(req, res, db);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/playlists/index.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
}, { permission: PERMISSIONS.PLAYLISTS });

module.exports.default = module.exports;
