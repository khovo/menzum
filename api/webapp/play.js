/**
 * api/webapp/play.js
 * ------------------
 * POST /api/webapp/play
 *
 * THE CRITICAL BRIDGE — connects the Mini App's UI to the bot's audio delivery.
 *
 * WHY THIS EXISTS:
 * Telegram Mini Apps cannot play audio directly (there is no WebApp audio API).
 * Instead, when the user taps ▶ on any track in the Mini App, the frontend
 * calls this endpoint with the track ID.  This server-side function:
 *   1. Looks up the file_id from MongoDB (never exposed to the client)
 *   2. Calls Telegram's sendAudio API directly using the Bot Token
 *   3. The audio appears in the user's bot chat with full inline keyboard
 *
 * This design is a FEATURE not a limitation:
 *   - The audio lands in chat with ❤️ Fav + ➕ Playlist buttons — full bot UX
 *   - file_id is never exposed to the frontend — prevents token harvesting
 *   - The Mini App is a discovery layer; the chat is the listening experience
 *
 * ACTIONS:
 *   "play"     → sendAudio to user's chat
 *   "favorite" → toggle favorite in DB (same logic as Python toggle_favorite())
 *
 * REQUEST:
 *   POST /api/webapp/play
 *   Authorization: tma <initData>
 *   Content-Type: application/json
 *   { "track_id": "64a1b2c3d4e5f6a7b8c9d0e1", "action": "play" | "favorite" }
 *
 * RESPONSE 200 (play):
 *   { "ok": true, "action": "play", "track_name": "Husni Sultan..." }
 *
 * RESPONSE 200 (favorite):
 *   { "ok": true, "action": "favorite", "is_favorite": true }
 *
 * RESPONSE 404:
 *   { "ok": false, "error": "Track not found." }
 */

const { withAuth }          = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const BOT_TOKEN = process.env.BOT_TOKEN;

/**
 * Call Telegram Bot API — minimal fetch wrapper.
 * @param {string} method  - Telegram API method name
 * @param {object} payload - JSON body
 */
async function telegramCall(method, payload) {
  const url = `https://api.telegram.org/bot${BOT_TOKEN}/${method}`;
  const res  = await fetch(url, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  return res.json();
}

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const { track_id, action = "play" } = req.body || {};
  const userId = parseInt(req.telegramUser.id, 10);

  // Validate track_id is a valid ObjectId string
  if (!track_id || track_id.length !== 24) {
    return res.status(400).json({ ok: false, error: "Invalid track_id." });
  }

  if (!["play", "favorite"].includes(action)) {
    return res.status(400).json({ ok: false, error: "Invalid action." });
  }

  try {
    const { db } = await connectToDatabase();

    // Fetch the track — we need file_id (for play) and display_name (for both)
    const track = await db.collection("files").findOne(
      { _id: new ObjectId(track_id) },
      { projection: { file_id: 1, display_name: 1 } }
    );

    if (!track) {
      return res.status(404).json({ ok: false, error: "Track not found." });
    }

    // ── ACTION: play ──────────────────────────────────────────────────────────
    if (action === "play") {
      if (!BOT_TOKEN) {
        return res.status(500).json({ ok: false, error: "BOT_TOKEN not configured." });
      }

      // Send audio to the user's chat with the same inline keyboard as the bot
      const tgResult = await telegramCall("sendAudio", {
        chat_id:    userId,
        audio:      track.file_id,
        caption:    `${track.display_name}\n\n@Almadihbot`,
        parse_mode: "Markdown",
        reply_markup: {
          inline_keyboard: [
            [{ text: "➕ Add to Playlist", callback_data: `pl_add_${track_id}` }],
            [{ text: "❤️ Fav",             callback_data: `fav_${track_id}` }],
          ],
        },
      });

      if (!tgResult.ok) {
        // Common case: user never started the bot — they must /start it first
        const tgError = tgResult.description || "Telegram API error";
        console.error("sendAudio failed:", tgError);
        return res.status(502).json({
          ok:    false,
          error: tgError.includes("bot was blocked") || tgError.includes("chat not found")
            ? "Please start the bot first: send /start to @Almadihbot"
            : tgError,
        });
      }

      // ── Track listen history (fire-and-forget, never blocks the response) ──
      // Appends to a capped listen_history array (max 50 entries) and bumps
      // total_plays counter.  Used by /api/webapp/library for stats.
      // $slice: -50 keeps only the 50 most recent plays — no unbounded growth.
      db.collection("users").updateOne(
        { _id: userId },
        {
          $inc:  { total_plays: 1 },
          $push: {
            listen_history: {
              $each:     [{ track_id, name: track.display_name, played_at: new Date() }],
              $slice:    -50,
              $position: 0,
            },
          },
        },
        { upsert: true }
      ).catch((e) => console.error("listen tracking failed:", e)); // intentional no-await

      return res.status(200).json({
        ok:         true,
        action:     "play",
        track_name: track.display_name,
      });
    }

    // ── ACTION: favorite ─────────────────────────────────────────────────────
    // Mirrors Python's toggle_favorite() in db.py exactly.
    if (action === "favorite") {
      const dbUser     = await db.collection("users").findOne(
        { _id: userId },
        { projection: { favorites: 1 } }
      );

      const favorites   = dbUser?.favorites ?? [];
      const fileId      = track.file_id;
      const alreadyFav  = favorites.includes(fileId);

      if (alreadyFav) {
        await db.collection("users").updateOne(
          { _id: userId },
          { $pull: { favorites: fileId } }
        );
      } else {
        await db.collection("users").updateOne(
          { _id: userId },
          { $addToSet: { favorites: fileId } },
          { upsert: true }
        );
      }

      return res.status(200).json({
        ok:          true,
        action:      "favorite",
        is_favorite: !alreadyFav,
      });
    }

  } catch (err) {
    console.error("play.js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
});
