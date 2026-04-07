```javascript
/**
 * api/webapp/lyrics.js
 * --------------------
 * GET  /api/webapp/lyrics?track_id=<24-char-mongo-id>  — public, no auth
 * POST /api/webapp/lyrics                               — requires Telegram initData auth
 *
 * GET: Returns the single approved lyrics doc for a track.
 * - track_id is the MongoDB _id of the files doc (NOT file_id — never expose that)
 * - Looks up file_id server-side, queries lyrics collection
 * - Increments view_count fire-and-forget
 *
 * POST: Submit new lyrics for admin review.
 * Body: { track_id, content, language }
 * - Validates auth via HMAC initData
 * - Blocks duplicate pending submissions from the same user for the same track
 * - Inserts a "pending" lyrics doc
 * - Sends an approval/rejection keyboard to the admin via Telegram Bot API
 */

const { validateInitData }  = require("./_auth");
const { connectToDatabase } = require("./_db");
const { ObjectId }          = require("mongodb");

const BOT_TOKEN  = process.env.BOT_TOKEN;
const ADMIN_ID   = process.env.ADMIN_ID;

// Only allow valid 24-char hex ObjectId strings
const OBJECT_ID_RE = /^[a-f\d]{24}$/i;

// Allowed language codes
const VALID_LANGUAGES = new Set(["ar", "am", "mixed"]);

module.exports = async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin",  "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");

  if (req.method === "OPTIONS") return res.status(200).end();

  // ── GET: fetch approved lyrics ──────────────────────────────────────────────
  if (req.method === "GET") {
    return handleGet(req, res);
  }

  // ── POST: submit lyrics ─────────────────────────────────────────────────────
  if (req.method === "POST") {
    return handlePost(req, res);
  }

  return res.status(405).json({ ok: false, error: "Method not allowed." });
};

// ── GET handler ─────────────────────────────────────────────────────────────

async function handleGet(req, res) {
  const trackId = (req.query.track_id || "").trim();

  if (!OBJECT_ID_RE.test(trackId)) {
    return res.status(400).json({ ok: false, error: "Invalid track_id." });
  }

  try {
    const { db } = await connectToDatabase();

    // 1. Resolve track_id (Mongo ObjectId) → file_id — server-side only, never returned
    const fileDoc = await db.collection("files").findOne(
      { _id: new ObjectId(trackId) },
      { projection: { file_id: 1, display_name: 1 } }
    );

    if (!fileDoc) {
      return res.status(404).json({ ok: false, error: "Track not found." });
    }

    // 2. Fetch the single approved lyrics doc for this file_id
    const lyricsDoc = await db.collection("lyrics").findOne({
      file_id: fileDoc.file_id,
      status:  "approved",
    });

    if (!lyricsDoc) {
      return res.status(404).json({ ok: false, error: "No approved lyrics found." });
    }

    // 3. Increment view_count — fire-and-forget, never blocks the response
    db.collection("lyrics")
      .updateOne({ _id: lyricsDoc._id }, { $inc: { view_count: 1 } })
      .catch(() => {}); // swallow errors — analytics, not critical

    // 4. Return lyrics — file_id is intentionally excluded
    return res.status(200).json({
      ok:               true,
      track_name:       lyricsDoc.track_name,
      content:          lyricsDoc.content,
      language:         lyricsDoc.language,
      attribution_name: lyricsDoc.attribution_name,
      view_count:       lyricsDoc.view_count ?? 0,
    });

  } catch (err) {
    console.error("lyrics GET error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
}

// ── POST handler ─────────────────────────────────────────────────────────────

async function handlePost(req, res) {
  // 1. Validate Telegram initData auth (mirrors withAuth logic from _auth.js)
  const authHeader = req.headers["authorization"] || "";
  const initData   = authHeader.startsWith("tma ") ? authHeader.slice(4) : null;
  const { valid, user, error } = validateInitData(initData);

  if (!valid) {
    return res.status(401).json({ ok: false, error: error || "Unauthorized." });
  }

  const telegramUser = user;
  const userId       = parseInt(telegramUser.id, 10);

  // 2. Parse and validate body
  const { track_id, content, language } = req.body || {};

  if (!OBJECT_ID_RE.test(track_id || "")) {
    return res.status(400).json({ ok: false, error: "Invalid track_id." });
  }

  if (!content || typeof content !== "string" || !content.trim().startsWith("[")) {
    return res.status(400).json({ ok: false, error: "content must be a non-empty LRC string starting with '['." });
  }

  if (!VALID_LANGUAGES.has(language)) {
    return res.status(400).json({ ok: false, error: "language must be 'ar', 'am', or 'mixed'." });
  }

  try {
    const { db } = await connectToDatabase();

    // 3. Resolve track_id → file_id and track_name (server-side; file_id never sent to client)
    const fileDoc = await db.collection("files").findOne(
      { _id: new ObjectId(track_id) },
      { projection: { file_id: 1, display_name: 1 } }
    );

    if (!fileDoc) {
      return res.status(404).json({ ok: false, error: "Track not found." });
    }

    const fileId    = fileDoc.file_id;
    const trackName = fileDoc.display_name || "Unknown";

    // 4. Block duplicate pending submissions from the same user for the same track
    const existingPending = await db.collection("lyrics").findOne({
      file_id:      fileId,
      submitted_by: userId,
      status:       "pending",
    });

    if (existingPending) {
      return res.status(409).json({
        ok:    false,
        error: "You already have a pending submission for this track.",
      });
    }

    // 5. Resolve attribution_name from users.contributor.display_name
    const dbUser         = await db.collection("users").findOne(
      { _id: userId },
      { projection: { "contributor.display_name": 1, first_name: 1 } }
    );
    const attributionName =
      dbUser?.contributor?.display_name || dbUser?.first_name || "Anonymous";

    // 6. Insert the pending lyrics doc
    const lyricsDoc = {
      file_id:          fileId,
      track_name:       trackName,
      content:          content.trim(),
      format:           "lrc",
      language,
      status:           "pending",
      submitted_by:     userId,
      attribution_name: attributionName,
      submitted_at:     new Date(),
      approved_at:      null,
      view_count:       0,
    };

    const insertResult = await db.collection("lyrics").insertOne(lyricsDoc);
    const docId        = insertResult.insertedId.toString();

    // 7. Notify admin via Telegram Bot API — fire-and-forget (non-blocking)
    if (BOT_TOKEN && ADMIN_ID) {
      const notifyPayload = {
        chat_id:    parseInt(ADMIN_ID, 10),
        text:
          `📝 *New Lyrics Submission*\n\n` +
          `🎵 Track: \`${trackName}\`\n` +
          `👤 By: ${attributionName} (ID: \`${userId}\`)\n` +
          `🌐 Language: \`${language}\``,
        parse_mode:   "Markdown",
        reply_markup: {
          inline_keyboard: [[
            { text: "✅ Approve", callback_data: `lyrics_approve_${docId}` },
            { text: "❌ Reject",  callback_data: `lyrics_reject_${docId}`  },
          ]],
        },
      };

      fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(notifyPayload),
      }).catch((err) => console.error("Admin notify failed:", err));
    }

    return res.status(201).json({
      ok:      true,
      message: "Lyrics submitted for review.",
      doc_id:  docId,
    });

  } catch (err) {
    console.error("lyrics POST error:", err);
    return res.status(500).json({ ok: false, error: "Database error." });
  }
}

```
