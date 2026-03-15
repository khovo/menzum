/**
 * api/webapp/featured.js
 * ----------------------
 * GET /api/webapp/featured
 *
 * Returns the 20 most recently added tracks (sorted by _id descending,
 * identical to the bot's inline query empty-search handler).
 *
 * Also returns which tracks the current user has favorited so the ♡ button
 * renders in the correct state without a second round-trip.
 *
 * REQUEST:
 *   GET /api/webapp/featured
 *   Authorization: tma <initData>
 *
 * RESPONSE 200:
 *   {
 *     "ok": true,
 *     "tracks": [
 *       {
 *         "id": "64a1b2c3d4e5f6a7b8c9d0e1",
 *         "name": "NEBEYE NEBEYE SELEHADIN HUSSEN",
 *         "is_favorite": false
 *       },
 *       ...
 *     ]
 *   }
 *
 * NOTE: file_id is intentionally NOT returned to the frontend.
 * The client never needs it — audio delivery goes through /api/webapp/play,
 * which looks up the file_id server-side. This prevents clients from
 * extracting Telegram file IDs directly.
 */

const { withAuth }         = require("./_auth");
const { connectToDatabase } = require("./_db");

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  try {
    const { db }  = await connectToDatabase();
    const userId  = parseInt(req.telegramUser.id, 10);

    // Fetch latest 20 tracks and the user's favorites in parallel
    const [tracks, dbUser] = await Promise.all([
      db.collection("files")
        .find(
          { file_id: { $exists: true } },
          { projection: { display_name: 1 } }   // never expose file_id
        )
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
      // file_id deliberately omitted
    }));

    return res.status(200).json({ ok: true, tracks: response });

  } catch (err) {
    console.error("featured.js error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
});
