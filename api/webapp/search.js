/**
 * api/webapp/search.js  (V4 — unified audio + PDF search)
 * GET /api/webapp/search?q=<query>&cursor=<last_id>&type=all|audio|pdf
 */
const { withAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const PAGE_SIZE = 20;

function buildAudioQuery(q) {
  if (!q) return { file_id: { $exists: true } };
  const trimmed = q.trim();
  if (trimmed.length === 1)
    return { display_name: { $regex: `^${escapeRegex(trimmed)}`, $options: "i" } };
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length === 1)
    return { display_name: { $regex: escapeRegex(words[0]), $options: "i" } };
  return { $and: words.map((w) => ({ display_name: { $regex: escapeRegex(w), $options: "i" } })) };
}

function buildPdfQuery(q) {
  if (!q) return {};
  const trimmed = q.trim();
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (!words.length) return {};
  if (words.length === 1)
    return { title: { $regex: escapeRegex(words[0]), $options: "i" } };
  return { $and: words.map((w) => ({ title: { $regex: escapeRegex(w), $options: "i" } })) };
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ ok: false, error: "Method not allowed." });

  const query       = (req.query.q      || "").trim();
  const cursorParam = (req.query.cursor  || "").trim();
  const typeFilter  = req.query.type || "all";   // "all" | "audio" | "pdf"
  const limit       = Math.min(parseInt(req.query.limit || PAGE_SIZE, 10), 50);
  const userId      = parseInt(req.telegramUser.id, 10);

  try {
    const { db } = await connectToDatabase();

    const audioFilter = buildAudioQuery(query);
    const pdfFilter   = buildPdfQuery(query);

    // Apply cursor to audio filter
    if (cursorParam && cursorParam.length === 24) {
      try { audioFilter._id = { $lt: new ObjectId(cursorParam) }; } catch {}
    }

    const [audioRes, pdfRes, dbUser] = await Promise.all([
      typeFilter !== "pdf"
        ? db.collection("files")
            .find(audioFilter, { projection: { display_name: 1, file_id: 1, thumb_file_id: 1 } })
            .sort({ _id: -1 })
            .limit(limit + 1)
            .toArray()
        : Promise.resolve([]),

      typeFilter !== "audio"
        ? db.collection("pdfs")
            .find(pdfFilter, { projection: { title: 1, file_name: 1 } })
            .sort({ _id: -1 })
            .limit(typeFilter === "pdf" ? limit + 1 : 5) // cap PDFs at 5 in mixed results
            .toArray()
        : Promise.resolve([]),

      db.collection("users").findOne({ _id: userId }, { projection: { favorites: 1, pdf_favorites: 1 } }),
    ]);

    const audioHasMore = typeFilter !== "pdf" && audioRes.length > limit;
    const audioPage    = audioHasMore ? audioRes.slice(0, limit) : audioRes;
    const favSet       = new Set(dbUser?.favorites ?? []);
    const pdfFavSet    = new Set((dbUser?.pdf_favorites ?? []).map(String));

    const audioResults = audioPage.map((t) => ({
      id:          t._id.toString(),
      name:        t.display_name || "Unknown",
      is_favorite: favSet.has(t.file_id ?? ""),
      has_thumb:   !!t.thumb_file_id,
      type:        "audio",
    }));

    const pdfHasMore  = typeFilter === "pdf" && pdfRes.length > limit;
    const pdfPage     = pdfHasMore ? pdfRes.slice(0, limit) : pdfRes;
    const pdfResults  = pdfPage.map((p) => ({
      id:          p._id.toString(),
      name:        p.title || p.file_name || "Untitled",
      is_favorite: pdfFavSet.has(p._id.toString()),
      type:        "pdf",
    }));

    // Mixed: audio first, PDFs appended
    const combined = [...audioResults, ...pdfResults];
    const hasMore  = audioHasMore || pdfHasMore;

    return res.status(200).json({
      ok:          true,
      query,
      tracks:      combined,   // kept as "tracks" for frontend compat
      has_more:    hasMore,
      next_cursor: audioHasMore ? audioResults[audioResults.length - 1]?.id : null,
    });

  } catch (err) {
    console.error("search.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});
