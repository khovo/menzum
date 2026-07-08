/**
 * POST /api/auth/login  { email, password }
 * No auth required (this IS the auth entry point). Sets the httpOnly session
 * cookie on success. Two account sources are checked:
 *
 *   1. The original single super-admin, sourced from env vars (ADMIN_EMAIL /
 *      ADMIN_SECRET), checked with a constant-time comparison — not a
 *      hashed/salted password, see lib/auth.js. Always resolves to
 *      ROLES.SUPER_ADMIN. Kept for backward compatibility.
 *   2. Additional admins created via the panel, stored in the `admins`
 *      collection with a role from lib/roles.js and a scrypt-hashed secret
 *      (see lib/adminUsers.js).
 */
const { checkSecret, signAdminToken, serializeSessionCookie } = require("../../../lib/auth");
const { verifyAdminCredentials } = require("../../../lib/adminUsers");
const { connectToDatabase } = require("../../../lib/db");
const { ROLES } = require("../../../lib/roles");

module.exports = async function handler(req, res) {
  try {
    if (req.method !== "POST") {
      return res.status(405).json({ ok: false, error: "Method not allowed." });
    }

    const { email, password } = req.body || {};
    if (!email || !password) {
      return res.status(400).json({ ok: false, error: "Email and password are required." });
    }

    const normEmail = String(email).trim().toLowerCase();
    const envEmail = (process.env.ADMIN_EMAIL || "").trim().toLowerCase();
    const envSecret = (process.env.ADMIN_SECRET || "").trim();

    if (envEmail && envSecret && normEmail === envEmail && checkSecret(password, envSecret)) {
      const token = signAdminToken({ sub: "env-admin", email: envEmail, role: ROLES.SUPER_ADMIN, name: "Super Admin" });
      res.setHeader("Set-Cookie", serializeSessionCookie(token));
      return res.status(200).json({ ok: true });
    }

    const { db } = await connectToDatabase();
    const admin = await verifyAdminCredentials(db, normEmail, password);
    if (!admin) {
      return res.status(401).json({ ok: false, error: "Invalid email or password." });
    }

    const token = signAdminToken(admin);
    res.setHeader("Set-Cookie", serializeSessionCookie(token));
    return res.status(200).json({ ok: true });
  } catch (err) {
    console.error("api/auth/login.js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
};

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
