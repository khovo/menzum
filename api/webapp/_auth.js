/**
 * api/webapp/_auth.js
 * -------------------
 * Authentication for the webapp/mobile API.
 *
 * TWO accepted schemes (dual auth) on every endpoint wrapped in withAuth():
 *
 *   1. Telegram Mini App:  Authorization: tma <initData>
 *      The signed string Telegram injects into a Mini App. Validated by HMAC
 *      against BOT_TOKEN (see validateInitData). This keeps the existing bot /
 *      Mini App working exactly as before.
 *
 *   2. Mobile app JWT:     Authorization: Bearer <jwt>
 *      A long-lived token this backend issues after a Telegram-login handshake
 *      (see auth-start.js / auth-poll.js). Verified with JWT_SECRET (see _jwt.js).
 *
 * Either way, req.telegramUser.id ends up set to the Telegram user id, so every
 * downstream endpoint is identical regardless of how the caller authenticated.
 *
 * REFERENCE: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
 */

const crypto = require("crypto");
const { verify: verifyJwt } = require("./_jwt");

const BOT_TOKEN = process.env.BOT_TOKEN;

/**
 * Validate a Telegram initData string.
 * @returns {{ valid: boolean, user: object|null, error: string|null }}
 */
function validateInitData(initData) {
  if (!initData) {
    return { valid: false, user: null, error: "No initData provided." };
  }
  if (!BOT_TOKEN) {
    return { valid: false, user: null, error: "BOT_TOKEN not configured." };
  }

  try {
    const params = new URLSearchParams(initData);
    const receivedHash = params.get("hash");
    if (!receivedHash) {
      return { valid: false, user: null, error: "Missing hash in initData." };
    }
    params.delete("hash");

    const dataCheckString = Array.from(params.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, val]) => `${key}=${val}`)
      .join("\n");

    const secretKey = crypto.createHmac("sha256", "WebAppData").update(BOT_TOKEN).digest();
    const computedHash = crypto.createHmac("sha256", secretKey).update(dataCheckString).digest("hex");

    const isValid = crypto.timingSafeEqual(
      Buffer.from(computedHash, "hex"),
      Buffer.from(receivedHash, "hex")
    );
    if (!isValid) {
      return { valid: false, user: null, error: "Hash mismatch — invalid initData." };
    }

    const authDate = parseInt(params.get("auth_date") || "0", 10);
    const ageSeconds = Math.floor(Date.now() / 1000) - authDate;
    if (ageSeconds > 86400) {
      return { valid: false, user: null, error: "initData expired." };
    }

    const userRaw = params.get("user");
    const user = userRaw ? JSON.parse(userRaw) : null;
    return { valid: true, user, error: null };
  } catch (err) {
    return { valid: false, user: null, error: `Validation exception: ${err.message}` };
  }
}

/**
 * Set the shared CORS headers used by every endpoint. Allows the mobile app and
 * the cross-origin Mini App, permits the Authorization + Range headers, and
 * exposes the headers an audio/PDF player needs for seeking.
 */
function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type, Range");
  res.setHeader("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges");
}

/**
 * Wrap a handler with dual auth (Bearer JWT OR Telegram initData) + CORS.
 * On success attaches req.telegramUser ({ id, ... }) and calls the handler.
 */
function withAuth(handler) {
  return async function (req, res) {
    setCors(res);
    if (req.method === "OPTIONS") {
      return res.status(200).end();
    }

    const authHeader = req.headers["authorization"] || "";

    // 1) Mobile app JWT
    if (authHeader.startsWith("Bearer ")) {
      const payload = verifyJwt(authHeader.slice(7));
      if (payload && payload.uid) {
        req.telegramUser = { id: payload.uid, via: "jwt" };
        return handler(req, res);
      }
      return res.status(401).json({ ok: false, error: "Invalid or expired token." });
    }

    // 2) Telegram Mini App initData
    if (authHeader.startsWith("tma ")) {
      const { valid, user, error } = validateInitData(authHeader.slice(4));
      if (!valid) {
        return res.status(401).json({ ok: false, error: error || "Unauthorized" });
      }
      req.telegramUser = user;
      return handler(req, res);
    }

    return res.status(401).json({
      ok: false,
      error: "Missing Authorization. Use 'tma <initData>' or 'Bearer <jwt>'.",
    });
  };
}

module.exports = { validateInitData, withAuth, setCors };
