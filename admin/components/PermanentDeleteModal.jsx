import { useState } from "react";

/**
 * components/PermanentDeleteModal.jsx
 * -------------------------------------
 * The "strong confirmation" for permanent delete: type DELETE to enable the
 * button. Only ever shown for items that are already hidden — callers must
 * enforce that themselves (this component doesn't know about `hidden`), and
 * the API rejects the request server-side regardless as the real guarantee.
 */
export default function PermanentDeleteModal({ itemName, onConfirm, onCancel, busy, error }) {
  const [confirmText, setConfirmText] = useState("");
  const canConfirm = confirmText.trim().toUpperCase() === "DELETE";

  return (
    <div className="space-y-4">
      <p className="text-sm text-red-300">
        This permanently deletes <strong>{itemName}</strong> — the database record AND its
        file(s) in storage. <strong>This cannot be undone.</strong> There is no restore after this.
      </p>
      {error && <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">{error}</div>}
      <div>
        <label className="block text-xs text-gray-400 mb-1.5">Type DELETE to confirm</label>
        <input
          autoFocus
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          className="input"
          placeholder="DELETE"
        />
      </div>
      <div className="flex gap-3">
        <button
          onClick={onConfirm}
          disabled={!canConfirm || busy}
          className="flex-1 rounded-lg bg-red-700 hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed text-white py-2.5 text-sm font-semibold transition-colors"
        >
          {busy ? "Deleting…" : "Delete Forever"}
        </button>
        <button onClick={onCancel} className="flex-1 rounded-lg border border-border py-2.5 text-sm text-gray-300 hover:bg-surface2">
          Cancel
        </button>
      </div>
    </div>
  );
}
