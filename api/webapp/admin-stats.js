/**
 * api/webapp/admin-stats.js
 * -------------------------
 * GET /api/webapp/admin-stats
 *
 * SECURITY MODEL:
 *   Authorization: Bearer <ADMIN_TOKEN>
 *
 *   ADMIN_TOKEN is a plain process.env var — NO "NEXT_PUBLIC_" prefix.
 *   It is NEVER embedded in the browser JS bundle.
 *   The admin page collects a password, sends it here as a Bearer token.
 *   This function compares it server-side using constant-time comparison.
 *
 * DATA RETURNED:
 *   - totalUsers:    count of all users
 *   - totalFiles:    count of all audio files
 *   - totalPlays:    global sum of users.total_plays
 *   - userGrowth:    new users per day for the last 14 days (for AreaChart)
 *   - trendingTracks: top 5 most-played tracks last 7 days (for BarChart)
 *
 * All queries run in parallel via Promise.all.
 */

const { connectToDatabase } = require("./_db");
const crypto = require("crypto");

// .trim() is mandatory: Vercel (and most CI systems) silently append a trailing
// newline or carriage-return to env var values when they are set via the dashboard
// or a .env file without quotes. If the byte lengths differ, timingSafeEqual throws
// instead of returning false, the catch returns false, and you get a permanent 401
// even when the token is 100% correct.
const ADMIN_TOKEN = (process.env.ADMIN_TOKEN || "").trim();

function constantTimeEqual(a, b) {
  // Trim both sides to strip any whitespace the client or server may have added.
  const bufA = Buffer.from(a.trim());
  const bufB = Buffer.from(b.trim());

  // timingSafeEqual REQUIRES identical lengths — throws a RangeError otherwise.
  // We must length-check first, then still call timingSafeEqual (not early-return)
  // so the comparison time stays constant and doesn't leak token length via timing.
  if (bufA.length !== bufB.length) {
    // Lengths differ — run a dummy equal-length comparison so timing stays flat,
    // then return false.
    const dummy = Buffer.alloc(bufA.length);
    crypto.timingSafeEqual(dummy, dummy);
    return false;
  }

  try {
    return crypto.timingSafeEqual(bufA, bufB);
  } catch {
    return false;
  }
}

module.exports = async function handler(req, res) {
  // CORS
  res.setHeader("Access-Control-Allow-Origin",  "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Authorization");
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "GET")    return res.status(405).json({ ok: false, error: "Method not allowed." });

  // ── Auth: Bearer token ────────────────────────────────────────────────────
  if (!ADMIN_TOKEN) {
    return res.status(503).json({ ok: false, error: "Admin token not configured on server." });
  }

  const authHeader = req.headers["authorization"] || "";
  const supplied   = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : "";

  if (!supplied || !constantTimeEqual(supplied, ADMIN_TOKEN)) {
    // Fixed 200ms delay to frustrate brute-force attempts
    await new Promise((r) => setTimeout(r, 200));
    return res.status(401).json({ ok: false, error: "Invalid token." });
  }

  try {
    const { db } = await connectToDatabase();

    const now      = new Date();
    const last14d  = new Date(now - 14 * 86_400_000);
    const last7d   = new Date(now -  7 * 86_400_000);

    // ── All queries in parallel ────────────────────────────────────────────
    const [
      totalUsers,
      totalFiles,
      playsAgg,
      userGrowthRaw,
      trendingRaw,
      activeUsersRaw,
    ] = await Promise.all([

      // 1. Total registered users
      db.collection("users").countDocuments({}),

      // 2. Total audio files in the catalog
      db.collection("files").countDocuments({}),

      // 3. Global plays: sum total_plays across every user doc
      db.collection("users").aggregate([
        { $group: { _id: null, total: { $sum: "$total_plays" } } },
      ]).toArray(),

      // 4. User growth: new users per day, last 14 days
      db.collection("users").aggregate([
        { $match: { joined_at: { $gte: last14d } } },
        {
          $group: {
            _id:   { $dateToString: { format: "%Y-%m-%d", date: "$joined_at" } },
            count: { $sum: 1 },
          },
        },
        { $sort: { _id: 1 } },
      ]).toArray(),

      // 5. Trending tracks — resilient version:
      //    $match first to skip users with no listen_history (avoids $unwind errors
      //    on Atlas when the field is missing entirely, not just an empty array).
      db.collection("users").aggregate([
        { $match: { listen_history: { $exists: true, $ne: [] } } },
        { $unwind: "$listen_history" },
        { $match: { "listen_history.played_at": { $gte: last7d } } },
        {
          $group: {
            _id:   "$listen_history.track_id",
            name:  { $first: "$listen_history.name" },
            plays: { $sum: 1 },
          },
        },
        { $sort: { plays: -1 } },
        { $limit: 5 },
      ]).toArray(),

      // 6. Active users (last 24h)
      db.collection("users").countDocuments({
        last_active: { $gte: new Date(now - 86_400_000) },
      }),

    ]);

    // ── Fill in missing days in growth chart with 0 ────────────────────────
    const growthMap = {};
    for (const row of userGrowthRaw) {
      growthMap[row._id] = row.count;
    }
    const userGrowth = [];
    for (let i = 13; i >= 0; i--) {
      const d = new Date(now - i * 86_400_000);
      const key = d.toISOString().slice(0, 10);
      userGrowth.push({
        date:  key.slice(5), // "MM-DD" is enough for the chart
        users: growthMap[key] ?? 0,
      });
    }

    // ── Format trending tracks for BarChart ────────────────────────────────
    const trendingTracks = trendingRaw.map((t) => ({
      // Truncate long names for the chart axis
      name:  t.name ? t.name.slice(0, 28) + (t.name.length > 28 ? "…" : "") : "Unknown",
      plays: t.plays,
    }));

    return res.status(200).json({
      ok: true,
      stats: {
        totalUsers,
        totalFiles,
        totalPlays:   playsAgg[0]?.total ?? 0,
        activeUsers:  activeUsersRaw,
        userGrowth,
        trendingTracks,
      },
    });

  } catch (err) {
    console.error("admin-stats.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
};
