/**
 * lib/uploadClient.js
 * --------------------
 * Browser-only helper for the presigned direct-to-R2 upload flow (Bug 2 /
 * H9 fix — see pages/api/pdfs/presign.js and pages/api/audio/presign.js).
 * No server-only imports (no aws-sdk, no mongodb) — safe to import from any
 * client component.
 *
 * Uses XMLHttpRequest (not fetch) for the actual R2 PUT specifically because
 * fetch has no upload-progress event — XHR's `upload.onprogress` is the only
 * way to report real percent-complete for a large file going straight to
 * storage.
 *
 * Also fixes Bug 2(c): every step here reads the response defensively
 * (`safeJson`) instead of assuming JSON, so a non-JSON error body (e.g. a
 * platform-level error page) surfaces as a readable message instead of
 * crashing on `res.json()`'s own parse error. A network-level failure on the
 * R2 PUT itself (no HTTP response at all — `xhr.onerror`) is reported with a
 * specific, actionable message rather than the raw "Failed to fetch": in
 * practice this almost always means the R2 bucket's CORS policy doesn't
 * allow the admin panel's origin yet (see scripts/set-r2-cors.js).
 */

const CORS_HINT =
  "Could not reach storage — this usually means the R2 bucket's CORS policy " +
  "doesn't allow uploads from this site yet. Ask the administrator to run " +
  "admin/scripts/set-r2-cors.js (or add the CORS policy from the Cloudflare dashboard).";

async function safeJson(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * PUTs `file` directly to a presigned R2 URL. `onProgress(fraction)` is
 * called with a 0-1 value as bytes upload; omit if you don't need a bar.
 */
function presignedPut(uploadUrl, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total);
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1);
        resolve();
      } else {
        // A real HTTP response came back (so this isn't CORS) — R2 itself
        // rejected the upload, e.g. a signature/content-type mismatch.
        reject(new Error(`Upload to storage failed (HTTP ${xhr.status}). Please try again.`));
      }
    };
    // No HTTP response at all reached the browser — CORS block, DNS
    // failure, or the network dropped. This is the "Failed to fetch"
    // equivalent for XHR.
    xhr.onerror = () => reject(new Error(CORS_HINT));

    xhr.send(file);
  });
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
 * @param {(fraction: number) => void} [onProgress] - 0-1 upload progress
 * @returns {Promise<{id: string}>}
 */
export async function presignedUploadPdf({ title, description, file, onProgress }) {
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
    await presignedPut(presignData.uploadUrl, file, onProgress);
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
 * @param {(fraction: number) => void} [onProgress] - 0-1 upload progress,
 *        weighted across both files when a thumbnail is included
 * @returns {Promise<{id: string}>}
 */
export async function presignedUploadAudio({ title, artist, category, file, thumbFile, onProgress }) {
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

  const hasThumb = !!(thumbFile && presignData.thumbUploadUrl);
  // The audio file is almost always far bigger than its thumbnail — weight
  // the progress bar accordingly rather than splitting 50/50.
  const audioShare = hasThumb ? 0.85 : 1;

  try {
    await presignedPut(presignData.uploadUrl, file, onProgress && ((f) => onProgress(f * audioShare)));
    if (hasThumb) {
      await presignedPut(presignData.thumbUploadUrl, thumbFile, onProgress && ((f) => onProgress(audioShare + f * (1 - audioShare))));
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
