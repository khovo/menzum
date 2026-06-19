/**
 * api/webapp/_auth.js
 * -------------------
 * Authentication for the webapp/mobile API + a tiny self-contained JWT helper.
 *
 * (JWT lives here rather than in its own file because Vercel's Hobby plan caps a
 * deployment at 12 Serverless Functions and `api/webapp/*.js` is already at the
 * limit — every extra .js file would be one more function. Shared modules like
 * this one are bundled into the endpoints that require them.)
 *
 * TWO accepted schemes (dual auth) on every endpoint wrapped in withAuth():
 *   1. Telegram Mini App:  Authorization: tma <initData>   (validated via HMAC/BOT_TOKEN)
 *   2. Mobile app JWT:     Authorization: Bearer <jwt>      (HS256, JWT_SECRET)
 * Either way req.telegramUser.id ends up as the Telegram user id.
 */

const crypto = require("crypto");

const BOT_TOKEN = process.env.BOT_TOKEN;
const JWT_SECRET = (process.env.JWT_SECRET || "").trim();
const JWT_DEFAULT_DAYS = 90;

// ── JWT (HS256) ───────────────────────────────────────────────────────────────

function b64url(input) {
  return Buffer.from(input).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function jwtConfigured() {
  return !!JWT_SECRET;
}

/** Sign a payload → JWT, or null if JWT_SECRET is unset. */
function jwtSign(payload, days = JWT_DEFAULT_DAYS) {
  if (!JWT_SECRET) return null;
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = b64url(JSON.stringify({ ...payload, iat: now, exp: now + days * 86400 }));
  const data = `${header}.${body}`;
  const sig = b64url(crypto.createHmac("sha256", JWT_SECRET).update(data).digest());
  return `${data}.${sig}`;
}

/** Verify a JWT → payload, or null if invalid/expired/misconfigured. */
function jwtVerify(token) {
  if (!JWT_SECRET || !token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [h, p, s] = parts;
  const expected = b64url(crypto.createHmac("sha256", JWT_SECRET).update(`${h}.${p}`).digest());
  const a = Buffer.from(s);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  let payload;
  try {
    payload = JSON.parse(Buffer.from(p.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
  } catch {
    return null;
  }
  if (payload.exp && Math.floor(Date.now() / 1000) > payload.exp) return null;
  return payload;
}

// ── Telegram Mini App initData ────────────────────────────────────────────────

function validateInitData(initData) {
  if (!initData) return { valid: false, user: null, error: "No initData provided." };
  if (!BOT_TOKEN) return { valid: false, user: null, error: "BOT_TOKEN not configured." };

  try {
    const params = new URLSearchParams(initData);
    const receivedHash = params.get("hash");
    if (!receivedHash) return { valid: false, user: null, error: "Missing hash in initData." };
    params.delete("hash");

    const dataCheckString = Array.from(params.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, val]) => `${key}=${val}`)
      .join("\n");

    const secretKey = crypto.createHmac("sha256", "WebAppData").update(BOT_TOKEN).digest();
    const computedHash = crypto.createHmac("sha256", secretKey).update(dataCheckString).digest("hex");

    const isValid = crypto.timingSafeEqual(Buffer.from(computedHash, "hex"), Buffer.from(receivedHash, "hex"));
    if (!isValid) return { valid: false, user: null, error: "Hash mismatch — invalid initData." };

    const authDate = parseInt(params.get("auth_date") || "0", 10);
    if (Math.floor(Date.now() / 1000) - authDate > 86400) {
      return { valid: false, user: null, error: "initData expired." };
    }

    const userRaw = params.get("user");
    return { valid: true, user: userRaw ? JSON.parse(userRaw) : null, error: null };
  } catch (err) {
    return { valid: false, user: null, error: `Validation exception: ${err.message}` };
  }
}

// ── CORS + dual-auth middleware ───────────────────────────────────────────────

function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type, Range");
  res.setHeader("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges");
}

/** Resolve the caller from an Authorization header → { id, ... } or null. */
function resolveUser(req) {
  const authHeader = req.headers["authorization"] || "";
  if (authHeader.startsWith("Bearer ")) {
    const payload = jwtVerify(authHeader.slice(7));
    if (payload && payload.uid) return { id: payload.uid, via: "jwt" };
    return null;
  }
  if (authHeader.startsWith("tma ")) {
    const { valid, user } = validateInitData(authHeader.slice(4));
    if (valid) return user;
    return null;
  }
  return null;
}

/** Wrap a handler with dual auth (Bearer JWT OR Telegram initData) + CORS. */
function withAuth(handler) {
  return async function (req, res) {
    setCors(res);
    if (req.method === "OPTIONS") return res.status(200).end();

    const user = resolveUser(req);
    if (!user) {
      return res.status(401).json({
        ok: false,
        error: "Missing or invalid Authorization. Use 'tma <initData>' or 'Bearer <jwt>'.",
      });
    }
    req.telegramUser = user;
    return handler(req, res);
  };
}

/**
 * Like withAuth, but auth is OPTIONAL: if a valid Bearer/initData is present,
 * req.telegramUser is the real user; if not, it's null (anonymous) and the
 * handler still runs. Used for public GET endpoints (featured/search/streams)
 * where anonymous callers get is_favorite:false and no per-user side effects.
 */
function withOptionalAuth(handler) {
  return async function (req, res) {
    setCors(res);
    if (req.method === "OPTIONS") return res.status(200).end();
    req.telegramUser = resolveUser(req); // user object, or null when anonymous
    return handler(req, res);
  };
}

module.exports = {
  validateInitData,
  withAuth,
  withOptionalAuth,
  setCors,
  resolveUser,
  jwtSign,
  jwtVerify,
  jwtConfigured,
};
