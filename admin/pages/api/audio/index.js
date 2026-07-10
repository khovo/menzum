/**
 * GET /api/audio?page=1&search=&category=&hidden=true   — paginated list (20/page)
 *     `hidden=true` lists ONLY soft-deleted items (for the admin panel's
 *     Hidden tab — this route is withAdminAuth-gated, so this is never
 *     reachable by the public app-facing endpoints in api/webapp/*.js,
 *     which keep their own separate, unconditional hidden:{$ne:true}
 *     filters untouched). Any other value (or omitted) keeps the existing
 *     default: only visible items.
 *
 * Uploads are handled by POST /api/audio/presign, NOT a POST here — see
 * the identical note in pages/api/pdfs/index.js: this route used to accept
 * a multipart upload directly, which pushed the file bytes through this
 * Vercel function's own request body and hit Vercel's platform-level
 * payload limit (the H9 bug). Deleted rather than left as dead code.
 *
 * `category` accepts any of the 5 fixed genre slugs (lib/categories.js) OR a
 * custom category created via /api/categories — see lib/categoryHelpers.js.
 *
 * NOTE ON VISIBILITY: uploads here are R2-native and have no Telegram
 * `file_id`. The bot's own catalog/search and the existing Mini App API
 * (api/webapp/featured.js, search.js, handlers/*.py) all filter on
 * `file_id` existing, so a track created here will NOT show up there until
 * those read paths are updated to also accept r2_url-only docs. This panel
 * itself manages such docs fully (list/edit/hide) regardless.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");

const PAGE_SIZE = 20;

async function handleGet(req, res, db) {
  const page = Math.max(1, parseInt(req.query.page, 10) || 1);
  const search = (req.query.search || "").trim();
  const category = (req.query.category || "").trim();

  const filter = req.query.hidden === "true" ? { hidden: true } : { hidden: { $ne: true } };
  if (search) {
    filter.display_name = { $regex: search.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), $options: "i" };
  }
  if (category) {
    filter.genre = category;
  }

  const [items, total] = await Promise.all([
    db.collection("files")
      .find(filter)
      .sort({ _id: -1 })
      .skip((page - 1) * PAGE_SIZE)
      .limit(PAGE_SIZE)
      .toArray(),
    db.collection("files").countDocuments(filter),
  ]);

  return res.status(200).json({
    ok: true,
    items: items.map((d) => ({
      id: d._id.toString(),
      display_name: d.display_name || "Unknown",
      artist: d.artist || null,
      genre: d.genre || null,
      play_count: d.play_count || 0,
      hidden: !!d.hidden,
      hidden_bot: !!d.hidden_bot,
      hidden_app: !!d.hidden_app,
      status: d.status || "published",
      has_r2: !!d.r2_url,
      has_telegram: !!d.file_id,
      r2_url: d.r2_url || null,
      thumb_url: d.thumb_url || null,
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
    console.error("api/audio/index.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

// Next.js's production API route runtime requires `.default` specifically —
// a bare CommonJS `module.exports = fn` alone isn't picked up at request time
// (only at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
