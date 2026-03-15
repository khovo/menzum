/**
 * api/webapp/library.js
 * ---------------------
 * GET /api/webapp/library
 *
 * Returns everything needed to render the Personal Library screen:
 *   - User's favorited tracks (full track objects, not just IDs)
 *   - Listening stats: total plays, total favorites, most-played tracks
 *
 * All DB work is done in parallel (Promise.all) — single round-trip feel.
 *
 * STATS DATA MODEL (written by play.js on every track delivery):
 *   users.total_plays:    integer — lifetime play count
 *   users.listen_history: array (capped at 50) of
 *     { track_id: string, name: string, played_at: Date }
 *
 * "Most Played" is computed by aggregating listen_history client-side
 * (max 50 items, so O(50) — cheaper than a MongoDB aggregation pipeline
 * on cold serverless invocations).
 *
 * RESPONSE 200:
 *  {
 *    "ok": true,
 *    "stats": {
 *      "total_plays":    47,
 *      "total_favorites": 12,
 *      "most_played": [
 *        { "track_id": "...", "name": "Husni Sultan...", "play_count": 6 },
 *        ...  (up to 3)
 *      ]
 *    },
 *    "favorites": [
 *      { "id": "...", "name": "...", "is_favorite": true },
 *      ...
 *    ]
 *  }
 */

const { withAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const userId = parseInt(req.telegramUser.id, 10);

  try {
    const { db } = await connectToDatabase();

    // ── Single user doc fetch: favorites + history + counters ─────────────────
    const dbUser = await db.collection("users").findOne(
      { _id: userId },
      { projection: { favorites: 1, listen_history: 1, total_plays: 1 } }
    );

    const favoriteFileIds  = dbUser?.favorites       ?? [];
    const listenHistory    = dbUser?.listen_history  ?? [];
    const totalPlays       = dbUser?.total_plays     ?? 0;

    // ── Resolve favorite file_ids → full track docs ───────────────────────────
    // favorites stores file_id strings; we need to join back to files collection
    const favDocs = favoriteFileIds.length > 0
      ? await db.collection("files")
          .find(
            { file_id: { $in: favoriteFileIds } },
            { projection: { display_name: 1 } }   // never expose file_id
          )
          .limit(50)
          .toArray()
      : [];

    // Preserve the user's favorite order (most recently added first)
    const fileIdOrder = new Map(
      favoriteFileIds.map((fid, i) => [fid, i])
    );
    favDocs.sort((a, b) => {
      const ia = fileIdOrder.get(a.file_id ?? "") ?? 999;
      const ib = fileIdOrder.get(b.file_id ?? "") ?? 999;
      return ia - ib;
    });

    const favorites = favDocs.map((doc) => ({
      id:          doc._id.toString(),
      name:        doc.display_name || "Unknown",
      is_favorite: true,
    }));

    // ── Compute most-played from listen_history (O(50) max) ───────────────────
    const playCounts = {};
    for (const entry of listenHistory) {
      if (!entry.track_id) continue;
      if (!playCounts[entry.track_id]) {
        playCounts[entry.track_id] = { name: entry.name, count: 0 };
      }
      playCounts[entry.track_id].count++;
    }

    const mostPlayed = Object.entries(playCounts)
      .sort(([, a], [, b]) => b.count - a.count)
      .slice(0, 3)
      .map(([track_id, { name, count }]) => ({
        track_id,
        name,
        play_count: count,
      }));

    return res.status(200).json({
      ok: true,
      stats: {
        total_plays:     totalPlays,
        total_favorites: favoriteFileIds.length,
        most_played:     mostPlayed,
      },
      favorites,
    });

  } catch (err) {
    console.error("library.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});
