const { withAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");
const { Readable }          = require("stream");

const BOT_TOKEN    = process.env.BOT_TOKEN;
const OID_RE       = /^[a-f\d]{24}$/i;

module.exports = withAuth(async function handler(req, res) {
  // 1. Handle CORS Preflight for PDF.js chunk requests
  if (req.method === "OPTIONS") {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Range, Authorization, Content-Type");
    res.setHeader("Access-Control-Max-Age", "86400");
    return res.status(200).end();
  }

  if (req.method !== "GET" && req.method !== "HEAD") return res.status(405).end();

  const id = (req.query.id || "").trim();
  const action = (req.query.action || "").trim();

  if (!OID_RE.test(id)) return res.status(400).json({ ok: false, error: "Invalid id." });
  if (!BOT_TOKEN)        return res.status(503).json({ ok: false, error: "BOT_TOKEN missing." });

  try {
    const { db } = await connectToDatabase();

    const doc = await db.collection("pdfs").findOne(
      { _id: new ObjectId(id) },
      { projection: { file_id: 1 } }
    );
    if (!doc?.file_id) return res.status(404).json({ ok: false, error: "PDF not found." });

    const gfRes  = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${doc.file_id}`);
    const gfData = await gfRes.json();

    if (!gfData.ok || !gfData.result?.file_path) {
      return res.status(404).json({ ok: false, error: "Could not resolve file URL." });
    }

    const tgUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${gfData.result.file_path}`;

    // Mode A: return our OWN proxied stream URL — never the raw Telegram URL,
    // which embeds the bot token (`/file/bot<TOKEN>/...`). Clients fetch this
    // URL with their auth header (Bearer JWT or tma initData).
    if (action !== "stream") {
      const base = `https://${req.headers.host || "menzum.vercel.app"}`;
      return res.status(200).json({ ok: true, url: `${base}/api/webapp/pdf-view?id=${id}&action=stream` });
    }

    // Mode B: Stream the PDF binary directly with Proper CORS & Range Headers for progressive loading
    const fetchOptions = {
      method: req.method,
      headers: {}
    };

    // Forward the Range header requested by PDF.js to Telegram's servers
    if (req.headers.range) {
      fetchOptions.headers['Range'] = req.headers.range;
    }

    const tgFileRes = await fetch(tgUrl, fetchOptions);

    // Required CORS and progressive loading headers
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
    res.setHeader("Access-Control-Expose-Headers", "Accept-Ranges, Content-Range, Content-Length, Content-Type");
    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Accept-Ranges", "bytes");

    if (tgFileRes.headers.has("content-length")) res.setHeader("Content-Length", tgFileRes.headers.get("content-length"));
    if (tgFileRes.headers.has("content-range")) res.setHeader("Content-Range", tgFileRes.headers.get("content-range"));

    // Return the correct status code (200 OK or 206 Partial Content)
    res.status(tgFileRes.status);

    if (req.method === "HEAD") return res.end();

    // Safely pipe the binary stream from Telegram to the client
    if (tgFileRes.body) {
      if (typeof tgFileRes.body.pipe === 'function') {
        // Node-fetch fallback
        tgFileRes.body.pipe(res);
      } else {
        // Native Next.js 18+ Web Streams implementation
        Readable.fromWeb(tgFileRes.body).pipe(res);
      }
    } else {
      const buffer = await tgFileRes.arrayBuffer();
      res.send(Buffer.from(buffer));
    }

  } catch (err) {
    console.error("pdf-view.js error:", err.message);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
});

