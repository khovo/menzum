/**
 * GET  /api/admins   — list all admins (the env-configured super admin +
 *                      everyone in the `admins` collection)
 * POST /api/admins   { email, password, role, name? } — create a new
 *                      DB-backed admin
 *
 * Requires PERMISSIONS.ADMINS (Super Admin only, per lib/roles.js).
 */
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { listAdmins, createAdmin } = require("../../../lib/adminUsers");
const { PERMISSIONS, ROLE_LABELS, ROLES } = require("../../../lib/roles");

async function handleGet(req, res, db) {
  const dbAdmins = await listAdmins(db);
  const envEmail = (process.env.ADMIN_EMAIL || "").trim().toLowerCase();

  const admins = envEmail
    ? [{ id: "env-admin", email: envEmail, name: "Super Admin", role: ROLES.SUPER_ADMIN, created_at: null, envManaged: true }, ...dbAdmins]
    : dbAdmins;

  return res.status(200).json({ ok: true, admins, roleLabels: ROLE_LABELS });
}

async function handlePost(req, res, db) {
  const { email, password, role, name } = req.body || {};
  try {
    const id = await createAdmin(db, { email, secret: password, role, name });
    return res.status(201).json({ ok: true, id });
  } catch (err) {
    return res.status(400).json({ ok: false, error: err.message });
  }
}

module.exports = withAdminAuth(async function handler(req, res) {
  try {
    const { db } = await connectToDatabase();
    if (req.method === "GET") return await handleGet(req, res, db);
    if (req.method === "POST") return await handlePost(req, res, db);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/admins/index.js error:", err);
    return res.status(500).json({ ok: false, error: "Server error." });
  }
}, { permission: PERMISSIONS.ADMINS });

module.exports.default = module.exports;
