/**
 * lib/uploadClient.js
 * --------------------
 * Browser-only helper for the presigned direct-to-R2 upload flow (Bug 2 /
 * H9 fix — see pages/api/pdfs/presign.js and pages/api/audio/presign.js).
 * No server-only imports (no aws-sdk, no mongodb) — safe to import from any
 * client component.
 *
 * Also fixes Bug 2(c): every step here reads the response defensively
 * (`safeJson`) instead of assuming JSON, so a non-JSON error body (e.g. a
 * platform-level error page) surfaces as a readable message instead of
 * crashing on `res.json()`'s own parse error.
 */

async function safeJson(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

async function presignedPut(uploadUrl, file) {
  const putRes = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!putRes.ok) {
    throw new Error(`Upload to storage failed (HTTP ${putRes.status}). Please try again.`);
  }
}

/**
 * Best-effort cleanup of a draft doc whose file upload never completed.
 * DELETE only soft-hides on a visible doc (the two-stage delete rule), so a
 * fresh draft needs the soft-hide THEN the permanent delete to actually
 * disappear rather than sitting in the Hidden tab forever.
 */
async function abandonDraft(itemUrl) {
  try {
    await fetch(itemUrl, { method: "DELETE" });
    await fetch(`${itemUrl}?permanent=true`, { method: "DELETE" });
  } catch {
    // Nothing more we can do client-side — an orphaned empty draft is
    // harmless and cleanable later from the admin UI either way.
  }
}

/**
 * Uploads a single PDF/document via the presigned flow.
 * @returns {Promise<{id: string}>}
 */
export async function presignedUploadPdf({ title, description, file }) {
  const presignRes = await fetch("/api/pdfs/presign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, description, filename: file.name, contentType: file.type }),
  });
  const presignData = await safeJson(presignRes);
  if (!presignRes.ok || !presignData?.ok) {
    throw new Error(presignData?.error || `Could not start upload (HTTP ${presignRes.status}).`);
  }

  try {
    await presignedPut(presignData.uploadUrl, file);
  } catch (err) {
    await abandonDraft(`/api/pdfs/${presignData.id}`);
    throw err;
  }

  const confirmRes = await fetch(`/api/pdfs/${presignData.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field: "_upload_complete", value: { size_bytes: file.size } }),
  });
  const confirmData = await safeJson(confirmRes);
  if (!confirmRes.ok || !confirmData?.ok) {
    throw new Error(confirmData?.error || "Upload finished but could not be confirmed. Please retry.");
  }

  return { id: presignData.id };
}

/**
 * Uploads a single audio track (+ optional thumbnail) via the presigned flow.
 * @returns {Promise<{id: string}>}
 */
export async function presignedUploadAudio({ title, artist, category, file, thumbFile }) {
  const presignRes = await fetch("/api/audio/presign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title,
      artist,
      category,
      filename: file.name,
      contentType: file.type,
      thumbFilename: thumbFile ? thumbFile.name : undefined,
      thumbContentType: thumbFile ? thumbFile.type : undefined,
    }),
  });
  const presignData = await safeJson(presignRes);
  if (!presignRes.ok || !presignData?.ok) {
    throw new Error(presignData?.error || `Could not start upload (HTTP ${presignRes.status}).`);
  }

  try {
    await presignedPut(presignData.uploadUrl, file);
    if (thumbFile && presignData.thumbUploadUrl) {
      await presignedPut(presignData.thumbUploadUrl, thumbFile);
    }
  } catch (err) {
    await abandonDraft(`/api/audio/${presignData.id}`);
    throw err;
  }

  const confirmRes = await fetch(`/api/audio/${presignData.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field: "_upload_complete", value: { size_bytes: file.size } }),
  });
  const confirmData = await safeJson(confirmRes);
  if (!confirmRes.ok || !confirmData?.ok) {
    throw new Error(confirmData?.error || "Upload finished but could not be confirmed. Please retry.");
  }

  return { id: presignData.id };
}
