/**
 * lib/withAdminAuth.js
 * --------------------
 * API route guard. Wrap every protected handler in pages/api/**:
 *   module.exports = withAdminAuth(async function handler(req, res) { ... });
 *
 * Reads the httpOnly session cookie, verifies the JWT, and 401s otherwise.
 * Attaches the verified session payload as req.admin ({sub, email, role, name}).
 *
 * Pass { permission } (a lib/roles.js PERMISSIONS value) to also require the
 * caller's role to have that permission, 403ing otherwise:
 *   module.exports = withAdminAuth(handler, { permission: PERMISSIONS.ADMINS });
 *
 * (auth/login.js and auth/logout.js are the only routes that do NOT use this.)
 */
const { getAdminFromCookieHeader } = require("./auth");
const { hasPermission } = require("./roles");

function withAdminAuth(handler, options = {}) {
  const { permission } = options;
  return async function (req, res) {
    const admin = getAdminFromCookieHeader(req.headers.cookie);
    if (!admin) {
      return res.status(401).json({ ok: false, error: "Not authenticated." });
    }
    if (permission && !hasPermission(admin.role, permission)) {
      return res.status(403).json({ ok: false, error: "You don't have permission to do that." });
    }
    req.admin = admin;
    return handler(req, res);
  };
}

module.exports = { withAdminAuth };
