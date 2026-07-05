/**
 * POST /api/auth/login  { email, password }
 * No auth required (this IS the auth entry point). Validates against the
 * single admin account (env vars) and sets the httpOnly session cookie.
 */
const { checkPassword, signAdminToken, serializeSessionCookie } = require("../../../lib/auth");

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }

  const { email, password } = req.body || {};
  const adminEmail = (process.env.ADMIN_EMAIL || "").trim().toLowerCase();
  const adminHash = process.env.ADMIN_PASSWORD_HASH;

  if (!adminEmail || !adminHash) {
    return res.status(503).json({ ok: false, error: "Admin account not configured on the server." });
  }
  if (!email || !password) {
    return res.status(400).json({ ok: false, error: "Email and password are required." });
  }

  const emailMatches = String(email).trim().toLowerCase() === adminEmail;
  const passwordMatches = await checkPassword(password, adminHash);

  // Always run both checks (even when email is already wrong) so failed-login
  // timing doesn't leak which part (email vs password) was incorrect.
  if (!emailMatches || !passwordMatches) {
    return res.status(401).json({ ok: false, error: "Invalid email or password." });
  }

  const token = signAdminToken();
  res.setHeader("Set-Cookie", serializeSessionCookie(token));
  return res.status(200).json({ ok: true });
};
