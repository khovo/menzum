/**
 * api/webapp/auth-refresh.js
 * --------------------------
 * POST /api/webapp/auth-refresh
 * Auth: Bearer <jwt> (a still-valid token) OR tma <initData>
 *
 * Returns a fresh 90-day JWT for the authenticated user. The app should call
 * this periodically (e.g. on launch when the token is older than ~60 days) so
 * the session never lapses.
 *
 * RESPONSE 200: { "ok": true, "token": "<new jwt>" }
 */
const { withAuth } = require("./_auth");
const { sign, isConfigured } = require("./_jwt");

module.exports = withAuth(async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }
  if (!isConfigured()) {
    return res.status(503).json({ ok: false, error: "JWT_SECRET not configured on server." });
  }
  const token = sign({ uid: parseInt(req.telegramUser.id, 10) });
  return res.status(200).json({ ok: true, token });
});
