/**
 * api/webapp/_auth.js
 * -------------------
 * Telegram Mini App authentication middleware.
 *
 * HOW TELEGRAM WEBAPP AUTH WORKS:
 * When your Mini App opens, Telegram injects a signed string called `initData`
 * into window.Telegram.WebApp.initData.  The frontend sends this in every API
 * request via the Authorization header: "tma <initData_string>".
 *
 * The server validates it by:
 *   1. Parsing the initData query string into key=value pairs
 *   2. Extracting and removing the `hash` field
 *   3. Sorting remaining pairs alphabetically and joining with \n
 *   4. HMAC-SHA256 signing the result with key = HMAC-SHA256("WebAppData", BOT_TOKEN)
 *   5. Comparing the computed hash to the one Telegram provided
 *
 * If hashes match → the data is genuinely from Telegram → user identity is trusted.
 * If hashes differ → reject with 401.
 *
 * This means NO user can forge a request to deliver audio to someone else's chat.
 *
 * REFERENCE: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
 */

const crypto = require("crypto");

const BOT_TOKEN = process.env.BOT_TOKEN;

/**
 * Validate a Telegram initData string.
 *
 * @param {string} initData  - The raw initData string from window.Telegram.WebApp.initData
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
    // Parse the initData as a URL query string
    const params = new URLSearchParams(initData);

    // Extract and remove the hash — we'll verify it
    const receivedHash = params.get("hash");
    if (!receivedHash) {
      return { valid: false, user: null, error: "Missing hash in initData." };
    }
    params.delete("hash");

    // Sort remaining key=value pairs alphabetically and join with \n
    const dataCheckString = Array.from(params.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, val]) => `${key}=${val}`)
      .join("\n");

    // Derive the secret key: HMAC-SHA256("WebAppData", BOT_TOKEN)
    const secretKey = crypto
      .createHmac("sha256", "WebAppData")
      .update(BOT_TOKEN)
      .digest();

    // Compute the expected hash
    const computedHash = crypto
      .createHmac("sha256", secretKey)
      .update(dataCheckString)
      .digest("hex");

    // Constant-time comparison to prevent timing attacks
    const isValid = crypto.timingSafeEqual(
      Buffer.from(computedHash, "hex"),
      Buffer.from(receivedHash,  "hex")
    );

    if (!isValid) {
      return { valid: false, user: null, error: "Hash mismatch — invalid initData." };
    }

    // Optional: check that auth_date is not too old (prevent replay attacks)
    const authDate = parseInt(params.get("auth_date") || "0", 10);
    const ageSeconds = Math.floor(Date.now() / 1000) - authDate;
    if (ageSeconds > 86400) {
      // initData older than 24 hours — reject
      return { valid: false, user: null, error: "initData expired." };
    }

    // Parse the user object (JSON-encoded string inside initData)
    const userRaw = params.get("user");
    const user    = userRaw ? JSON.parse(userRaw) : null;

    return { valid: true, user, error: null };

  } catch (err) {
    return { valid: false, user: null, error: `Validation exception: ${err.message}` };
  }
}

/**
 * Express-style middleware that validates the Authorization header and
 * attaches req.telegramUser to the request on success.
 *
 * Usage in any API route:
 *   const { withAuth } = require("./_auth");
 *   module.exports = withAuth(async (req, res) => { ... });
 */
function withAuth(handler) {
  return async function (req, res) {
    // CORS headers — Telegram WebApp runs on a different origin
    res.setHeader("Access-Control-Allow-Origin",  "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");

    // Preflight
    if (req.method === "OPTIONS") {
      return res.status(200).end();
    }

    // Extract initData from Authorization header: "tma <initData>"
    const authHeader = req.headers["authorization"] || "";
    const initData   = authHeader.startsWith("tma ")
      ? authHeader.slice(4)
      : null;

    const { valid, user, error } = validateInitData(initData);

    if (!valid) {
      return res.status(401).json({
        ok:    false,
        error: error || "Unauthorized",
      });
    }

    // Attach the validated Telegram user to the request
    req.telegramUser = user;
    return handler(req, res);
  };
}

module.exports = { validateInitData, withAuth };
