/**
 * PUT    /api/audio/:id  (multipart: title, artist, category, thumbnail?)
 *        Edits metadata; thumbnail file is optional (only re-uploaded if sent).
 * DELETE /api/audio/:id
 *        Soft-delete only — sets hidden:true. Never removes the document.
 */
const { ObjectId } = require("mongodb");
const fs = require("fs");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { uploadToR2 } = require("../../../lib/r2");
const { parseForm, flat, flatFile } = require("../../../lib/parseForm");
const { CATEGORY_SLUGS } = require("../../../lib/categories");

async function handlePut(req, res, db, id) {
  const { fields, files } = await parseForm(req);
  const { title, artist, category } = flat(fields);
  const thumbFile = flatFile(files, "thumbnail");

  if (category && !CATEGORY_SLUGS.includes(category)) {
    return res.status(400).json({ ok: false, error: `Invalid category. Must be one of: ${CATEGORY_SLUGS.join(", ")}` });
  }

  const update = {};
  if (title !== undefined && title.trim()) update.display_name = title.trim();
  if (artist !== undefined) update.artist = artist.trim() || null;
  if (category !== undefined) update.genre = category || null;

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
    if (req.method === "PUT") return handlePut(req, res, db, id);
    if (req.method === "DELETE") return handleDelete(req, res, db, id);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/audio/[id].js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

module.exports.config = { api: { bodyParser: false } };
