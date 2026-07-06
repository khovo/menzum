/**
 * POST /api/auth/login  { email, password }
 * No auth required (this IS the auth entry point). Validates against the
 * single admin account (env vars) and sets the httpOnly session cookie.
 */
const { checkPassword, signAdminToken, serializeSessionCookie } = require("../../../lib/auth");
const bcrypt = require("bcryptjs"); // TEMPORARY DEBUG — remove once login works

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
    const adminHash = (process.env.ADMIN_PASSWORD_HASH || "").trim();

    if (!adminEmail || !adminHash) {
      return res.status(503).json({ ok: false, error: "Admin account not configured on the server." });
    }
    if (!email || !password) {
      return res.status(400).json({ ok: false, error: "Email and password are required." });
    }

    const emailMatches = String(email).trim().toLowerCase() === adminEmail;
    const passwordMatches = await checkPassword(password, adminHash);

    // ── TEMPORARY DEBUG — remove once login works ───────────────────────────
    // NOTE: deliberately NOT logging the full hash value — bcrypt hashes are
    // credential-adjacent and Vercel logs can persist/be exported. Logging
    // length + prefix is enough to catch truncation/whitespace/wrong-value
    // issues without putting the real hash in the log stream.
    console.log('ENV EMAIL:', process.env.ADMIN_EMAIL);
    console.log('ENV HASH exists:', !!process.env.ADMIN_PASSWORD_HASH);
    console.log('ENV HASH raw length:', (process.env.ADMIN_PASSWORD_HASH || '').length);
    console.log('ENV HASH trimmed length:', adminHash.length);
    console.log('ENV HASH prefix:', adminHash.slice(0, 7));
    console.log('Input email:', email);
    console.log('bcrypt result:', passwordMatches);

    // ── TEMPORARY DEBUG — remove once login works ───────────────────────────
    // Diagnostic only — does NOT feed the actual auth decision below (which
    // still uses checkPassword()/passwordMatches). bcryptjs already treats
    // $2a$/$2b$/$2y$ hashes identically, so this is likely a no-op, but it's
    // a cheap way to rule out a version-tag mismatch as the cause.
    const normalizedHash = adminHash.replace(/^\$2a\$/, '$2b$');
    const passwordMatch = await bcrypt.compare(password, normalizedHash);
    console.log('DEBUG normalized-hash bcrypt.compare result:', passwordMatch);

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

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
