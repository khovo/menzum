/**
 * api/webapp/play.js
 * ------------------
 * Auth: Bearer <jwt> OR tma <initData>  (dual auth via withAuth)
 *
 * GET  /api/webapp/play?id=<track_id>&action=stream
 *      → STREAMS the track's audio bytes (Content-Type + Range/seek, 200/206).
 *        This is what `audio_url` in featured/search/library points to. The bot
 *        token and file_id are never exposed (we proxy the bytes). HEAD supported.
 *
 * POST /api/webapp/play   { track_id, action: "play" | "favorite" }
 *      → "play":     sendAudio into the user's Telegram chat (used by the bot/Mini App)
 *      → "favorite": toggle favorite in the DB
 *      (UNCHANGED — the bot still relies on this.)
 *
 * (Audio streaming lives here, not in its own audio.js, to stay under Vercel
 * Hobby's 12-Serverless-Function limit.)
 */
const { withOptionalAuth } = require("./_auth");
const { connectToDatabase } = require("./_db");
const { isRateLimited, clientIp } = require("./_rateLimit");
const { ObjectId } = require("mongodb");
const { Readable } = require("stream");

const BOT_TOKEN = process.env.BOT_TOKEN;
const OID_RE = /^[a-f\d]{24}$/i;

async function telegramCall(method, payload) {
  const res = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

function audioContentType(path) {
  const p = path.toLowerCase();
  if (p.endsWith(".oga") || p.endsWith(".ogg")) return "audio/ogg";
  if (p.endsWith(".m4a") || p.endsWith(".mp4") || p.endsWith(".aac")) return "audio/mp4";
  if (p.endsWith(".wav")) return "audio/wav";
  if (p.endsWith(".opus")) return "audio/opus";
  return "audio/mpeg";
}

// ── GET: stream the audio bytes ───────────────────────────────────────────────
async function streamAudio(req, res) {
  // H2: this is anonymous-allowed and pulls real bytes through the shared
  // BOT_TOKEN — an unthrottled scraping loop here both scrapes the catalog
  // and burns Telegram's per-bot rate limit against the live bot.
  if (isRateLimited(clientIp(req), { max: 30, windowMs: 60_000 })) {
    return res.status(429).json({ ok: false, error: "Too many requests. Please slow down." });
  }

  const id = (req.query.id || req.query.track_id || "").trim();
  if (!OID_RE.test(id)) return res.status(400).json({ ok: false, error: "Invalid id." });
  if (!BOT_TOKEN) return res.status(503).json({ ok: false, error: "BOT_TOKEN missing." });

  const { db } = await connectToDatabase();
  const doc = await db.collection("files").findOne(
    { _id: new ObjectId(id), hidden: { $ne: true } },
    { projection: { file_id: 1 } }
  );
  if (!doc?.file_id) return res.status(404).json({ ok: false, error: "Track not found." });

  const gfRes = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/getFile?file_id=${doc.file_id}`);
  const gfData = await gfRes.json();
  if (!gfData.ok || !gfData.result?.file_path) {
    return res.status(404).json({ ok: false, error: "Could not resolve audio file." });
  }

  const filePath = gfData.result.file_path;
  const tgUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${filePath}`;
  const fetchOptions = { method: req.method, headers: {} };
  if (req.headers.range) fetchOptions.headers["Range"] = req.headers.range;

  const tgFileRes = await fetch(tgUrl, fetchOptions);

  res.setHeader("Content-Type", audioContentType(filePath));
  res.setHeader("Accept-Ranges", "bytes");
  res.setHeader("Cache-Control", "private, max-age=3000");
  if (tgFileRes.headers.has("content-length")) res.setHeader("Content-Length", tgFileRes.headers.get("content-length"));
  if (tgFileRes.headers.has("content-range")) res.setHeader("Content-Range", tgFileRes.headers.get("content-range"));

  res.status(tgFileRes.status); // 200 or 206

  if (req.method === "HEAD") return res.end();

  if (tgFileRes.body) {
    if (typeof tgFileRes.body.pipe === "function") tgFileRes.body.pipe(res);
    else Readable.fromWeb(tgFileRes.body).pipe(res);
  } else {
    const buffer = await tgFileRes.arrayBuffer();
    res.send(Buffer.from(buffer));
  }
}

module.exports = withOptionalAuth(async function handler(req, res) {
  // GET / HEAD → audio streaming (public — anonymous allowed)
  if (req.method === "GET" || req.method === "HEAD") {
    try {
      return await streamAudio(req, res);
    } catch (err) {
      console.error("play.js stream error:", err.message);
      return res.status(500).json({ ok: false, error: "Server error." });
    }
  }

  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  // POST (favorite / deliver-to-chat) still requires a real user.
  if (!req.telegramUser) {
    return res.status(401).json({ ok: false, error: "Authentication required." });
  }

  const { track_id, action = "play" } = req.body || {};
  const userId = parseInt(req.telegramUser.id, 10);

  if (!track_id || track_id.length !== 24) {
    return res.status(400).json({ ok: false, error: "Invalid track_id." });
  }
  if (!["play", "favorite"].includes(action)) {
    return res.status(400).json({ ok: false, error: "Invalid action." });
  }

  try {
    const { db } = await connectToDatabase();

    const track = await db.collection("files").findOne(
      { _id: new ObjectId(track_id), hidden: { $ne: true } },
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
      const tgResult = await telegramCall("sendAudio", {
        chat_id: userId,
        audio: track.file_id,
        caption: `${track.display_name}\n\n@Almadihbot`,
        parse_mode: "Markdown",
        reply_markup: {
          inline_keyboard: [
            [{ text: "➕ Add to Playlist", callback_data: `pl_add_${track_id}` }],
            [{ text: "❤️ Fav", callback_data: `fav_${track_id}` }],
          ],
        },
      });

      if (!tgResult.ok) {
        const tgError = tgResult.description || "Telegram API error";
        console.error("sendAudio failed:", tgError);
        return res.status(502).json({
          ok: false,
          error: tgError.includes("bot was blocked") || tgError.includes("chat not found")
            ? "Please start the bot first: send /start to @Almadihbot"
            : tgError,
        });
      }

      db.collection("users").updateOne(
        { _id: userId },
        {
          $inc: { total_plays: 1 },
          $push: {
            listen_history: {
              $each: [{ track_id, name: track.display_name, played_at: new Date() }],
              $slice: -50,
              $position: 0,
            },
          },
        },
        { upsert: true }
      ).catch((e) => console.error("listen tracking failed:", e));

      return res.status(200).json({ ok: true, action: "play", track_name: track.display_name });
    }

    // ── ACTION: favorite ─────────────────────────────────────────────────────
    if (action === "favorite") {
      const dbUser = await db.collection("users").findOne(
        { _id: userId },
        { projection: { favorites: 1 } }
      );
      const favorites = dbUser?.favorites ?? [];
      const fileId = track.file_id;
      const alreadyFav = favorites.includes(fileId);

      if (alreadyFav) {
        await db.collection("users").updateOne({ _id: userId }, { $pull: { favorites: fileId } });
      } else {
        await db.collection("users").updateOne({ _id: userId }, { $addToSet: { favorites: fileId } }, { upsert: true });
      }
      return res.status(200).json({ ok: true, action: "favorite", is_favorite: !alreadyFav });
    }
  } catch (err) {
    console.error("play.js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
});
