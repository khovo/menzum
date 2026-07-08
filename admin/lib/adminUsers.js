/**
 * lib/adminUsers.js
 * -----------------
 * CRUD over the `admins` collection (MenzumaDB) — additional admin accounts
 * beyond the single env-var-configured super admin (see lib/auth.js). Each
 * doc: { _id, email, name, role, secret_hash, created_at }.
 *
 * Server-only (imports lib/db.js indirectly via callers) — mirrors the
 * split between lib/categories.js (client-safe) and lib/categoryHelpers.js
 * (server-only) elsewhere in this app.
 */
const { ObjectId } = require("mongodb");
const { hashSecret, verifySecretAgainstHash } = require("./auth");
const { ROLES } = require("./roles");

async function listAdmins(db) {
  const docs = await db.collection("admins").find({}).sort({ created_at: 1 }).toArray();
  return docs.map((d) => ({
    id: d._id.toString(),
    email: d.email,
    name: d.name || null,
    role: d.role,
    created_at: d.created_at || null,
  }));
}

async function findAdminByEmail(db, email) {
  return db.collection("admins").findOne({ email: String(email || "").trim().toLowerCase() });
}

async function createAdmin(db, { email, secret, role, name }) {
  const normEmail = String(email || "").trim().toLowerCase();
  if (!normEmail) throw new Error("Email is required.");
  if (!secret || String(secret).length < 8) throw new Error("Password must be at least 8 characters.");
  if (!Object.values(ROLES).includes(role)) throw new Error("A valid role is required.");

  const existing = await findAdminByEmail(db, normEmail);
  if (existing) throw new Error(`An admin with email "${normEmail}" already exists.`);

  const doc = {
    email: normEmail,
    name: name ? String(name).trim() : null,
    role,
    secret_hash: hashSecret(secret),
    created_at: new Date(),
  };
  const result = await db.collection("admins").insertOne(doc);
  return result.insertedId.toString();
}

async function updateAdmin(db, id, { role, name, secret }) {
  const update = {};
  if (role !== undefined) {
    if (!Object.values(ROLES).includes(role)) throw new Error("A valid role is required.");
    update.role = role;
  }
  if (name !== undefined) update.name = name ? String(name).trim() : null;
  if (secret !== undefined && secret !== "") {
    if (String(secret).length < 8) throw new Error("Password must be at least 8 characters.");
    update.secret_hash = hashSecret(secret);
  }
  if (Object.keys(update).length === 0) return false;

  const result = await db.collection("admins").updateOne({ _id: new ObjectId(id) }, { $set: update });
  return result.matchedCount > 0;
}

async function deleteAdmin(db, id) {
  const result = await db.collection("admins").deleteOne({ _id: new ObjectId(id) });
  return result.deletedCount > 0;
}

/** Verify email+password against a DB-backed admin; returns a JWT-payload-shaped object or null. */
async function verifyAdminCredentials(db, email, secret) {
  const doc = await findAdminByEmail(db, email);
  if (!doc) return null;
  if (!verifySecretAgainstHash(secret, doc.secret_hash)) return null;
  return { sub: doc._id.toString(), email: doc.email, role: doc.role, name: doc.name || null };
}

module.exports = {
  listAdmins,
  findAdminByEmail,
  createAdmin,
  updateAdmin,
  deleteAdmin,
  verifyAdminCredentials,
};
