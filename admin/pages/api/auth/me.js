/**
 * GET /api/auth/me
 * Returns the current session's admin identity (email/role/name) so
 * client components — namely Sidebar.jsx for role-gated nav — can render
 * accordingly without the httpOnly session cookie ever being readable by JS.
 */
const { withAdminAuth } = require("../../../lib/withAdminAuth");

module.exports = withAdminAuth(async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  }
  return res.status(200).json({
    ok: true,
    admin: { email: req.admin.email, role: req.admin.role, name: req.admin.name || null },
  });
});

module.exports.default = module.exports;
