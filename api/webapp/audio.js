/**
 * api/webapp/audio.js
 * -------------------
 * GET /api/webapp/audio?id=<track_id>&action=stream
 * Auth: Bearer <jwt> OR tma <initData>
 *
 * Streams the actual audio bytes for a track so the mobile app (or any player)
 * can play and seek it. Modeled on pdf-view.js streaming:
 *   1. Resolve the track's Telegram file_id from MongoDB (never exposed).
 *   2. getFile → temporary CDN path.
 *   3. Pipe the bytes back with Content-Type + Range support (200 / 206).
 *
 * The bot token never reaches the client — we proxy the bytes, we don't redirect
 * to the raw Telegram file URL. Supports GET and HEAD; forwards the Range header.
 *
 * `track_id` is accepted as an alias for `id`.
 */
const { withAuth } = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId } = require("mongodb");
const { Readable } = require("stream");

const BOT_TOKEN = process.env.BOT_TOKEN;
const OID_RE = /^[a-f\d]{24}$/i;

function contentTypeFor(path) {
  const p = path.toLowerCase();
  if (p.endsWith(".oga") || p.endsWith(".ogg")) return "audio/ogg";
  if (p.endsWith(".m4a") || p.endsWith(".mp4") || p.endsWith(".aac")) return "audio/mp4";
  if (p.endsWith(".wav")) return "audio/wav";
  if (p.endsWith(".opus")) return "audio/opus";
  return "audio/mpeg"; // .mp3 and default
}

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const id = (req.query.id || req.query.track_id || "").trim();
  if (!OID_RE.test(id)) return res.status(400).json({ ok: false, error: "Invalid id." });
  if (!BOT_TOKEN) return res.status(503).json({ ok: false, error: "BOT_TOKEN missing." });

  try {
    const { db } = await connectToDatabase();

    const doc = await db.collection("files").findOne(
      { _id: new ObjectId(id) },
      { projection: { file_id: 1 } }
    );
    if (!doc?.file_id) return res.status(404).json({ ok: false, error: "Track not found." });

    const gfRes = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${doc.file_id}`);
    const gfData = await gfRes.json();
    if (!gfData.ok || !gfData.result?.file_path) {
      return res.status(404).json({ ok: false, error: "Could not resolve audio file." });
    }

    const filePath = gfData.result.file_path;
    const tgUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${filePath}`;

    const fetchOptions = { method: req.method, headers: {} };
    if (req.headers.range) fetchOptions.headers["Range"] = req.headers.range;

    const tgFileRes = await fetch(tgUrl, fetchOptions);

    res.setHeader("Content-Type", contentTypeFor(filePath));
    res.setHeader("Accept-Ranges", "bytes");
    res.setHeader("Cache-Control", "private, max-age=3000");
    if (tgFileRes.headers.has("content-length")) res.setHeader("Content-Length", tgFileRes.headers.get("content-length"));
    if (tgFileRes.headers.has("content-range")) res.setHeader("Content-Range", tgFileRes.headers.get("content-range"));

    res.status(tgFileRes.status); // 200 or 206 (Partial Content)

    if (req.method === "HEAD") return res.end();

    if (tgFileRes.body) {
      if (typeof tgFileRes.body.pipe === "function") {
        tgFileRes.body.pipe(res);
      } else {
        Readable.fromWeb(tgFileRes.body).pipe(res);
      }
    } else {
      const buffer = await tgFileRes.arrayBuffer();
      res.send(Buffer.from(buffer));
    }
  } catch (err) {
    console.error("audio.js error:", err.message);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
});
