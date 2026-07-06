/**
 * lib/auth.js
 * -----------
 * Single-admin JWT session. There is exactly one admin account, sourced from
 * env vars (ADMIN_EMAIL / ADMIN_SECRET) — no admins collection.
 *
 * Session token lives in an httpOnly cookie (COOKIE_NAME), never in
 * localStorage/JS-readable storage, so it can't be read by injected/XSS'd
 * client script.
 *
 * NOTE: login is a constant-time shared-secret comparison (crypto.timingSafeEqual),
 * not a hashed password. There's exactly one admin and ADMIN_SECRET is meant to be
 * a long random token (not a human-memorized password) generated once with
 * `node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"` and
 * pasted into both the Vercel env var and the login form — same pattern already
 * used for ADMIN_TOKEN in api/webapp/admin-stats.js.
 */
const jwt = require("jsonwebtoken");
const crypto = require("crypto");
const cookie = require("cookie");

const COOKIE_NAME = "admin_token";
const JWT_SECRET = process.env.ADMIN_JWT_SECRET;
const SESSION_DAYS = 7;

function signAdminToken() {
  if (!JWT_SECRET) throw new Error("ADMIN_JWT_SECRET is not set.");
  return jwt.sign({ role: "admin" }, JWT_SECRET, { expiresIn: `${SESSION_DAYS}d` });
}

function verifyAdminToken(token) {
  if (!JWT_SECRET || !token) return null;
  try {
    const payload = jwt.verify(token, JWT_SECRET);
    return payload && payload.role === "admin" ? payload : null;
  } catch {
    return null;
  }
}

/** Constant-time comparison of the submitted secret against ADMIN_SECRET. */
function checkSecret(submitted, expected) {
  if (!submitted || !expected) return false;
  const a = Buffer.from(String(submitted));
  const b = Buffer.from(String(expected));
  // timingSafeEqual throws on length mismatch rather than returning false.
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

/** Build the Set-Cookie header value for logging in. */
function serializeSessionCookie(token) {
  return cookie.serialize(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_DAYS * 24 * 60 * 60,
  });
}

/** Build the Set-Cookie header value for logging out (clears the cookie). */
function serializeLogoutCookie() {
  return cookie.serialize(COOKIE_NAME, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}

/** Extract + verify the admin session from a raw `Cookie` request header. */
function getAdminFromCookieHeader(cookieHeader) {
  const parsed = cookie.parse(cookieHeader || "");
  return verifyAdminToken(parsed[COOKIE_NAME]);
}

module.exports = {
  COOKIE_NAME,
  signAdminToken,
  verifyAdminToken,
  checkSecret,
  serializeSessionCookie,
  serializeLogoutCookie,
  getAdminFromCookieHeader,
};
