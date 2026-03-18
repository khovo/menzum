/**
 * api/webapp/thumb.js
 * -------------------
 * GET /api/webapp/thumb?id=<mongo_doc_id>
 *
 * IMAGE PROXY — issues a 302 redirect to the Telegram CDN URL for a track thumbnail.
 *
 * WHY NO AUTH:
 *   This endpoint serves image files only — not audio, not user data.
 *   Telegram audio thumbnails are already publicly visible to anyone who
 *   received the audio message in their chat.  Protecting them with initData
 *   would require either passing initData as a query param (leaks to server logs)
 *   or fetching the image via JS + blob URL (breaks <img> caching).
 *   The tradeoff is correct: open thumbnail endpoint vs. broken UX.
 *
 * WHY 302 (REDIRECT) NOT 200 (PROXY):
 *   Proxying the image through Vercel would consume egress bandwidth on every
 *   request.  A 302 redirect is ~200 bytes; the browser fetches the image
 *   directly from Telegram's CDN.  Zero Vercel bandwidth cost.
 *
 * CACHING:
 *   Telegram file URLs expire after ~1 hour.  We set Cache-Control to 50 minutes
 *   so browsers and CDN edges reuse the redirect before it expires.
 *   The 10-minute safety margin prevents serving stale redirects to expired URLs.
 *
 * FLOW:
 *   1. Validate `id` is a 24-char hex ObjectId string
 *   2. Fetch the `files` doc — check thumb_file_id exists
 *   3. Call Telegram getFile API to resolve the CDN path
 *   4. Redirect → Telegram CDN URL
 *   5. On any failure: return 404 (browser shows broken img → falls back to gradient)
 */

const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const BOT_TOKEN = process.env.BOT_TOKEN;

// Only allow valid 24-char hex ObjectId strings — rejects all other input
const OBJECT_ID_RE = /^[a-f\d]{24}$/i;

module.exports = async function handler(req, res) {
  // CORS — image can be loaded from the webapp origin
  res.setHeader("Access-Control-Allow-Origin",  "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "GET")    return res.status(405).end();

  const id = (req.query.id || "").trim();

  // ── 1. Validate id ─────────────────────────────────────────────────────────
  if (!OBJECT_ID_RE.test(id)) {
    return res.status(400).end(); // bad request — browser shows broken img → gradient
  }

  // ── 2. No BOT_TOKEN → can't call Telegram API ─────────────────────────────
  if (!BOT_TOKEN) {
    return res.status(503).end();
  }

  try {
    const { db } = await connectToDatabase();

    // Fetch only thumb_file_id — never expose file_id or display_name
    const doc = await db.collection("files").findOne(
      { _id: new ObjectId(id) },
      { projection: { thumb_file_id: 1 } }
    );

    // ── 3. No doc or no thumbnail → 404 (frontend falls back to gradient) ────
    if (!doc?.thumb_file_id) {
      return res.status(404).end();
    }

    // ── 4. Resolve the Telegram CDN path via getFile ───────────────────────
    const getFileRes = await fetch(
      `https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${doc.thumb_file_id}`
    );
    const getFileData = await getFileRes.json();

    if (!getFileData.ok || !getFileData.result?.file_path) {
      // Telegram returned an error (file expired, invalid ID, etc.)
      return res.status(404).end();
    }

    const cdnUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${getFileData.result.file_path}`;

    // ── 5. Redirect to Telegram CDN ────────────────────────────────────────
    // Cache for 50 minutes (Telegram URLs valid ~1hr; 10-min safety margin)
    res.setHeader("Cache-Control", "public, max-age=3000, s-maxage=3000");
    res.setHeader("X-Robots-Tag",  "noindex");  // don't let bots index audio artwork

    return res.redirect(302, cdnUrl);

  } catch (err) {
    console.error("thumb.js error:", err.message);
    // Any error → 404 so the browser triggers <img> onError → gradient fallback
    return res.status(404).end();
  }
};
