/**
 * PUT    /api/audio/:id  (multipart: title, artist, category, thumbnail?)
 *        Edits metadata; thumbnail file is optional (only re-uploaded if sent).
 * PATCH  /api/audio/:id  (JSON: { field: "hidden"|"hidden_bot"|"hidden_app", value: boolean })
 *        Instant visibility toggle — see pages/api/pdfs/[id].js for what each
 *        field means. Reads its own JSON body manually (see note below).
 * DELETE /api/audio/:id
 *        Soft-delete only — sets hidden:true. Never removes the document.
 */
const { ObjectId } = require("mongodb");
const fs = require("fs");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { uploadToR2 } = require("../../../lib/r2");
const { parseForm, flat, flatFile, readJsonBody } = require("../../../lib/parseForm");
const { isValidCategorySlug } = require("../../../lib/categoryHelpers");

const TOGGLE_FIELDS = ["hidden", "hidden_bot", "hidden_app"];

async function handlePut(req, res, db, id) {
  const { fields, files } = await parseForm(req);
  const { title, artist, category } = flat(fields);
  const thumbFile = flatFile(files, "thumbnail");

  // genre is stored as an array — the edit form's multi-select checkboxes
  // send the chosen slugs joined by commas.
  const genres = category !== undefined
    ? category.split(",").map((c) => c.trim()).filter(Boolean)
    : undefined;
  if (genres) {
    for (const g of genres) {
      if (!(await isValidCategorySlug(db, g))) {
        return res.status(400).json({ ok: false, error: `Unknown category "${g}". Create it first on the Categories page.` });
      }
    }
  }

  const update = {};
  if (title !== undefined && title.trim()) update.display_name = title.trim();
  if (artist !== undefined) update.artist = artist.trim() || null;
  if (genres !== undefined) update.genre = genres;

  if (thumbFile) {
    const thumbBuf = fs.readFileSync(thumbFile.filepath);
    const thumbExt = (thumbFile.originalFilename || "").split(".").pop() || "jpg";
    update.thumb_url = await uploadToR2("audio", `audio/thumbs/${id}.${thumbExt}`, thumbBuf, thumbFile.mimetype);
  }

  if (Object.keys(update).length === 0) {
    return res.status(400).json({ ok: false, error: "Nothing to update." });
  }

  const result = await db.collection("files").updateOne({ _id: new ObjectId(id) }, { $set: update });
  if (result.matchedCount === 0) {
    return res.status(404).json({ ok: false, error: "Track not found." });
  }
  return res.status(200).json({ ok: true });
}

async function handlePatch(req, res, db, id) {
  // This route disables Next.js's default body parser (config.api.bodyParser
  // = false below) so PUT's multipart thumbnail upload can reach formidable
  // un-consumed — but that setting applies to every method on this route, so
  // a JSON PATCH request has to parse its own body instead of using req.body.
  const body = await readJsonBody(req);
  const { field, value } = body || {};

  if (!TOGGLE_FIELDS.includes(field)) {
    return res.status(400).json({ ok: false, error: `field must be one of: ${TOGGLE_FIELDS.join(", ")}` });
  }
  if (typeof value !== "boolean") {
    return res.status(400).json({ ok: false, error: "value must be a boolean." });
  }

  const update = { [field]: value };
  if (field === "hidden") {
    update.hidden_reason = value ? "admin_panel" : null;
    update.hidden_at = value ? new Date() : null;
  }

  const result = await db.collection("files").updateOne({ _id: new ObjectId(id) }, { $set: update });
  if (result.matchedCount === 0) {
    return res.status(404).json({ ok: false, error: "Track not found." });
  }
  return res.status(200).json({ ok: true, [field]: value });
}

async function handleDelete(req, res, db, id) {
  const result = await db.collection("files").updateOne(
    { _id: new ObjectId(id) },
    { $set: { hidden: true, hidden_reason: "admin_panel", hidden_at: new Date() } }
  );
  if (result.matchedCount === 0) {
    return res.status(404).json({ ok: false, error: "Track not found." });
  }
  return res.status(200).json({ ok: true });
}

module.exports = withAdminAuth(async function handler(req, res) {
  const { id } = req.query;
  if (!id || id.length !== 24) {
    return res.status(400).json({ ok: false, error: "Invalid id." });
  }

  try {
    const { db } = await connectToDatabase();
    // Awaiting these matters — see pages/api/pdfs/index.js for why a bare
    // `return handleX(...)` lets errors escape this try/catch as an HTML 500.
    if (req.method === "PUT") return await handlePut(req, res, db, id);
    if (req.method === "PATCH") return await handlePatch(req, res, db, id);
    if (req.method === "DELETE") return await handleDelete(req, res, db, id);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/audio/[id].js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

module.exports.default = module.exports;
module.exports.config = { api: { bodyParser: false } };
