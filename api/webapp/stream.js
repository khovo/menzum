/**
 * api/webapp/stream.js
 * --------------------
 * GET /api/webapp/stream?track_id=<24-char-mongo-id>
 *
 * AUDIO PROXY — issues a 302 redirect to the Telegram CDN URL for a track's
 * audio file, so the Mini App's HTML5 <audio> element can play it directly.
 *
 * WHY NO AUTH (same reasoning as thumb.js):
 *   HTML5 <audio> elements cannot send Authorization headers. Requiring auth
 *   would mean fetching via JS → blob URL, which risks Vercel's 10s function
 *   timeout for large audio files on the free tier. The 302 redirect approach
 *   keeps the architecture simple and proven. The file_id is still NEVER sent
 *   to the browser — only the temporary Telegram CDN URL (via redirect), which
 *   expires within ~1 hour and cannot be linked to any user account.
 *
 * WHY NO crossorigin ATTRIBUTE ON <audio>:
 *   Without the crossorigin attribute, the browser fetches audio as a "no-cors"
 *   opaque request. CORS headers are not checked. The audio plays fine. We only
 *   need timeupdate events from the element — no Web Audio API access required.
 *
 * WHY 302 (REDIRECT) NOT 200 (PROXY):
 *   Proxying large audio files through a serverless function risks the Vercel
 *   Hobby tier's 10-second function timeout. A 302 redirect costs ~200 bytes
 *   from our function; the browser streams audio directly from Telegram's CDN.
 *
 * FLOW:
 *   1. Validate track_id is a 24-char hex ObjectId
 *   2. Fetch files doc → get file_id (server-side only, never returned to client)
 *   3. Call Telegram getFile API → get CDN path
 *   4. 302 redirect → Telegram CDN audio URL
 *   5. On any failure: 404 (audio element triggers onerror)
 */

const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const BOT_TOKEN = process.env.BOT_TOKEN;

const OBJECT_ID_RE = /^[a-f\d]{24}$/i;

module.exports = async function handler(req, res) {
  // CORS — audio can be loaded from the webapp origin
  res.setHeader("Access-Control-Allow-Origin",  "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "GET")    return res.status(405).end();

  const id = (req.query.track_id || "").trim();

  // ── 1. Validate track_id ───────────────────────────────────────────────────
  if (!OBJECT_ID_RE.test(id)) {
    return res.status(400).end();
  }

  if (!BOT_TOKEN) {
    return res.status(503).end();
  }

  try {
    const { db } = await connectToDatabase();

    // ── 2. Look up file_id server-side — never sent to the browser ────────
    const doc = await db.collection("files").findOne(
      { _id: new ObjectId(id) },
      { projection: { file_id: 1 } }
    );

    if (!doc?.file_id) {
      return res.status(404).end();
    }

    // ── 3. Resolve the Telegram CDN path via getFile ──────────────────────
    const getFileRes  = await fetch(
      `https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${doc.file_id}`
    );
    const getFileData = await getFileRes.json();

    if (!getFileData.ok || !getFileData.result?.file_path) {
      return res.status(404).end();
    }

    const cdnUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${getFileData.result.file_path}`;

    // ── 4. Redirect to Telegram CDN ───────────────────────────────────────
    // Cache 30 min — audio URLs are valid ~1hr; 30-min margin prevents
    // the browser serving a stale redirect to an expired URL mid-session.
    res.setHeader("Cache-Control", "public, max-age=1800, s-maxage=1800");
    res.setHeader("X-Robots-Tag",  "noindex");

    return res.redirect(302, cdnUrl);

  } catch (err) {
    console.error("stream.js error:", err.message);
    return res.status(404).end();
  }
};
