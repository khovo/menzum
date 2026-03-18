/**
 * api/webapp/search.js
 * --------------------
 * GET /api/webapp/search?q=<query>&cursor=<last_id>
 *
 * Live search with cursor-based pagination.
 *
 * SEARCH LOGIC (mirrors Python build_search_query):
 *   - Empty query    → return latest 20 tracks (same as /featured)
 *   - Single char    → prefix match
 *   - Multiple words → AND-regex (every word must appear)
 *
 * PAGINATION:
 *   Same cursor model as /featured. First call omits cursor. Subsequent
 *   calls pass next_cursor to get the next page of results.
 *   The UI uses a "Load more" button (better than auto-scroll for search —
 *   users decide whether to dig deeper into results).
 *
 * RESPONSE 200:
 *   {
 *     "ok": true,
 *     "query": "husni",
 *     "tracks": [...],
 *     "has_more": false,
 *     "next_cursor": null
 *   }
 */

const { withAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const PAGE_SIZE = 20;

function buildSearchQuery(queryText) {
  if (!queryText || !queryText.trim()) {
    return { file_id: { $exists: true } };
  }
  const q = queryText.trim();
  if (q.length === 1) {
    return { display_name: { $regex: `^${escapeRegex(q)}`, $options: "i" } };
  }
  const words = q.split(/\s+/).filter(Boolean);
  if (words.length === 1) {
    return { display_name: { $regex: escapeRegex(words[0]), $options: "i" } };
  }
  return {
    $and: words.map((word) => ({
      display_name: { $regex: escapeRegex(word), $options: "i" },
    })),
  };
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const query       = (req.query.q      || "").trim();
  const cursorParam = (req.query.cursor  || "").trim();
  const limit       = Math.min(parseInt(req.query.limit || PAGE_SIZE, 10), 50);
  const userId      = parseInt(req.telegramUser.id, 10);

  try {
    const { db } = await connectToDatabase();

    const filter = buildSearchQuery(query);

    // Apply cursor if provided
    if (cursorParam && cursorParam.length === 24) {
      try {
        filter._id = { $lt: new ObjectId(cursorParam) };
      } catch {
        // Invalid ObjectId — ignore
      }
    }

    const [tracks, dbUser] = await Promise.all([
      db.collection("files")
        .find(filter, { projection: { display_name: 1, file_id: 1, thumb_file_id: 1 } })
        .sort({ _id: -1 })
        .limit(limit + 1)
        .toArray(),

      db.collection("users").findOne(
        { _id: userId },
        { projection: { favorites: 1 } }
      ),
    ]);

    const hasMore     = tracks.length > limit;
    const pageTracks  = hasMore ? tracks.slice(0, limit) : tracks;
    const favoriteSet = new Set(dbUser?.favorites ?? []);

    const response = pageTracks.map((t) => ({
      id:          t._id.toString(),
      name:        t.display_name || "Unknown",
      is_favorite: favoriteSet.has(t.file_id ?? ""),
      has_thumb:   !!t.thumb_file_id,
    }));

    return res.status(200).json({
      ok:          true,
      query,
      tracks:      response,
      has_more:    hasMore,
      next_cursor: hasMore ? response[response.length - 1].id : null,
    });

  } catch (err) {
    console.error("search.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});
