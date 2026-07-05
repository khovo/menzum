/**
 * GET  /api/pdfs?page=1&search=       — paginated list (20/page)
 * POST /api/pdfs  (multipart: title, description, pdf)  — no size limit
 *
 * Same visibility caveat as api/audio/index.js: this creates R2-native docs
 * with no Telegram file_id, so they won't appear in the bot/Mini App's
 * existing PDF list until those read paths accept r2_url-only docs.
 */
const fs = require("fs");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { uploadToR2 } = require("../../../lib/r2");
const { parseForm, flat, flatFile } = require("../../../lib/parseForm");

const PAGE_SIZE = 20;

async function handleGet(req, res, db) {
  const page = Math.max(1, parseInt(req.query.page, 10) || 1);
  const search = (req.query.search || "").trim();

  const filter = {};
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
      download_count: d.download_count || 0,
      hidden: !!d.hidden,
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
  const pdfFile = flatFile(files, "pdf");

  if (!title || !title.trim()) {
    return res.status(400).json({ ok: false, error: "Title is required." });
  }
  if (!pdfFile) {
    return res.status(400).json({ ok: false, error: "A PDF file is required." });
  }

  const now = new Date();
  const insertResult = await db.collection("pdfs").insertOne({
    title: title.trim(),
    description: description ? description.trim() : null,
    file_id: null, // R2-native upload — see module note above
    hidden: false,
    download_count: 0,
    created_at: now,
  });
  const docId = insertResult.insertedId;

  const buf = fs.readFileSync(pdfFile.filepath);
  const r2Url = await uploadToR2("pdf", `pdfs/${docId}.pdf`, buf, "application/pdf");

  await db.collection("pdfs").updateOne(
    { _id: docId },
    { $set: { r2_url: r2Url, size_bytes: pdfFile.size || buf.length } }
  );

  return res.status(201).json({ ok: true, id: docId.toString() });
}

module.exports = withAdminAuth(async function handler(req, res) {
  try {
    const { db } = await connectToDatabase();
    if (req.method === "GET") return handleGet(req, res, db);
    if (req.method === "POST") return handlePost(req, res, db);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/pdfs/index.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

module.exports.default = module.exports;
module.exports.config = { api: { bodyParser: false } };
