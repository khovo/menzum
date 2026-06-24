/**
 * api/webapp/featured.js
 * ----------------------
 * GET /api/webapp/featured?cursor=<last_id>&limit=20
 *
 * PAGINATION MODEL: cursor-based using MongoDB _id.
 *
 * WHY CURSOR NOT SKIP:
 *   .skip(N) on a 1,150-document collection requires MongoDB to scan and discard
 *   N documents on every request. Cursor-based pagination filters _id < cursor
 *   which uses the _id index directly — O(log n) at any scroll depth.
 *
 * FIRST PAGE:  GET /api/webapp/featured
 *              (no cursor) → returns first 20, sorted by _id desc
 *
 * NEXT PAGES:  GET /api/webapp/featured?cursor=<next_cursor_from_previous_response>
 *              → returns next 20 tracks with _id < cursor
 *
 * RESPONSE 200:
 *   {
 *     "ok": true,
 *     "tracks":      [...],         // up to `limit` tracks
 *     "has_more":    true,          // false when the catalog is exhausted
 *     "next_cursor": "64a1b2..."    // pass this as cursor on the next call
 *   }
 */

const { withOptionalAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const PAGE_SIZE = 20;

module.exports = withOptionalAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const cursorParam = (req.query.cursor || "").trim();
  const limit       = Math.min(parseInt(req.query.limit || PAGE_SIZE, 10), 50);

  try {
    const { db }  = await connectToDatabase();
    const userId  = req.telegramUser ? parseInt(req.telegramUser.id, 10) : null;

    // Build filter: if cursor provided, only return tracks older than cursor
    const filter = { file_id: { $exists: true }, hidden: { $ne: true } };
    if (cursorParam && cursorParam.length === 24) {
      try {
        filter._id = { $lt: new ObjectId(cursorParam) };
      } catch {
        // Invalid ObjectId — ignore, start from top
      }
    }

    // Fetch limit+1 to cheaply detect whether another page exists
    const [tracks, dbUser] = await Promise.all([
      db.collection("files")
        .find(filter, { projection: { display_name: 1, file_id: 1, thumb_file_id: 1 } })
        .sort({ _id: -1 })
        .limit(limit + 1)
        .toArray(),

      userId
        ? db.collection("users").findOne({ _id: userId }, { projection: { favorites: 1 } })
        : Promise.resolve(null),
    ]);

    const hasMore    = tracks.length > limit;
    const pageTracks = hasMore ? tracks.slice(0, limit) : tracks;
    const favoriteSet = new Set(dbUser?.favorites ?? []);

    const base = `https://${req.headers.host || "menzum.vercel.app"}`;
    const response = pageTracks.map((t) => ({
      id:          t._id.toString(),
      name:        t.display_name || "Unknown",
      is_favorite: favoriteSet.has(t.file_id ?? ""),
      has_thumb:   !!t.thumb_file_id,
      audio_url:   `${base}/api/webapp/play?id=${t._id}&action=stream`,
      thumb_url:   t.thumb_file_id ? `${base}/api/webapp/thumb?id=${t._id}` : null,
    }));

    return res.status(200).json({
      ok:          true,
      tracks:      response,
      has_more:    hasMore,
      next_cursor: hasMore ? response[response.length - 1].id : null,
    });

  } catch (err) {
    console.error("featured.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});
