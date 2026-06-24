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
const GENRES = new Set(["eshq", "abret", "katbare", "raya"]);

module.exports = withOptionalAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const cursorParam = (req.query.cursor || "").trim();
  const category    = (req.query.category || "all").trim().toLowerCase();
  const limit       = Math.min(parseInt(req.query.limit || PAGE_SIZE, 10), 50);

  try {
    const { db }  = await connectToDatabase();
    const userId  = req.telegramUser ? parseInt(req.telegramUser.id, 10) : null;

    // Base filter — every category excludes hidden docs.
    const filter = { file_id: { $exists: true }, hidden: { $ne: true } };
    if (category === "neshida") {
      // Auto-detected from the title — no stored field needed.
      filter.display_name = { $regex: "ነሺዳ|neshida", $options: "i" };
    } else if (GENRES.has(category)) {
      filter.genre = category;
    }

    // Per-category sort. _id is the cursor key for ALL categories (ObjectId is
    // creation-ordered, so "new" == _id desc); "new"/"trending" prepend their
    // sort field with _id as the stable tiebreak so cursor paging stays valid.
    let sort = { _id: -1 };
    if (category === "new") sort = { created_at: -1, _id: -1 };
    else if (category === "trending") sort = { play_count: -1, _id: -1 };

    // Cursor: _id < cursor (works for every category, incl. the neshida regex).
    if (cursorParam && cursorParam.length === 24) {
      try { filter._id = { $lt: new ObjectId(cursorParam) }; } catch { /* ignore */ }
    }

    // Fetch limit+1 to cheaply detect whether another page exists
    const [tracks, dbUser] = await Promise.all([
      db.collection("files")
        .find(filter, { projection: { display_name: 1, file_id: 1, thumb_file_id: 1, genre: 1 } })
        .sort(sort)
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
      genre:       t.genre || null,
      is_favorite: favoriteSet.has(t.file_id ?? ""),
      has_thumb:   !!t.thumb_file_id,
      audio_url:   `${base}/api/webapp/play?id=${t._id}&action=stream`,
      thumb_url:   t.thumb_file_id ? `${base}/api/webapp/thumb?id=${t._id}` : null,
    }));

    return res.status(200).json({
      ok:          true,
      category,
      tracks:      response,
      has_more:    hasMore,
      next_cursor: hasMore ? response[response.length - 1].id : null,
    });

  } catch (err) {
    console.error("featured.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});
