const { withAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const BOT_TOKEN = process.env.BOT_TOKEN;
const PAGE_SIZE = 20;

async function telegramCall(method, payload) {
  const res = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  return res.json();
}

module.exports = withAuth(async function handler(req, res) {
  const { db }    = await connectToDatabase();
  const userId    = parseInt(req.telegramUser.id, 10);

  // ── GET /api/webapp/pdfs?cursor= ─────────────────────────────────────────
  if (req.method === "GET") {
    const cursorParam = (req.query.cursor || "").trim();
    const limit       = Math.min(parseInt(req.query.limit || PAGE_SIZE, 10), 50);

    const filter = {};
    if (cursorParam && cursorParam.length === 24) {
      try { filter._id = { $lt: new ObjectId(cursorParam) }; } catch {}
    }

    const [pdfs, dbUser] = await Promise.all([
      db.collection("pdfs")
        .find(filter, { projection: { file_id: 0 } })
        .sort({ _id: -1 })
        .limit(limit + 1)
        .toArray(),
      db.collection("users").findOne({ _id: userId }, { projection: { pdf_favorites: 1 } }),
    ]);

    const hasMore   = pdfs.length > limit;
    const page      = hasMore ? pdfs.slice(0, limit) : pdfs;
    const favSet    = new Set((dbUser?.pdf_favorites ?? []).map(String));

    const response = page.map((p) => ({
      id:          p._id.toString(),
      title:       p.title || "Untitled",
      file_name:   p.file_name || "",
      is_favorite: favSet.has(p._id.toString()),
    }));

    return res.status(200).json({
      ok:          true,
      pdfs:        response,
      has_more:    hasMore,
      next_cursor: hasMore ? response[response.length - 1].id : null,
    });
  }

  // ── POST /api/webapp/pdfs  { action, pdf_id } ─────────────────────────────
  if (req.method === "POST") {
    const { action, pdf_id } = req.body || {};

    if (!pdf_id || pdf_id.length !== 24) {
      return res.status(400).json({ ok: false, error: "Invalid pdf_id." });
    }

    const doc = await db.collection("pdfs").findOne(
      { _id: new ObjectId(pdf_id) },
      { projection: { file_id: 1, title: 1 } }
    );
    if (!doc) return res.status(404).json({ ok: false, error: "PDF not found." });

    // ── action: favorite ────────────────────────────────────────────────────
    if (action === "favorite") {
      const dbUser  = await db.collection("users").findOne({ _id: userId }, { projection: { pdf_favorites: 1 } });
      const favs    = (dbUser?.pdf_favorites ?? []).map(String);
      const already = favs.includes(pdf_id);

      if (already) {
        await db.collection("users").updateOne({ _id: userId }, { $pull: { pdf_favorites: pdf_id } });
      } else {
        await db.collection("users").updateOne(
          { _id: userId },
          { $addToSet: { pdf_favorites: pdf_id } },
          { upsert: true }
        );
      }
      return res.status(200).json({ ok: true, action: "favorite", is_favorite: !already });
    }

    // ── action: deliver ─────────────────────────────────────────────────────
    if (action === "deliver") {
      if (!BOT_TOKEN) return res.status(500).json({ ok: false, error: "BOT_TOKEN missing." });

      const tgRes = await telegramCall("sendDocument", {
        chat_id:    userId,
        document:   doc.file_id,
        caption:    doc.title ? `📄 ${doc.title}` : "📄 Al-Madih PDF Library",
        parse_mode: "Markdown",
      });

      if (!tgRes.ok) {
        const err = tgRes.description || "Telegram error";
        return res.status(502).json({
          ok:    false,
          error: err.includes("chat not found") ? "Please send /start to @Almadihbot first." : err,
        });
      }

      await db.collection("pdfs").updateOne({ _id: doc._id }, { $inc: { download_count: 1 } });
      return res.status(200).json({ ok: true, action: "deliver", title: doc.title });
    }

    return res.status(400).json({ ok: false, error: "Invalid action." });
  }

  return res.status(405).json({ ok: false, error: "Method not allowed." });
});
