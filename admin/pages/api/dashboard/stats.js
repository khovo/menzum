/**
 * GET /api/dashboard/stats
 * Aggregate numbers for the dashboard: stat cards, daily-plays line chart,
 * top-10 bar chart, recent uploads, and best-effort R2 storage usage.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");

module.exports = withAdminAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const { db } = await connectToDatabase();
    const now = new Date();
    const since30d = new Date(now - 30 * 86_400_000);

    const [
      totalUsers,
      totalAudio,
      totalPdfs,
      totalPlaysAgg,
      dailyPlaysRaw,
      topTracks,
      recentAudio,
      recentPdfs,
      storageAgg,
    ] = await Promise.all([
      db.collection("users").countDocuments({}),
      db.collection("files").countDocuments({}),
      db.collection("pdfs").countDocuments({}),

      db.collection("users").aggregate([
        { $group: { _id: null, total: { $sum: { $ifNull: ["$total_plays", 0] } } } },
      ]).toArray(),

      // Plays per day over the last 30 days, sourced from users.listen_history
      // (the only per-play timestamped record kept anywhere in this system).
      db.collection("users").aggregate([
        { $match: { listen_history: { $exists: true, $ne: [] } } },
        { $unwind: "$listen_history" },
        { $match: { "listen_history.played_at": { $gte: since30d } } },
        {
          $group: {
            _id: { $dateToString: { format: "%Y-%m-%d", date: "$listen_history.played_at" } },
            count: { $sum: 1 },
          },
        },
      ]).toArray(),

      db.collection("files")
        .find({}, { projection: { display_name: 1, play_count: 1 } })
        .sort({ play_count: -1 })
        .limit(10)
        .toArray(),

      db.collection("files")
        .find({}, { projection: { display_name: 1, artist: 1, hidden: 1, r2_url: 1 } })
        .sort({ _id: -1 })
        .limit(5)
        .toArray(),

      db.collection("pdfs")
        .find({}, { projection: { title: 1, hidden: 1, r2_url: 1 } })
        .sort({ _id: -1 })
        .limit(5)
        .toArray(),

      // Best-effort: only sums size_bytes where we recorded it at upload time
      // (i.e. content uploaded through this panel). Legacy Telegram-migrated
      // docs don't have a known size without a live R2 HEAD request per file,
      // which is too slow to do on every dashboard load.
      Promise.all([
        db.collection("files").aggregate([
          { $group: { _id: null, bytes: { $sum: { $ifNull: ["$size_bytes", 0] } } } },
        ]).toArray(),
        db.collection("pdfs").aggregate([
          { $group: { _id: null, bytes: { $sum: { $ifNull: ["$size_bytes", 0] } } } },
        ]).toArray(),
      ]),
    ]);

    // Fill in zero-play days so the line chart has a continuous 30-day axis.
    const dayMap = {};
    for (const row of dailyPlaysRaw) dayMap[row._id] = row.count;
    const dailyPlays = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(now - i * 86_400_000);
      const key = d.toISOString().slice(0, 10);
      dailyPlays.push({ date: key.slice(5), plays: dayMap[key] ?? 0 });
    }

    const [audioBytesAgg, pdfBytesAgg] = storageAgg;
    const storageUsedBytes = (audioBytesAgg[0]?.bytes ?? 0) + (pdfBytesAgg[0]?.bytes ?? 0);

    return res.status(200).json({
      ok: true,
      stats: {
        totalUsers,
        totalAudio,
        totalPdfs,
        totalPlays: totalPlaysAgg[0]?.total ?? 0,
        storageUsedBytes,
      },
      dailyPlays,
      topTracks: topTracks.map((t) => ({
        name: t.display_name || "Unknown",
        plays: t.play_count || 0,
      })),
      recentAudio: recentAudio.map((a) => ({
        id: a._id.toString(),
        name: a.display_name || "Unknown",
        artist: a.artist || null,
        hidden: !!a.hidden,
        hasR2: !!a.r2_url,
      })),
      recentPdfs: recentPdfs.map((p) => ({
        id: p._id.toString(),
        title: p.title || "Untitled",
        hidden: !!p.hidden,
        hasR2: !!p.r2_url,
      })),
    });
  } catch (err) {
    console.error("dashboard/stats.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
