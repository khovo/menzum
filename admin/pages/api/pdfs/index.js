/**
 * GET  /api/pdfs?page=1&search=       — paginated list (20/page)
 * POST /api/pdfs  (multipart: title, description, pdf)  — no size limit
 *
 * Accepts documents beyond plain PDF (.doc/.docx/.txt/.epub) — this endpoint
 * was originally PDF-only in name but the "PDFs" section doubles as the
 * general document library, matching what the bot's own upload path accepts
 * for the `pdfs` collection.
 *
 * Same visibility caveat as api/audio/index.js: this creates R2-native docs
 * with no Telegram file_id, so they won't appear in the bot/Mini App's
 * existing PDF list until those read paths accept r2_url-only docs.
 */
const fs = require("fs");
const path = require("path");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { uploadToR2 } = require("../../../lib/r2");
const { parseForm, flat, flatFile } = require("../../../lib/parseForm");

const PAGE_SIZE = 20;

// Extension -> canonical MIME type, used both to validate the upload and as
// the R2 object's Content-Type (formidable's detected mimetype can be a
// generic "application/octet-stream" for less common formats like .epub).
const ALLOWED_EXTENSIONS = {
  pdf: "application/pdf",
  doc: "application/msword",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  txt: "text/plain",
  epub: "application/epub+zip",
};

async function handleGet(req, res, db) {
  const page = Math.max(1, parseInt(req.query.page, 10) || 1);
  const search = (req.query.search || "").trim();

  const filter = { hidden: { $ne: true } };
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

async function handlePost(req, res, db) {
  const { fields, files } = await parseForm(req, { maxFileSize: 1024 * 1024 * 1024 }); // no practical size limit (1GB safety cap)
  const { title, description } = flat(fields);
  const docFile = flatFile(files, "pdf");

  if (!title || !title.trim()) {
    return res.status(400).json({ ok: false, error: "Title is required." });
  }
  if (!docFile) {
    return res.status(400).json({ ok: false, error: "A file is required." });
  }

  const ext = path.extname(docFile.originalFilename || "").slice(1).toLowerCase();
  const canonicalMime = ALLOWED_EXTENSIONS[ext];
  if (!canonicalMime) {
    return res.status(400).json({
      ok: false,
      error: `Unsupported file type ".${ext || "?"}" — allowed: ${Object.keys(ALLOWED_EXTENSIONS).map((e) => "." + e).join(", ")}.`,
    });
  }

  const now = new Date();
  const insertResult = await db.collection("pdfs").insertOne({
    title: title.trim(),
    description: description ? description.trim() : null,
    file_id: null, // R2-native upload — see module note above
    mimetype: canonicalMime,
    hidden: false,
    hidden_bot: false,
    hidden_app: false,
    // New uploads start as a draft pending admin approval (content approval
    // workflow). NOTE: api/webapp/* read paths don't filter on `status` yet
    // — this is admin-panel-side state only until that's wired in.
    status: "draft",
    download_count: 0,
    created_at: now,
  });
  const docId = insertResult.insertedId;

  const buf = fs.readFileSync(docFile.filepath);
  const r2Url = await uploadToR2("pdf", `pdfs/${docId}.${ext}`, buf, canonicalMime);

  await db.collection("pdfs").updateOne(
    { _id: docId },
    { $set: { r2_url: r2Url, size_bytes: docFile.size || buf.length } }
  );

  return res.status(201).json({ ok: true, id: docId.toString() });
}

module.exports = withAdminAuth(async function handler(req, res) {
  try {
    const { db } = await connectToDatabase();
    // IMPORTANT: these must be `await`ed, not just `return`ed. `return
    // handlePost(...)` returns the still-pending promise without waiting on
    // it, so this try/catch has already exited by the time a later rejection
    // (e.g. a formidable parse error, or the R2 upload failing) happens — the
    // rejection then propagates unhandled, and Next.js renders its default
    // HTML error page instead of a JSON body. That's the exact cause of the
    // "Unexpected token '<' " error the client saw parsing the response as
    // JSON: it was actually being handed an HTML 500 page.
    if (req.method === "GET") return await handleGet(req, res, db);
    if (req.method === "POST") return await handlePost(req, res, db);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/pdfs/index.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

module.exports.default = module.exports;
module.exports.config = { api: { bodyParser: false } };
