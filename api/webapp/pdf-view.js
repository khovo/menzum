/**
 * api/webapp/pdf-view.js
 * ----------------------
 * GET/HEAD /api/webapp/pdf-view?id=<pdf_id>[&action=stream|url]
 * Auth: Bearer <jwt> OR tma <initData>  (dual auth via withAuth)
 *
 * Returns the raw PDF bytes (Content-Type: application/pdf) with Range/seek
 * support. Streaming is now the DEFAULT — both `?action=stream` and no `action`
 * stream the file, so a client that forgets the param still gets a real PDF.
 * Only the explicit `?action=url` returns a JSON pointer instead of bytes.
 *
 * Why buffer instead of pipe: piping a web ReadableStream to the response is
 * not reliably flushed on Vercel's serverless runtime (it could return 200 with
 * an empty/garbled body). We read the bytes and res.send() them — deterministic.
 * PDFs here are books (a few MB), so buffering is fine.
 *
 * The bot token is never exposed — we proxy the bytes, never redirect to the
 * raw Telegram file URL.
 */
const { withOptionalAuth } = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId } = require("mongodb");

const BOT_TOKEN = process.env.BOT_TOKEN;
const OID_RE = /^[a-f\d]{24}$/i;

module.exports = withOptionalAuth(async function handler(req, res) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const id = (req.query.id || "").trim();
  const action = (req.query.action || "").trim();

  if (!OID_RE.test(id)) return res.status(400).json({ ok: false, error: "Invalid id." });
  if (!BOT_TOKEN) return res.status(503).json({ ok: false, error: "BOT_TOKEN missing." });

  try {
    const { db } = await connectToDatabase();

    const doc = await db.collection("pdfs").findOne(
      { _id: new ObjectId(id) },
      { projection: { file_id: 1 } }
    );
    if (!doc?.file_id) return res.status(404).json({ ok: false, error: "PDF not found." });

    const gfRes = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${doc.file_id}`);
    const gfData = await gfRes.json();
    if (!gfData.ok || !gfData.result?.file_path) {
      // Telegram couldn't hand us the file. Log the exact reason so the cause is
      // visible in prod logs, and return a specific, honest error (never bytes).
      const desc = (gfData && gfData.description) || "unknown";
      console.error(`pdf-view.js getFile failed id=${id} file_id=${String(doc.file_id).slice(0, 12)}… desc="${desc}"`);
      if (/too big/i.test(desc)) {
        // Bot API can only download files up to 20 MB — larger PDFs can't be served this way.
        return res.status(413).json({ ok: false, error: "This PDF is too large to stream (Telegram Bot API limit is 20 MB).", reason: desc });
      }
      return res.status(404).json({ ok: false, error: "This PDF is no longer available from Telegram.", reason: desc });
    }

    const tgUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${gfData.result.file_path}`;

    // Opt-in JSON pointer (only when explicitly requested). Everything else streams.
    if (action === "url") {
      const base = `https://${req.headers.host || "menzum.vercel.app"}`;
      return res.status(200).json({ ok: true, url: `${base}/api/webapp/pdf-view?id=${id}&action=stream` });
    }

    // ── Stream (buffered) ──────────────────────────────────────────────────────
    const fetchOptions = { method: "GET", headers: {} };
    if (req.headers.range) fetchOptions.headers["Range"] = req.headers.range;

    const tgFileRes = await fetch(tgUrl, fetchOptions);

    // Never forward a Telegram error body as application/pdf.
    if (!tgFileRes.ok && tgFileRes.status !== 206) {
      console.error("pdf-view.js upstream status:", tgFileRes.status, "id:", id);
      return res.status(502).json({ ok: false, error: "Upstream file fetch failed." });
    }

    const buf = Buffer.from(await tgFileRes.arrayBuffer());

    // CORS + range headers
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
    res.setHeader("Access-Control-Expose-Headers", "Accept-Ranges, Content-Range, Content-Length, Content-Type");
    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Accept-Ranges", "bytes");
    res.setHeader("Cache-Control", "private, max-age=3000");

    const contentRange = tgFileRes.headers.get("content-range");
    if (contentRange) {
      res.setHeader("Content-Range", contentRange);
      res.setHeader("Content-Length", String(buf.length));
      res.status(206);
    } else {
      res.setHeader("Content-Length", String(buf.length));
      res.status(200);
      // Diagnostic: a full response should start with the PDF magic bytes.
      if (buf.length >= 4 && buf.toString("latin1", 0, 4) !== "%PDF") {
        console.error("pdf-view.js: non-PDF bytes from upstream, id:", id, "head:", buf.toString("latin1", 0, 16));
      }
    }

    if (req.method === "HEAD") return res.end();
    return res.end(buf);
  } catch (err) {
    console.error("pdf-view.js error:", err && err.message);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
});
