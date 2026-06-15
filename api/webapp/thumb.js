/**
 * api/webapp/thumb.js
 * -------------------
 * GET /api/webapp/thumb?id=<track_id>   (public — images only)
 *
 * Returns a track's cover image. PROXIES THE BYTES through the backend rather
 * than 302-redirecting to the raw Telegram file URL, because that URL contains
 * the bot token (`/file/bot<TOKEN>/...`) and would leak it to the client.
 *
 * FLOW:
 *   1. Validate `id` is a 24-char hex ObjectId.
 *   2. Look up the track's thumb_file_id (never exposed).
 *   3. getFile → CDN path → fetch the image bytes server-side.
 *   4. Stream the bytes back with the original Content-Type. 404 on any failure
 *      so the UI falls back to a generated gradient/placeholder.
 *
 * Still public (no auth) — it only serves cover art. Cached ~50 minutes.
 */
const { connectToDatabase } = require("./_db");
const { ObjectId } = require("mongodb");
const { Readable } = require("stream");

const BOT_TOKEN = process.env.BOT_TOKEN;
const OBJECT_ID_RE = /^[a-f\d]{24}$/i;

module.exports = async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "GET") return res.status(405).end();

  const id = (req.query.id || "").trim();
  if (!OBJECT_ID_RE.test(id)) return res.status(400).end();
  if (!BOT_TOKEN) return res.status(503).end();

  try {
    const { db } = await connectToDatabase();

    const doc = await db.collection("files").findOne(
      { _id: new ObjectId(id) },
      { projection: { thumb_file_id: 1 } }
    );
    if (!doc?.thumb_file_id) return res.status(404).end();

    const getFileRes = await fetch(
      `https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${doc.thumb_file_id}`
    );
    const getFileData = await getFileRes.json();
    if (!getFileData.ok || !getFileData.result?.file_path) {
      return res.status(404).end();
    }

    const cdnUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${getFileData.result.file_path}`;
    const imgRes = await fetch(cdnUrl);
    if (!imgRes.ok) return res.status(404).end();

    res.setHeader("Content-Type", imgRes.headers.get("content-type") || "image/jpeg");
    res.setHeader("Cache-Control", "public, max-age=3000, s-maxage=3000");
    res.setHeader("X-Robots-Tag", "noindex");

    if (imgRes.body && typeof imgRes.body.pipe === "function") {
      imgRes.body.pipe(res);
    } else if (imgRes.body) {
      Readable.fromWeb(imgRes.body).pipe(res);
    } else {
      const buf = await imgRes.arrayBuffer();
      res.status(200).send(Buffer.from(buf));
    }
  } catch (err) {
    console.error("thumb.js error:", err.message);
    return res.status(404).end();
  }
};
