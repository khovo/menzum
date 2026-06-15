/**
 * api/webapp/_jwt.js
 * ------------------
 * Minimal HS256 JWT sign/verify using Node's built-in crypto — no extra
 * dependency. Used to issue long-lived tokens to the mobile app after a
 * Telegram-login handshake.
 *
 * Secret comes from the JWT_SECRET env var (set it in the Vercel project).
 * If JWT_SECRET is unset, sign()/verify() return null so callers can degrade
 * gracefully (the bot's Mini App initData auth keeps working regardless).
 *
 * Token payload: { uid: <telegram_user_id>, iat, exp }. Default lifetime 90 days.
 */
const crypto = require("crypto");

const SECRET = (process.env.JWT_SECRET || "").trim();
const DEFAULT_DAYS = 90;

function b64url(input) {
  return Buffer.from(input)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function b64urlJson(obj) {
  return b64url(JSON.stringify(obj));
}

function isConfigured() {
  return !!SECRET;
}

/** Sign a payload → JWT string, or null if JWT_SECRET is not configured. */
function sign(payload, days = DEFAULT_DAYS) {
  if (!SECRET) return null;
  const header = { alg: "HS256", typ: "JWT" };
  const now = Math.floor(Date.now() / 1000);
  const body = { ...payload, iat: now, exp: now + days * 86400 };
  const data = `${b64urlJson(header)}.${b64urlJson(body)}`;
  const sig = b64url(crypto.createHmac("sha256", SECRET).update(data).digest());
  return `${data}.${sig}`;
}

/** Verify a JWT → payload object, or null if invalid/expired/misconfigured. */
function verify(token) {
  if (!SECRET || !token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [h, p, s] = parts;

  const expected = b64url(crypto.createHmac("sha256", SECRET).update(`${h}.${p}`).digest());
  const a = Buffer.from(s);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;

  let payload;
  try {
    const json = Buffer.from(p.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8");
    payload = JSON.parse(json);
  } catch {
    return null;
  }
  if (payload.exp && Math.floor(Date.now() / 1000) > payload.exp) return null;
  return payload;
}

module.exports = { sign, verify, isConfigured };
