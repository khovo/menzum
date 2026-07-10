/**
 * POST /api/pdfs/presign  { title, description, filename, contentType }
 *
 * Bug 2 / H9 fix: replaces uploading the file THROUGH this function's body
 * (which hit Vercel's platform-level request size limit — "Request Entity
 * Too Large" — well below the file sizes admins actually need to upload).
 * This endpoint only creates the draft `pdfs` doc and hands back a
 * presigned R2 PUT URL; the browser then PUTs the raw file bytes directly
 * to R2 (see lib/uploadClient.js), never touching this function again.
 *
 * The doc is created WITHOUT r2_url — instead `pending_key` records where
 * the object will land once the direct-to-R2 PUT actually succeeds.
 * PATCH /api/pdfs/:id { field: "_upload_complete" } (see [id].js) resolves
 * pending_key into r2_url. This two-step handshake means a browser upload
 * that never completes leaves a harmless empty draft (visible/cleanable via
 * the Hidden tab) rather than a doc pointing at a file that doesn't exist.
 */
const path = require("path");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { getPresignedUploadUrl } = require("../../../lib/r2");
const { ALLOWED_EXTENSIONS } = require("../../../lib/pdfTypes");

module.exports = withAdminAuth(async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const { title, description, filename } = req.body || {};
    if (!title || !String(title).trim()) {
      return res.status(400).json({ ok: false, error: "Title is required." });
    }
    if (!filename) {
      return res.status(400).json({ ok: false, error: "A file is required." });
    }

    const ext = path.extname(filename).slice(1).toLowerCase();
    const canonicalMime = ALLOWED_EXTENSIONS[ext];
    if (!canonicalMime) {
      return res.status(400).json({
        ok: false,
        error: `Unsupported file type ".${ext || "?"}" — allowed: ${Object.keys(ALLOWED_EXTENSIONS).map((e) => "." + e).join(", ")}.`,
      });
    }

    const { db } = await connectToDatabase();
    const now = new Date();
    const insertResult = await db.collection("pdfs").insertOne({
      title: String(title).trim(),
      description: description ? String(description).trim() : null,
      file_id: null,
      mimetype: canonicalMime,
      hidden: false,
      hidden_bot: false,
      hidden_app: false,
      status: "draft",
      download_count: 0,
      created_at: now,
    });
    const docId = insertResult.insertedId;
    const key = `pdfs/${docId}.${ext}`;

    await db.collection("pdfs").updateOne({ _id: docId }, { $set: { pending_key: key } });

    const uploadUrl = await getPresignedUploadUrl("pdf", key, canonicalMime);
    return res.status(200).json({ ok: true, id: docId.toString(), uploadUrl });
  } catch (err) {
    console.error("api/pdfs/presign.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

module.exports.default = module.exports;
