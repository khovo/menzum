/**
 * api/webapp/categories.js
 * -------------------------
 * GET /api/webapp/categories
 *
 * Returns the 5 fixed genre categories plus any custom categories created in
 * the admin panel (stored in the `categories` collection), sorted by
 * `sort_order` ascending. Fixed categories default to their canonical order
 * (0-4) and custom ones default to appending after them unless the admin
 * panel's up/down reorder buttons have set an explicit `sort_order`.
 *
 * Categories the admin has hidden (via the Categories page — works for BOTH
 * fixed and custom slugs, since fixed ones can never be deleted, only
 * hidden) are excluded entirely from this response. This does not affect
 * which tracks exist or their genre tag — a track tagged with a hidden
 * category stays tagged and remains reachable under the "all"/no-category
 * view; it's only removed from the category *picker* itself.
 *
 * RESPONSE 200:
 *   { "ok": true, "categories": [{ "slug", "display_name", "sort_order" }, ...] }
 */
const { withOptionalAuth } = require("./_auth");
const { connectToDatabase } = require("./_db");

// Mirrors admin/lib/categories.js — duplicated here (not imported) because
// admin/ is a separate Vercel project/deployment from this one.
const FIXED_SLUGS = ["neshida", "eshq", "abret", "katbare", "raya"];
const DEFAULT_LABELS = {
  neshida: "Neshida",
  eshq: "Eshq",
  abret: "Abret",
  katbare: "Katbare",
  raya: "Raya",
};

module.exports = withOptionalAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const { db } = await connectToDatabase();
    const allDocs = await db.collection("categories").find({}).toArray();

    const docMap = {};
    for (const d of allDocs) docMap[d._id] = d;
    const customSlugs = allDocs.map((d) => d._id).filter((slug) => !FIXED_SLUGS.includes(slug));
    const allSlugs = [...FIXED_SLUGS, ...customSlugs];

    const categories = allSlugs
      .filter((slug) => !docMap[slug]?.hidden)
      .map((slug) => {
        const isFixed = FIXED_SLUGS.includes(slug);
        const defaultOrder = isFixed ? FIXED_SLUGS.indexOf(slug) : FIXED_SLUGS.length + customSlugs.indexOf(slug);
        return {
          slug,
          display_name: docMap[slug]?.display_name || DEFAULT_LABELS[slug] || slug,
          sort_order: docMap[slug]?.sort_order ?? defaultOrder,
        };
      })
      .sort((a, b) => a.sort_order - b.sort_order);

    return res.status(200).json({ ok: true, categories });
  } catch (err) {
    console.error("categories.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});
