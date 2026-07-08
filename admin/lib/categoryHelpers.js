/**
 * lib/categoryHelpers.js
 * -----------------------
 * Server-only helpers for the fixed-5-plus-custom category model. Deliberately
 * kept out of lib/categories.js: that file is imported from client components
 * too (for the plain CATEGORY_SLUGS/DEFAULT_LABELS constants), and pulling
 * `lib/db.js` (mongodb) into that same module would drag mongodb into the
 * browser bundle. Only import this file from API routes.
 *
 * Custom categories live in the same `categories` collection as the fixed
 * slugs' display-name overrides, distinguished by `custom: true` and an _id
 * that isn't one of CATEGORY_SLUGS.
 */
const { CATEGORY_SLUGS, DEFAULT_LABELS } = require("./categories");

/**
 * Validate a user-submitted name for a NEW custom category. The slug IS the
 * display name as typed (trimmed) — no charset restriction, so Amharic,
 * Arabic, or any other script works the same as Latin text.
 */
function validateNewSlug(slug) {
  if (!slug || typeof slug !== "string" || !slug.trim()) return "Name is required.";
  if (CATEGORY_SLUGS.includes(slug.trim())) {
    return `"${slug.trim()}" is one of the fixed categories already.`;
  }
  return null;
}

/**
 * Fixed + custom categories, each with a live track count from `files.genre`
 * and a sort_order (explicit if set via the reorder buttons, else a sensible
 * default — fixed slugs keep their canonical 0-4 order, custom ones append
 * after). Sorted ascending by sort_order, same as api/webapp/categories.js.
 */
async function listAllCategories(db) {
  const allDocs = await db.collection("categories").find({}).toArray();
  const docMap = {};
  for (const d of allDocs) docMap[d._id] = d;
  const customSlugs = allDocs.map((d) => d._id).filter((slug) => !CATEGORY_SLUGS.includes(slug));
  const allSlugs = [...CATEGORY_SLUGS, ...customSlugs];

  const counts = await Promise.all(allSlugs.map((slug) => db.collection("files").countDocuments({ genre: slug })));

  const categories = allSlugs.map((slug, i) => {
    const isFixed = CATEGORY_SLUGS.includes(slug);
    const defaultOrder = isFixed ? CATEGORY_SLUGS.indexOf(slug) : CATEGORY_SLUGS.length + customSlugs.indexOf(slug);
    return {
      slug,
      display_name: docMap[slug]?.display_name || DEFAULT_LABELS[slug] || slug,
      track_count: counts[i],
      custom: !isFixed,
      sort_order: docMap[slug]?.sort_order ?? defaultOrder,
    };
  });

  return categories.sort((a, b) => a.sort_order - b.sort_order);
}

/** True if `slug` is either a fixed category or an existing custom one. */
async function isValidCategorySlug(db, slug) {
  if (!slug) return true; // category is optional on audio docs
  if (CATEGORY_SLUGS.includes(slug)) return true;
  const doc = await db.collection("categories").findOne({ _id: slug });
  return !!doc;
}

module.exports = { validateNewSlug, listAllCategories, isValidCategorySlug };
