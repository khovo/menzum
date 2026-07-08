/**
 * PUT    /api/admins/:id  { role?, name?, password? } — edit a DB-backed admin
 * DELETE /api/admins/:id  — remove a DB-backed admin
 *
 * Requires PERMISSIONS.ADMINS (Super Admin only). The env-configured super
 * admin (id "env-admin") has no document to edit/remove — those requests
 * 400 rather than throwing on an invalid ObjectId.
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { updateAdmin, deleteAdmin, listAdmins } = require("../../../lib/adminUsers");
const { PERMISSIONS, ROLES } = require("../../../lib/roles");

async function handlePut(req, res, db, id) {
  const { role, name, password } = req.body || {};
  try {
    const ok = await updateAdmin(db, id, { role, name, secret: password });
    if (!ok) return res.status(400).json({ ok: false, error: "Nothing to update." });
    return res.status(200).json({ ok: true });
  } catch (err) {
    return res.status(400).json({ ok: false, error: err.message });
  }
}

async function handleDelete(req, res, db, id, requester) {
  // Never let a Super Admin delete the account they're currently signed in
  // as, and never remove the last remaining Super Admin — both would lock
  // every admin out of role management.
  if (requester.sub === id) {
    return res.status(400).json({ ok: false, error: "You can't remove your own account." });
  }
  const admins = await listAdmins(db);
  const target = admins.find((a) => a.id === id);
  if (!target) return res.status(404).json({ ok: false, error: "Admin not found." });

  if (target.role === ROLES.SUPER_ADMIN) {
    const envConfigured = !!(process.env.ADMIN_EMAIL || "").trim();
    const otherSuperAdmins = admins.filter((a) => a.role === ROLES.SUPER_ADMIN && a.id !== id);
    if (!envConfigured && otherSuperAdmins.length === 0) {
      return res.status(400).json({ ok: false, error: "Can't remove the last Super Admin." });
    }
  }

  const ok = await deleteAdmin(db, id);
  if (!ok) return res.status(404).json({ ok: false, error: "Admin not found." });
  return res.status(200).json({ ok: true });
}

module.exports = withAdminAuth(async function handler(req, res) {
  const { id } = req.query;
  if (!id || id === "env-admin") {
    return res.status(400).json({ ok: false, error: "The environment-configured super admin can't be edited here." });
  }

  try {
    const { db } = await connectToDatabase();
    if (req.method === "PUT") return await handlePut(req, res, db, id);
    if (req.method === "DELETE") return await handleDelete(req, res, db, id, req.admin);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/admins/[id].js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
}, { permission: PERMISSIONS.ADMINS });

module.exports.default = module.exports;
