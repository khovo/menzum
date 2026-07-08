/**
 * lib/auth.js
 * -----------
 * Multi-admin JWT session. Two account sources:
 *   1. The original single super-admin, sourced from env vars
 *      (ADMIN_EMAIL / ADMIN_SECRET) — kept for backward compatibility, always
 *      resolves to role: ROLES.SUPER_ADMIN.
 *   2. Additional admins stored in the `admins` collection (see
 *      lib/adminUsers.js), each with an explicit role from lib/roles.js.
 *
 * Session token lives in an httpOnly cookie (COOKIE_NAME), never in
 * localStorage/JS-readable storage, so it can't be read by injected/XSS'd
 * client script. The token payload now carries { sub, email, role, name }
 * instead of the old flat { role: "admin" } — existing sessions signed
 * before this change will simply fail verification and be redirected to
 * /login (harmless: sessions are short-lived at 7 days).
 *
 * NOTE: the env-var super-admin login is still a constant-time shared-secret
 * comparison (crypto.timingSafeEqual), not a hashed password — see
 * checkSecret() below. DB-backed admins created via the panel use a salted
 * scrypt hash instead (hashSecret/verifySecretAgainstHash) since their
 * secret lives in Mongo rather than an env var.
 */
const jwt = require("jsonwebtoken");
const crypto = require("crypto");
const cookie = require("cookie");
const { ROLE_LABELS } = require("./roles");

const COOKIE_NAME = "admin_token";
const JWT_SECRET = process.env.ADMIN_JWT_SECRET;
const SESSION_DAYS = 7;

/** Sign a session token for { sub, email, role, name }. */
function signAdminToken({ sub, email, role, name }) {
  if (!JWT_SECRET) throw new Error("ADMIN_JWT_SECRET is not set.");
  return jwt.sign({ sub, email, role, name: name || null }, JWT_SECRET, { expiresIn: `${SESSION_DAYS}d` });
}

function verifyAdminToken(token) {
  if (!JWT_SECRET || !token) return null;
  try {
    const payload = jwt.verify(token, JWT_SECRET);
    return payload && payload.role && ROLE_LABELS[payload.role] ? payload : null;
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

/** Salted scrypt hash for a DB-backed admin's password (stored as "salt:hash"). */
function hashSecret(secret) {
  const salt = crypto.randomBytes(16).toString("hex");
  const hash = crypto.scryptSync(String(secret), salt, 64).toString("hex");
  return `${salt}:${hash}`;
}

/** Verify a submitted password against a hashSecret()-produced string. */
function verifySecretAgainstHash(secret, stored) {
  if (!secret || !stored || !stored.includes(":")) return false;
  const [salt, hash] = stored.split(":");
  const check = crypto.scryptSync(String(secret), salt, 64).toString("hex");
  const a = Buffer.from(hash, "hex");
  const b = Buffer.from(check, "hex");
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
  hashSecret,
  verifySecretAgainstHash,
  serializeSessionCookie,
  serializeLogoutCookie,
  getAdminFromCookieHeader,
};
