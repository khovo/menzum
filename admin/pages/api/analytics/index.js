/**
 * GET /api/analytics
 * Data for the /analytics page: 30-day user growth, plays per category,
 * and the top 10 most-downloaded PDFs.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { CATEGORY_SLUGS } = require("../../../lib/categories");

module.exports = withAdminAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const { db } = await connectToDatabase();
    const now = new Date();
    const since30d = new Date(now - 30 * 86_400_000);

    const [growthRaw, playsByGenreRaw, topPdfs] = await Promise.all([
      db.collection("users").aggregate([
        { $match: { joined_at: { $gte: since30d } } },
        {
          $group: {
            _id: { $dateToString: { format: "%Y-%m-%d", date: "$joined_at" } },
            count: { $sum: 1 },
          },
        },
      ]).toArray(),

      db.collection("files").aggregate([
        { $match: { genre: { $in: CATEGORY_SLUGS } } },
        { $group: { _id: "$genre", plays: { $sum: { $ifNull: ["$play_count", 0] } } } },
      ]).toArray(),

      db.collection("pdfs")
        .find({}, { projection: { title: 1, download_count: 1 } })
        .sort({ download_count: -1 })
        .limit(10)
        .toArray(),
    ]);

    const growthMap = {};
    for (const row of growthRaw) growthMap[row._id] = row.count;
    const userGrowth = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(now - i * 86_400_000);
      const key = d.toISOString().slice(0, 10);
      userGrowth.push({ date: key.slice(5), users: growthMap[key] ?? 0 });
    }

    const playsMap = {};
    for (const row of playsByGenreRaw) playsMap[row._id] = row.plays;
    const playsByCategory = CATEGORY_SLUGS.map((slug) => ({ category: slug, plays: playsMap[slug] ?? 0 }));

    return res.status(200).json({
      ok: true,
      userGrowth,
      playsByCategory,
      topPdfs: topPdfs.map((p) => ({
        id: p._id.toString(),
        title: p.title || "Untitled",
        downloads: p.download_count || 0,
      })),
    });
  } catch (err) {
    console.error("api/analytics/index.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
