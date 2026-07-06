/**
 * GET  /api/categories        — the 5 fixed slugs + any custom categories,
 *                                 each with editable display name + track count
 * POST   /api/categories  { display_name }        — create a new custom category
 *          (slug is the display name as typed, trimmed only — any script/charset)
 * PUT    /api/categories  { slug, display_name }  — rename a fixed or custom slug
 * DELETE /api/categories?slug=xxx                 — remove a custom category
 *          (fixed categories can never be deleted, only renamed)
 *
 * Not in the original API route spec, but the /categories page needs a data
 * source — added as the minimal necessary route. Display-name overrides (and
 * custom categories themselves) are stored in a small `categories` collection
 * ({_id: slug, display_name, ...}); the 5 fixed slugs are still hardcoded in
 * lib/categories.js and can never be deleted here, only renamed.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { CATEGORY_SLUGS } = require("../../../lib/categories");
const { validateNewSlug, listAllCategories, isValidCategorySlug } = require("../../../lib/categoryHelpers");

async function handleGet(req, res, db) {
  const categories = await listAllCategories(db);
  return res.status(200).json({ ok: true, categories });
}

async function handlePost(req, res, db) {
  const { display_name } = req.body || {};
  // The slug IS the display name as typed, trimmed only — no lowercasing or
  // charset restriction, so Amharic/Arabic/any script names work as-is.
  const slug = String(display_name || "").trim();

  const slugError = validateNewSlug(slug);
  if (slugError) {
    return res.status(400).json({ ok: false, error: slugError });
  }

  const existing = await db.collection("categories").findOne({ _id: slug });
  if (existing) {
    return res.status(409).json({ ok: false, error: `Category "${slug}" already exists.` });
  }

  await db.collection("categories").insertOne({
    _id: slug,
    slug,
    display_name: slug,
    created_at: new Date(),
    custom: true,
  });
  return res.status(201).json({ ok: true, slug });
}

async function handleDelete(req, res, db) {
  const slug = (req.query.slug || "").trim();
  if (!slug) {
    return res.status(400).json({ ok: false, error: "slug is required." });
  }
  if (CATEGORY_SLUGS.includes(slug)) {
    return res.status(400).json({ ok: false, error: "Fixed categories cannot be deleted." });
  }
  const result = await db.collection("categories").deleteOne({ _id: slug });
  if (result.deletedCount === 0) {
    return res.status(404).json({ ok: false, error: "Category not found." });
  }
  return res.status(200).json({ ok: true });
}

async function handlePut(req, res, db) {
  const { slug, display_name } = req.body || {};
  if (!(await isValidCategorySlug(db, slug))) {
    return res.status(400).json({
      ok: false,
      error: `Invalid slug. Must be one of the fixed categories (${CATEGORY_SLUGS.join(", ")}) or an existing custom category.`,
    });
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
    // NOTE: these awaits matter — `return handleX(...)` without awaiting would
    // let a rejection inside handleX escape this try/catch (it only rejects
    // *after* the synchronous `return` already exited the try block), which
    // surfaces to the client as Next.js's default HTML error page instead of
    // JSON. See pages/api/pdfs/index.js for the write-up of this bug.
    if (req.method === "GET") return await handleGet(req, res, db);
    if (req.method === "POST") return await handlePost(req, res, db);
    if (req.method === "PUT") return await handlePut(req, res, db);
    if (req.method === "DELETE") return await handleDelete(req, res, db);
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
