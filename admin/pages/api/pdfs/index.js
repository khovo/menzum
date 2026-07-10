/**
 * GET /api/pdfs?page=1&search=&hidden=true       — paginated list (20/page)
 *     `hidden=true` lists ONLY soft-deleted items (for the admin panel's
 *     Hidden tab — see the matching note in api/audio/index.js; the
 *     public/app-facing endpoints are untouched and keep excluding hidden
 *     docs unconditionally). Any other value (or omitted) keeps the
 *     existing default: only visible items.
 *
 * Uploads are handled by POST /api/pdfs/presign, NOT a POST here — this
 * route USED to accept a multipart upload directly, but that pushed the
 * file bytes through this Vercel function's own request body, which hits
 * Vercel's platform-level payload limit (the "Request Entity Too Large" /
 * H9 bug). Deleted rather than left as dead code so nothing accidentally
 * calls back into the exact path that bug came from.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");

const PAGE_SIZE = 20;

async function handleGet(req, res, db) {
  const page = Math.max(1, parseInt(req.query.page, 10) || 1);
  const search = (req.query.search || "").trim();

  const filter = req.query.hidden === "true" ? { hidden: true } : { hidden: { $ne: true } };
  if (search) {
    filter.title = { $regex: search.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), $options: "i" };
  }

  const [items, total] = await Promise.all([
    db.collection("pdfs")
      .find(filter)
      .sort({ _id: -1 })
      .skip((page - 1) * PAGE_SIZE)
      .limit(PAGE_SIZE)
      .toArray(),
    db.collection("pdfs").countDocuments(filter),
  ]);

  return res.status(200).json({
    ok: true,
    items: items.map((d) => ({
      id: d._id.toString(),
      title: d.title || "Untitled",
      description: d.description || null,
      size_bytes: d.size_bytes || null,
      mimetype: d.mimetype || null,
      download_count: d.download_count || 0,
      hidden: !!d.hidden,
      hidden_bot: !!d.hidden_bot,
      hidden_app: !!d.hidden_app,
      status: d.status || "published",
      has_r2: !!d.r2_url,
      has_telegram: !!d.file_id,
      r2_url: d.r2_url || null,
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
    console.error("api/pdfs/index.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

module.exports.default = module.exports;
