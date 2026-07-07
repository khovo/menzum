/**
 * GET  /api/audio?page=1&search=&category=          — paginated list (20/page)
 * POST /api/audio  (multipart: title, artist, category, audio, thumbnail)
 *
 * `category` accepts any of the 5 fixed genre slugs (lib/categories.js) OR a
 * custom category created via /api/categories — see lib/categoryHelpers.js.
 *
 * NOTE ON VISIBILITY: uploads here are R2-native and have no Telegram
 * `file_id`. The bot's own catalog/search and the existing Mini App API
 * (api/webapp/featured.js, search.js, handlers/*.py) all filter on
 * `file_id` existing, so a track created here will NOT show up there until
 * those read paths are updated to also accept r2_url-only docs. This panel
 * itself manages such docs fully (list/edit/hide) regardless.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { uploadToR2 } = require("../../../lib/r2");
const { parseForm, flat, flatFile } = require("../../../lib/parseForm");
const { isValidCategorySlug } = require("../../../lib/categoryHelpers");
const fs = require("fs");

const PAGE_SIZE = 20;

async function handleGet(req, res, db) {
  const page = Math.max(1, parseInt(req.query.page, 10) || 1);
  const search = (req.query.search || "").trim();
  const category = (req.query.category || "").trim();

  const filter = { hidden: { $ne: true } };
  if (search) {
    filter.display_name = { $regex: search.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), $options: "i" };
  }
  if (category) {
    filter.genre = category;
  }

  const [items, total] = await Promise.all([
    db.collection("files")
      .find(filter)
      .sort({ _id: -1 })
      .skip((page - 1) * PAGE_SIZE)
      .limit(PAGE_SIZE)
      .toArray(),
    db.collection("files").countDocuments(filter),
  ]);

  return res.status(200).json({
    ok: true,
    items: items.map((d) => ({
      id: d._id.toString(),
      display_name: d.display_name || "Unknown",
      artist: d.artist || null,
      genre: d.genre || null,
      play_count: d.play_count || 0,
      hidden: !!d.hidden,
      hidden_bot: !!d.hidden_bot,
      hidden_app: !!d.hidden_app,
      has_r2: !!d.r2_url,
      has_telegram: !!d.file_id,
      r2_url: d.r2_url || null,
      thumb_url: d.thumb_url || null,
    })),
    page,
    pageSize: PAGE_SIZE,
    total,
    totalPages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
  });
}

async function handlePost(req, res, db) {
  const { fields, files } = await parseForm(req);
  const { title, artist, category } = flat(fields);
  const audioFile = flatFile(files, "audio");
  const thumbFile = flatFile(files, "thumbnail");

  if (!title || !title.trim()) {
    return res.status(400).json({ ok: false, error: "Title is required." });
  }
  if (!audioFile) {
    return res.status(400).json({ ok: false, error: "An audio file is required." });
  }
  if (category && !(await isValidCategorySlug(db, category))) {
    return res.status(400).json({ ok: false, error: `Unknown category "${category}". Create it first on the Categories page.` });
  }

  const now = new Date();
  const insertResult = await db.collection("files").insertOne({
    display_name: title.trim(),
    artist: artist ? artist.trim() : null,
    genre: category || null,
    file_id: null, // R2-native upload — see module note above
    hidden: false,
    hidden_bot: false,
    hidden_app: false,
    play_count: 0,
    created_at: now,
  });
  const docId = insertResult.insertedId;

  const audioBuf = fs.readFileSync(audioFile.filepath);
  const audioExt = (audioFile.originalFilename || "").split(".").pop() || "mp3";
  const audioUrl = await uploadToR2("audio", `audio/${docId}.${audioExt}`, audioBuf, audioFile.mimetype);

  const update = { r2_url: audioUrl, size_bytes: audioFile.size || audioBuf.length };

  if (thumbFile) {
    const thumbBuf = fs.readFileSync(thumbFile.filepath);
    const thumbExt = (thumbFile.originalFilename || "").split(".").pop() || "jpg";
    update.thumb_url = await uploadToR2("audio", `audio/thumbs/${docId}.${thumbExt}`, thumbBuf, thumbFile.mimetype);
  }

  await db.collection("files").updateOne({ _id: docId }, { $set: update });

  return res.status(201).json({ ok: true, id: docId.toString() });
}

module.exports = withAdminAuth(async function handler(req, res) {
  try {
    const { db } = await connectToDatabase();
    // These awaits matter — see pages/api/pdfs/index.js for the write-up of
    // why a bare `return handleX(...)` lets a later rejection escape this
    // try/catch and surface as an HTML 500 instead of a JSON error body.
    if (req.method === "GET") return await handleGet(req, res, db);
    if (req.method === "POST") return await handlePost(req, res, db);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/audio/index.js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

// Next.js's production API route runtime requires `.default` specifically —
// a bare CommonJS `module.exports = fn` alone isn't picked up at request time
// (only at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
module.exports.config = { api: { bodyParser: false } };
