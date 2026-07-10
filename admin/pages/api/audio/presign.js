/**
 * POST /api/audio/presign
 *   { title, artist, category, filename, contentType, thumbFilename?, thumbContentType? }
 *
 * Bug 2 / H9 fix — audio side (mirrors pages/api/pdfs/presign.js exactly;
 * see that file's header for the full rationale). Creates the draft `files`
 * doc with `pending_key` (+ `pending_thumb_key` if a thumbnail was
 * requested) and returns presigned R2 PUT URLs; the browser uploads bytes
 * directly to R2, then PATCH /api/audio/:id { field: "_upload_complete" }
 * resolves the pending keys into real r2_url/thumb_url.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { getPresignedUploadUrl } = require("../../../lib/r2");
const { isValidCategorySlug } = require("../../../lib/categoryHelpers");

module.exports = withAdminAuth(async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const { db } = await connectToDatabase();
    const { title, artist, category, filename, contentType, thumbFilename, thumbContentType } = req.body || {};

    if (!title || !String(title).trim()) {
      return res.status(400).json({ ok: false, error: "Title is required." });
    }
    if (!filename) {
      return res.status(400).json({ ok: false, error: "An audio file is required." });
    }

    const genres = category ? String(category).split(",").map((c) => c.trim()).filter(Boolean) : [];
    for (const g of genres) {
      if (!(await isValidCategorySlug(db, g))) {
        return res.status(400).json({ ok: false, error: `Unknown category "${g}". Create it first on the Categories page.` });
      }
    }

    const now = new Date();
    const insertResult = await db.collection("files").insertOne({
      display_name: String(title).trim(),
      artist: artist ? String(artist).trim() : null,
      genre: genres,
      file_id: null,
      hidden: false,
      hidden_bot: false,
      hidden_app: false,
      status: "draft",
      play_count: 0,
      created_at: now,
    });
    const docId = insertResult.insertedId;

    const audioExt = (filename.split(".").pop() || "mp3").toLowerCase();
    const audioKey = `audio/${docId}.${audioExt}`;
    const pendingUpdate = { pending_key: audioKey };

    const response = {
      ok: true,
      id: docId.toString(),
      uploadUrl: await getPresignedUploadUrl("audio", audioKey, contentType || "audio/mpeg"),
    };

    if (thumbFilename) {
      const thumbExt = (thumbFilename.split(".").pop() || "jpg").toLowerCase();
      const thumbKey = `audio/thumbs/${docId}.${thumbExt}`;
      pendingUpdate.pending_thumb_key = thumbKey;
      response.thumbUploadUrl = await getPresignedUploadUrl("audio", thumbKey, thumbContentType || "image/jpeg");
    }

    await db.collection("files").updateOne({ _id: docId }, { $set: pendingUpdate });

    return res.status(200).json(response);
  } catch (err) {
    console.error("api/audio/presign.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

module.exports.default = module.exports;
