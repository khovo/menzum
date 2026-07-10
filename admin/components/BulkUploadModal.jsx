import { useState } from "react";
import { presignedUploadAudio } from "../lib/uploadClient";

/**
 * components/BulkUploadModal.jsx
 * -------------------------------
 * Multi-file audio upload: pick several files at once, optionally tag them
 * all with one category, then upload sequentially via the presigned
 * direct-to-R2 flow (lib/uploadClient.js — the H9/Bug 2 fix), one file at a
 * time. Title defaults to the filename (extension stripped) per file;
 * per-row status shows queued/uploading/done/error.
 */
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

export default function BulkUploadModal({ categories, onDone }) {
  const [files, setFiles] = useState([]); // [{file, title, status, error}]
  const [category, setCategory] = useState("");
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
    updateRow(i, { status: "uploading", progress: 0 });
    try {
      await presignedUploadAudio({
        title: row.title,
        artist: "",
        category,
        file: row.file,
        onProgress: (fraction) => updateRow(i, { progress: fraction }),
      });
      updateRow(i, { status: "done" });
    } catch (err) {
      updateRow(i, { status: "error", error: err.message });
    }
  }

  async function startUpload() {
    setBusy(true);
    // Sequential, not parallel — keeps each request's R2 upload from
    // competing for the same serverless function's bandwidth/memory and
    // makes per-file progress legible.
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
        <label className="block text-xs text-gray-400 mb-1.5">Audio files</label>
        <input type="file" accept="audio/*" multiple onChange={pickFiles} disabled={busy} className="input" />
      </div>

      <div>
        <label className="block text-xs text-gray-400 mb-1.5">Category (applied to all)</label>
        <select value={category} onChange={(e) => setCategory(e.target.value)} disabled={busy} className="input">
          <option value="">— none —</option>
          {categories.map((c) => <option key={c.slug} value={c.slug}>{c.display_name}</option>)}
        </select>
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
                {row.status === "uploading" ? `Uploading… ${Math.round((row.progress || 0) * 100)}%` : STATUS_LABEL[row.status]}
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
