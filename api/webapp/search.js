/**
 * api/webapp/search.js
 * --------------------
 * GET /api/webapp/search?q=<query>
 *
 * Live search endpoint called by the Mini App's search screen.
 * The frontend debounces calls to this endpoint by 300ms on the client side,
 * so this function only fires when the user has paused typing.
 *
 * SEARCH LOGIC — mirrors Python's build_search_query() exactly:
 *   - Empty query         → return 20 latest tracks (same as /featured)
 *   - Single character    → prefix match on display_name
 *   - Multiple words      → AND-regex: every word must appear in display_name
 *
 * REQUEST:
 *   GET /api/webapp/search?q=husni
 *   Authorization: tma <initData>
 *
 * RESPONSE 200:
 *   {
 *     "ok": true,
 *     "query": "husni",
 *     "count": 4,
 *     "tracks": [
 *       { "id": "...", "name": "Husni Sultan New Menzuma", "is_favorite": false },
 *       ...
 *     ]
 *   }
 */

const { withAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");

/**
 * Build a MongoDB filter from a query string.
 * JavaScript port of Python's build_search_query() in db.py.
 *
 * @param {string} queryText
 * @returns {object} MongoDB filter document
 */
function buildSearchQuery(queryText) {
  if (!queryText || !queryText.trim()) {
    return { file_id: { $exists: true } };
  }

  const q = queryText.trim();

  // Single character → prefix match
  if (q.length === 1) {
    return {
      display_name: {
        $regex:   `^${escapeRegex(q)}`,
        $options: "i",
      },
    };
  }

  // Multiple words → AND: every word must appear somewhere in the name
  const words = q.split(/\s+/).filter(Boolean);

  if (words.length === 1) {
    return {
      display_name: {
        $regex:   escapeRegex(words[0]),
        $options: "i",
      },
    };
  }

  return {
    $and: words.map((word) => ({
      display_name: {
        $regex:   escapeRegex(word),
        $options: "i",
      },
    })),
  };
}

/**
 * Escape a string for safe use inside a RegExp.
 * Mirrors Python's re.escape().
 */
function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const query  = (req.query.q || "").trim();
  const userId = parseInt(req.telegramUser.id, 10);

  try {
    const { db } = await connectToDatabase();

    const filter = buildSearchQuery(query);

    // Fetch matching tracks and user favorites in parallel
    const [tracks, dbUser] = await Promise.all([
      db.collection("files")
        .find(filter, { projection: { display_name: 1 } })
        .sort({ _id: -1 })
        .limit(20)
        .toArray(),

      db.collection("users").findOne(
        { _id: userId },
        { projection: { favorites: 1 } }
      ),
    ]);

    const favoriteSet = new Set(dbUser?.favorites ?? []);

    const response = tracks.map((t) => ({
      id:          t._id.toString(),
      name:        t.display_name || "Unknown",
      is_favorite: favoriteSet.has(t.file_id ?? ""),
    }));

    return res.status(200).json({
      ok:     true,
      query,
      count:  response.length,
      tracks: response,
    });

  } catch (err) {
    console.error("search.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});
