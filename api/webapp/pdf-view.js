const { withAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const BOT_TOKEN    = process.env.BOT_TOKEN;
const OID_RE       = /^[a-f\d]{24}$/i;

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).end();

  const id = (req.query.id || "").trim();
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

    const url = `https://api.telegram.org/file/bot${BOT_TOKEN}/${gfData.result.file_path}`;

    // Return JSON — frontend constructs the Google Docs viewer iframe src
    return res.status(200).json({ ok: true, url });

  } catch (err) {
    console.error("pdf-view.js error:", err.message);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
});
