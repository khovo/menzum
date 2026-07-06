/**
 * POST /api/auth/login  { email, password }
 * No auth required (this IS the auth entry point). Validates against the
 * single admin account (env vars) and sets the httpOnly session cookie.
 *
 * "password" here is really a shared secret (ADMIN_SECRET) checked with a
 * constant-time comparison, not a hashed/salted password — see lib/auth.js.
 */
const { checkSecret, signAdminToken, serializeSessionCookie } = require("../../../lib/auth");

module.exports = async function handler(req, res) {
  try {
    if (req.method !== "POST") {
      return res.status(405).json({ ok: false, error: "Method not allowed." });
    }

    const { email, password } = req.body || {};
    const adminEmail = (process.env.ADMIN_EMAIL || "").trim().toLowerCase();
    const adminSecret = (process.env.ADMIN_SECRET || "").trim();

    if (!adminEmail || !adminSecret) {
      return res.status(503).json({ ok: false, error: "Admin account not configured on the server." });
    }
    if (!email || !password) {
      return res.status(400).json({ ok: false, error: "Email and password are required." });
    }

    const emailMatches = String(email).trim().toLowerCase() === adminEmail;
    const secretMatches = checkSecret(password, adminSecret);

    // Always run both checks (even when email is already wrong) so failed-login
    // timing doesn't leak which part (email vs password) was incorrect.
    if (!emailMatches || !secretMatches) {
      return res.status(401).json({ ok: false, error: "Invalid email or password." });
    }

    const token = signAdminToken();
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
