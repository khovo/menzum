/**
 * PUT    /api/pdfs/:id  { title, description }
 * PATCH  /api/pdfs/:id  { field: "hidden"|"hidden_bot"|"hidden_app", value: boolean }
 *        Instant visibility toggle — independent of the DELETE soft-delete below.
 *        hidden      — the master admin-panel visibility flag (all read paths
 *                       across bot + Mini App already filter on this one).
 *        hidden_bot  — Telegram-bot-only visibility (admin-panel field only;
 *                       not yet consumed by handlers/db.py — see note in
 *                       pages/pdfs/index.js UI).
 *        hidden_app  — Al-Madih Flutter app-only visibility (admin-panel
 *                       field only; not yet consumed by api/webapp/*.js).
 * DELETE /api/pdfs/:id  — soft-delete only (hidden:true), never removes the doc.
 */
const { ObjectId } = require("mongodb");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");
const { deleteFromR2 } = require("../../../lib/r2");

const TOGGLE_FIELDS = ["hidden", "hidden_bot", "hidden_app"];
const STATUS_VALUES = ["draft", "published"];

async function handlePut(req, res, db, id) {
  const { title, description } = req.body || {};
  const update = {};
  if (title !== undefined && String(title).trim()) update.title = String(title).trim();
  if (description !== undefined) update.description = String(description).trim() || null;

  if (Object.keys(update).length === 0) {
    return res.status(400).json({ ok: false, error: "Nothing to update." });
  }

  const result = await db.collection("pdfs").updateOne({ _id: new ObjectId(id) }, { $set: update });
  if (result.matchedCount === 0) {
    return res.status(404).json({ ok: false, error: "PDF not found." });
  }
  return res.status(200).json({ ok: true });
}

async function handlePatch(req, res, db, id) {
  const { field, value } = req.body || {};

  if (field === "status") {
    if (!STATUS_VALUES.includes(value)) {
      return res.status(400).json({ ok: false, error: `value must be one of: ${STATUS_VALUES.join(", ")}` });
    }
    const result = await db.collection("pdfs").updateOne({ _id: new ObjectId(id) }, { $set: { status: value } });
    if (result.matchedCount === 0) {
      return res.status(404).json({ ok: false, error: "PDF not found." });
    }
    return res.status(200).json({ ok: true, field, value });
  }

  if (!TOGGLE_FIELDS.includes(field)) {
    return res.status(400).json({ ok: false, error: `field must be one of: ${TOGGLE_FIELDS.join(", ")}, status` });
  }
  if (typeof value !== "boolean") {
    return res.status(400).json({ ok: false, error: "value must be a boolean." });
  }

  const update = { [field]: value };
  if (field === "hidden") {
    update.hidden_reason = value ? "admin_panel" : null;
    update.hidden_at = value ? new Date() : null;
  }

  const result = await db.collection("pdfs").updateOne({ _id: new ObjectId(id) }, { $set: update });
  if (result.matchedCount === 0) {
    return res.status(404).json({ ok: false, error: "PDF not found." });
  }
  return res.status(200).json({ ok: true, [field]: value });
}

async function handleDelete(req, res, db, id) {
  // ?permanent=true is the second-stage "Delete Forever" — everything else
  // about this handler (soft-hide) is unchanged.
  if (req.query.permanent !== "true") {
    const result = await db.collection("pdfs").updateOne(
      { _id: new ObjectId(id) },
      { $set: { hidden: true, hidden_reason: "admin_panel", hidden_at: new Date() } }
    );
    if (result.matchedCount === 0) {
      return res.status(404).json({ ok: false, error: "PDF not found." });
    }
    return res.status(200).json({ ok: true });
  }

  const doc = await db.collection("pdfs").findOne({ _id: new ObjectId(id) });
  if (!doc) {
    return res.status(404).json({ ok: false, error: "PDF not found." });
  }
  // Never allow permanent delete on a visible item — hide first, then
  // delete forever. This is the one hard rule for this action.
  if (!doc.hidden) {
    return res.status(400).json({ ok: false, error: "This PDF must be hidden first before it can be permanently deleted." });
  }

  const r2Errors = [];
  if (doc.r2_url) {
    try { await deleteFromR2("pdf", doc.r2_url); } catch (e) { r2Errors.push(`file: ${e.message}`); }
  }

  await db.collection("pdfs").deleteOne({ _id: new ObjectId(id) });
  return res.status(200).json({ ok: true, permanent: true, r2_errors: r2Errors.length ? r2Errors : undefined });
}

module.exports = withAdminAuth(async function handler(req, res) {
  const { id } = req.query;
  if (!id || id.length !== 24) {
    return res.status(400).json({ ok: false, error: "Invalid id." });
  }

  try {
    const { db } = await connectToDatabase();
    // Awaiting these matters — see pages/api/pdfs/index.js for why a bare
    // `return handleX(...)` lets errors escape this try/catch as an HTML 500.
    if (req.method === "PUT") return await handlePut(req, res, db, id);
    if (req.method === "PATCH") return await handlePatch(req, res, db, id);
    if (req.method === "DELETE") return await handleDelete(req, res, db, id);
    return res.status(405).json({ ok: false, error: "Method not allowed." });
  } catch (err) {
    console.error("api/pdfs/[id].js error:", err);
    return res.status(500).json({ ok: false, error: err.message || "Server error." });
  }
});

// Next.js production API runtime requires `.default` specifically — a bare
// CommonJS `module.exports = fn` alone is not picked up at request time (only
// at build-time page listing), which caused every route to 500 with
// "does not export a default function".
module.exports.default = module.exports;
