/**
 * GET /api/users?page=1&search=
 * Paginated user list (20/page). Ban status is resolved from the separate
 * `banned_users` collection (matching the bot's own is_banned() check in
 * db.py) — NOT a `banned` field on the user doc, so this stays consistent
 * with what the bot actually enforces.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");

const PAGE_SIZE = 20;

module.exports = withAdminAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const { db } = await connectToDatabase();
    const page = Math.max(1, parseInt(req.query.page, 10) || 1);
    const search = (req.query.search || "").trim();

    const filter = {};
    if (search) {
      filter.first_name = { $regex: search.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), $options: "i" };
    }

    const [items, total] = await Promise.all([
      db.collection("users")
        .find(filter)
        .sort({ _id: -1 })
        .skip((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .toArray(),
      db.collection("users").countDocuments(filter),
    ]);

    const ids = items.map((u) => u._id);
    const bannedDocs = ids.length
      ? await db.collection("banned_users").find({ _id: { $in: ids } }, { projection: { _id: 1 } }).toArray()
      : [];
    const bannedSet = new Set(bannedDocs.map((b) => b._id));

    return res.status(200).json({
      ok: true,
      items: items.map((u) => ({
        id: u._id,
        first_name: u.first_name || "Unknown",
        joined_at: u.joined_at || null,
        last_active: u.last_active || null,
        total_plays: u.total_plays || 0,
        favorites_count: (u.favorites || []).length,
        banned: bannedSet.has(u._id),
      })),
      page,
      pageSize: PAGE_SIZE,
      total,
      totalPages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
    });
  } catch (err) {
    console.error("api/users/index.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
