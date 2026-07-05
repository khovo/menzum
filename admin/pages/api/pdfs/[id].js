/**
 * PUT    /api/pdfs/:id  { title, description }
 * DELETE /api/pdfs/:id  — soft-delete only (hidden:true), never removes the doc.
 */
const { ObjectId } = require("mongodb");
const { connectToDatabase } = require("../../../lib/db");
const { withAdminAuth } = require("../../../lib/withAdminAuth");

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

async function handleDelete(req, res, db, id) {
  const result = await db.collection("pdfs").updateOne(
    { _id: new ObjectId(id) },
    { $set: { hidden: true, hidden_reason: "admin_panel", hidden_at: new Date() } }
  );
  if (result.matchedCount === 0) {
    return res.status(404).json({ ok: false, error: "PDF not found." });
  }
  return res.status(200).json({ ok: true });
}

module.exports = withAdminAuth(async function handler(req, res) {
  const { id } = req.query;
  if (!id || id.length !== 24) {
    return res.status(400).json({ ok: false, error: "Invalid id." });
  }

  try {
    const { db } = await connectToDatabase();
    if (req.method === "PUT") return handlePut(req, res, db, id);
    if (req.method === "DELETE") return handleDelete(req, res, db, id);
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
