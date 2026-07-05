/**
 * POST /api/auth/login  { email, password }
 * No auth required (this IS the auth entry point). Validates against the
 * single admin account (env vars) and sets the httpOnly session cookie.
 */
const { checkPassword, signAdminToken, serializeSessionCookie } = require("../../../lib/auth");

module.exports = async function handler(req, res) {
  // ── TEMPORARY DEBUG — remove once login works ─────────────────────────────
  console.log("[login debug] env present:", {
    ADMIN_EMAIL: !!process.env.ADMIN_EMAIL,
    ADMIN_PASSWORD_HASH: !!process.env.ADMIN_PASSWORD_HASH,
    ADMIN_JWT_SECRET: !!process.env.ADMIN_JWT_SECRET,
  });

  try {
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
  } catch (err) {
    // ── TEMPORARY DEBUG — remove once login works ───────────────────────────
    console.error("[login debug] CRASH:", err);
    return res.status(500).json({
      ok: false,
      error: "DEBUG: " + err.message,
      stack: err.stack,
    });
  }
};
