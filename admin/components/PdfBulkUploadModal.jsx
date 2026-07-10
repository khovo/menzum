import { useState } from "react";
import { presignedUploadPdf } from "../lib/uploadClient";

/**
 * components/PdfBulkUploadModal.jsx
 * -----------------------------------
 * Bug 3: PDFs page had no bulk upload, unlike Audio. Mirrors
 * BulkUploadModal.jsx's UX exactly (pick several files, per-row
 * queued/uploading/done/error status, sequential not parallel) but each
 * file goes through the presigned direct-to-R2 flow (lib/uploadClient.js)
 * instead of a multipart POST — built on the same H9 fix as the single
 * upload form so large batches don't hit Vercel's function body limit
 * either.
 */
const ACCEPTED_EXTENSIONS = ".pdf,.doc,.docx,.txt,.epub";

const STATUS_LABEL = {
  queued: "Queued",
  uploading: "Uploading…",
  done: "Done",
  error: "Failed",
};

function stripExt(filename) {
  const idx = filename.lastIndexOf(".");
  return idx > 0 ? filename.slice(0, idx) : filename;
}

export default function PdfBulkUploadModal({ onDone }) {
  const [files, setFiles] = useState([]); // [{file, title, status, error}]
  const [busy, setBusy] = useState(false);

  function pickFiles(e) {
    const picked = Array.from(e.target.files || []);
    setFiles(
      picked.map((file) => ({
        file,
        title: stripExt(file.name),
        status: "queued",
        error: null,
      }))
    );
  }

  function updateRow(i, patch) {
    setFiles((prev) => prev.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  }

  async function uploadOne(row, i) {
    updateRow(i, { status: "uploading" });
    try {
      await presignedUploadPdf({ title: row.title, description: "", file: row.file });
      updateRow(i, { status: "done" });
    } catch (err) {
      updateRow(i, { status: "error", error: err.message });
    }
  }

  async function startUpload() {
    setBusy(true);
    // Sequential, not parallel — keeps per-file progress legible and
    // matches BulkUploadModal.jsx's audio bulk upload behavior.
    for (let i = 0; i < files.length; i++) {
      if (files[i].status === "done") continue;
      // eslint-disable-next-line no-await-in-loop
      await uploadOne(files[i], i);
    }
    setBusy(false);
  }

  const allDone = files.length > 0 && files.every((f) => f.status === "done");
  const anyError = files.some((f) => f.status === "error");

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs text-gray-400 mb-1.5">Document files (PDF, DOC, DOCX, TXT, or EPUB)</label>
        <input type="file" accept={ACCEPTED_EXTENSIONS} multiple onChange={pickFiles} disabled={busy} className="input" />
      </div>

      {files.length > 0 && (
        <div className="border border-border rounded-lg divide-y divide-border max-h-60 overflow-y-auto">
          {files.map((row, i) => (
            <div key={i} className="flex items-center gap-3 px-3 py-2 text-sm">
              <input
                value={row.title}
                onChange={(e) => updateRow(i, { title: e.target.value })}
                disabled={busy || row.status === "done"}
                className="input py-1 flex-1 min-w-0"
              />
              <span
                className={`text-[10px] px-2 py-0.5 rounded border shrink-0 ${
                  row.status === "done"
                    ? "bg-green-950/50 text-green-400 border-green-900"
                    : row.status === "error"
                    ? "bg-red-950/50 text-red-400 border-red-900"
                    : row.status === "uploading"
                    ? "bg-gold/10 text-gold border-gold/30"
                    : "bg-gray-800/50 text-gray-400 border-gray-700"
                }`}
                title={row.error || ""}
              >
                {STATUS_LABEL[row.status]}
              </span>
            </div>
          ))}
        </div>
      )}

      {anyError && (
        <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
          One or more files failed — check each row's status. Uploaded files were saved as drafts.
        </div>
      )}

      <div className="flex gap-3">
        <button
          onClick={startUpload}
          disabled={busy || files.length === 0 || allDone}
          className="btn-gold flex-1 disabled:opacity-50"
        >
          {busy ? "Uploading…" : allDone ? "All uploaded" : `Upload ${files.length || ""} file${files.length === 1 ? "" : "s"}`}
        </button>
        {allDone && (
          <button onClick={onDone} className="flex-1 rounded-lg border border-border py-2.5 text-sm text-gray-300 hover:bg-surface2">
            Done
          </button>
        )}
      </div>
    </div>
  );
}
