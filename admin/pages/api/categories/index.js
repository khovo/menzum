/**
 * GET /api/categories        — the 5 fixed slugs + editable display name + track count
 * PUT /api/categories  { slug, display_name }
 *
 * Not in the original API route spec, but the /categories page needs a data
 * source — added as the minimal necessary route. Display-name overrides are
 * stored in a small `categories` collection ({_id: slug, display_name}); the
 * slugs themselves are fixed (lib/categories.js), not user-creatable.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { CATEGORY_SLUGS, DEFAULT_LABELS } = require("../../../lib/categories");

async function handleGet(req, res, db) {
  const [overrides, counts] = await Promise.all([
    db.collection("categories").find({ _id: { $in: CATEGORY_SLUGS } }).toArray(),
    Promise.all(CATEGORY_SLUGS.map((slug) => db.collection("files").countDocuments({ genre: slug }))),
  ]);
  const overrideMap = {};
  for (const o of overrides) overrideMap[o._id] = o.display_name;

  return res.status(200).json({
    ok: true,
    categories: CATEGORY_SLUGS.map((slug, i) => ({
      slug,
      display_name: overrideMap[slug] || DEFAULT_LABELS[slug],
      track_count: counts[i],
    })),
  });
}

async function handlePut(req, res, db) {
  const { slug, display_name } = req.body || {};
  if (!CATEGORY_SLUGS.includes(slug)) {
    return res.status(400).json({ ok: false, error: `Invalid slug. Must be one of: ${CATEGORY_SLUGS.join(", ")}` });
  }
  if (!display_name || !String(display_name).trim()) {
    return res.status(400).json({ ok: false, error: "display_name is required." });
  }
  await db.collection("categories").updateOne(
    { _id: slug },
    { $set: { display_name: String(display_name).trim() } },
    { upsert: true }
  );
  return res.status(200).json({ ok: true });
}

module.exports = withAdminAuth(async function handler(req, res) {
  try {
    const { db } = await connectToDatabase();
    if (req.method === "GET") return handleGet(req, res, db);
    if (req.method === "PUT") return handlePut(req, res, db);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/categories/index.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
