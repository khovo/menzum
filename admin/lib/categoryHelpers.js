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

/** Fixed + custom categories, each with a live track count from `files.genre`. */
async function listAllCategories(db) {
  const customDocs = await db.collection("categories").find({ _id: { $nin: CATEGORY_SLUGS } }).toArray();
  const allSlugs = [...CATEGORY_SLUGS, ...customDocs.map((d) => d._id)];

  const [overrides, counts] = await Promise.all([
    db.collection("categories").find({ _id: { $in: CATEGORY_SLUGS } }).toArray(),
    Promise.all(allSlugs.map((slug) => db.collection("files").countDocuments({ genre: slug }))),
  ]);
  const overrideMap = {};
  for (const o of overrides) overrideMap[o._id] = o.display_name;

  return allSlugs.map((slug, i) => ({
    slug,
    display_name: overrideMap[slug] || DEFAULT_LABELS[slug] || slug,
    track_count: counts[i],
    custom: !CATEGORY_SLUGS.includes(slug),
  }));
}

/** True if `slug` is either a fixed category or an existing custom one. */
async function isValidCategorySlug(db, slug) {
  if (!slug) return true; // category is optional on audio docs
  if (CATEGORY_SLUGS.includes(slug)) return true;
  const doc = await db.collection("categories").findOne({ _id: slug });
  return !!doc;
}

module.exports = { validateNewSlug, listAllCategories, isValidCategorySlug };
