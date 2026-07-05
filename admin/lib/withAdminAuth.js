/**
 * lib/withAdminAuth.js
 * --------------------
 * API route guard. Wrap every protected handler in pages/api/**:
 *   module.exports = withAdminAuth(async function handler(req, res) { ... });
 *
 * Reads the httpOnly session cookie, verifies the JWT, and 401s otherwise.
 * (auth/login.js and auth/logout.js are the only routes that do NOT use this.)
 */
const { getAdminFromCookieHeader } = require("./auth");

function withAdminAuth(handler) {
  return async function (req, res) {
    const admin = getAdminFromCookieHeader(req.headers.cookie);
    if (!admin) {
      return res.status(401).json({ ok: false, error: "Not authenticated." });
    }
    return handler(req, res);
  };
}

module.exports = { withAdminAuth };
