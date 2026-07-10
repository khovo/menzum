import { useEffect, useState, useCallback } from "react";
import Layout from "../../components/Layout";
import Modal from "../../components/Modal";
import Pagination from "../../components/Pagination";
import VisibilityToggle from "../../components/VisibilityToggle";
import PermanentDeleteModal from "../../components/PermanentDeleteModal";
import PdfBulkUploadModal from "../../components/PdfBulkUploadModal";
import ProgressBar from "../../components/ProgressBar";
import { requireAdmin } from "../../lib/requireAdmin";
import { presignedUploadPdf } from "../../lib/uploadClient";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
}

const ACCEPTED_EXTENSIONS = ".pdf,.doc,.docx,.txt,.epub";

function formatBytes(bytes) {
  if (!bytes) return "—";
  const mb = bytes / (1024 * 1024);
  return mb > 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
}

function UploadForm({ onDone }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    if (!file) return setError("Please choose a document file.");
    setBusy(true);
    setProgress(0);
    setError("");
    try {
      await presignedUploadPdf({ title, description, file, onProgress: setProgress });
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">{error}</div>}
      <div>
        <label className="block text-xs text-gray-400 mb-1.5">Title</label>
        <input required value={title} onChange={(e) => setTitle(e.target.value)} className="input" />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1.5">Description</label>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} className="input" />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1.5">Document file (PDF, DOC, DOCX, TXT, or EPUB — uploaded directly to storage, up to 5GB)</label>
        <input type="file" accept={ACCEPTED_EXTENSIONS} required onChange={(e) => setFile(e.target.files[0])} className="input" />
      </div>
      {busy && <ProgressBar fraction={progress} />}
      <button disabled={busy} className="btn-gold w-full">{busy ? `Uploading… ${Math.round(progress * 100)}%` : "Upload"}</button>
    </form>
  );
}

function EditForm({ pdf, onDone }) {
  const [title, setTitle] = useState(pdf.title);
  const [description, setDescription] = useState(pdf.description || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`/api/pdfs/${pdf.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Update failed.");
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">{error}</div>}
      <div>
        <label className="block text-xs text-gray-400 mb-1.5">Title</label>
        <input required value={title} onChange={(e) => setTitle(e.target.value)} className="input" />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1.5">Description</label>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} className="input" />
      </div>
      <button disabled={busy} className="btn-gold w-full">{busy ? "Saving…" : "Save changes"}</button>
    </form>
  );
}

export default function PdfsPage() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [showBulkUpload, setShowBulkUpload] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [purging, setPurging] = useState(null); // item pending "Delete Forever" — only shown for already-hidden items
  const [purgeBusy, setPurgeBusy] = useState(false);
  const [purgeError, setPurgeError] = useState("");
  const [toggling, setToggling] = useState(null); // `${id}:${field}` while a PATCH is in flight
  const [viewMode, setViewMode] = useState("visible"); // "visible" | "hidden" — which tab the table shows

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ page, search });
    if (viewMode === "hidden") params.set("hidden", "true");
    fetch(`/api/pdfs?${params}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) { setItems(d.items); setTotalPages(d.totalPages); }
      })
      .finally(() => setLoading(false));
  }, [page, search, viewMode]);

  useEffect(() => { load(); }, [load]);

  function switchView(mode) {
    setViewMode(mode);
    setPage(1);
  }

  async function confirmDelete() {
    const res = await fetch(`/api/pdfs/${deleting.id}`, { method: "DELETE" });
    const data = await res.json();
    setDeleting(null);
    if (res.ok && data.ok) {
      // Refetch from the server rather than only splicing local state — a
      // slower in-flight GET (e.g. from a just-changed page/search filter)
      // resolving after this DELETE would otherwise overwrite the optimistic
      // removal and make the row appear to "come back".
      load();
    }
  }

  async function confirmPurge() {
    setPurgeBusy(true);
    setPurgeError("");
    try {
      const res = await fetch(`/api/pdfs/${purging.id}?permanent=true`, { method: "DELETE" });
      const data = await res.json();
      if (res.ok && data.ok) {
        setPurging(null);
        load();
      } else {
        setPurgeError(data.error || "Could not permanently delete this PDF.");
      }
    } finally {
      setPurgeBusy(false);
    }
  }

  async function toggleField(item, field) {
    const key = `${item.id}:${field}`;
    setToggling(key);
    try {
      await fetch(`/api/pdfs/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field, value: !item[field] }),
      });
      load();
    } finally {
      setToggling(null);
    }
  }

  async function setStatus(item, status) {
    const key = `${item.id}:status`;
    setToggling(key);
    try {
      await fetch(`/api/pdfs/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field: "status", value: status }),
      });
      load();
    } finally {
      setToggling(null);
    }
  }

  return (
    <Layout title="PDFs">
      <div className="flex items-center gap-1.5 mb-4 border-b border-border">
        <button
          onClick={() => switchView("visible")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            viewMode === "visible" ? "border-gold text-gold" : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Visible
        </button>
        <button
          onClick={() => switchView("hidden")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            viewMode === "hidden" ? "border-gold text-gold" : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Hidden
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-5">
        <input
          placeholder="Search by title…"
          value={search}
          onChange={(e) => { setPage(1); setSearch(e.target.value); }}
          className="input max-w-xs"
        />
        {viewMode === "visible" && (
          <div className="ml-auto flex gap-3">
            <button onClick={() => setShowBulkUpload(true)} className="rounded-lg border border-gold/40 text-gold px-4 py-2 text-sm hover:bg-gold/10 transition-colors">⬆ Bulk Upload</button>
            <button onClick={() => setShowUpload(true)} className="btn-gold">+ Upload Document</button>
          </div>
        )}
      </div>

      {viewMode === "hidden" && (
        <div className="bg-surface border border-border rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-border">
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Size</th>
                <th className="px-4 py-3">Storage</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className="border-b border-border last:border-0 text-gray-500 opacity-60">
                  <td className="px-4 py-3 max-w-[280px] truncate">{p.title}</td>
                  <td className="px-4 py-3">{formatBytes(p.size_bytes)}</td>
                  <td className="px-4 py-3">
                    {p.has_r2 ? <Badge color="green">R2</Badge> : <Badge color="gray">none</Badge>}
                    {p.has_telegram && <Badge color="blue">Telegram</Badge>}
                  </td>
                  <td className="px-4 py-3 space-x-2 whitespace-nowrap">
                    <button
                      onClick={() => toggleField(p, "hidden")}
                      disabled={toggling === `${p.id}:hidden`}
                      className="text-gold hover:underline text-xs font-medium disabled:opacity-50"
                    >
                      {toggling === `${p.id}:hidden` ? "Restoring…" : "Restore"}
                    </button>
                    <button onClick={() => { setPurgeError(""); setPurging(p); }} className="text-red-600 hover:underline text-xs font-semibold">
                      Delete Forever
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && items.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-500">No hidden PDFs.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {viewMode === "visible" && (
      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Size</th>
              <th className="px-4 py-3">Downloads</th>
              <th className="px-4 py-3">Storage</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Visibility</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id} className="border-b border-border last:border-0 hover:bg-surface2/50">
                <td className="px-4 py-3 text-gray-200 max-w-[280px] truncate">{p.title}</td>
                <td className="px-4 py-3 text-gray-400">{formatBytes(p.size_bytes)}</td>
                <td className="px-4 py-3 text-gray-400">{p.download_count}</td>
                <td className="px-4 py-3">
                  {p.has_r2 ? <Badge color="green">R2</Badge> : <Badge color="gray">none</Badge>}
                  {p.has_telegram && <Badge color="blue">Telegram</Badge>}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => setStatus(p, p.status === "published" ? "draft" : "published")}
                    disabled={toggling === `${p.id}:status`}
                    className={`text-[10px] px-2 py-0.5 rounded border font-medium disabled:opacity-50 ${
                      p.status === "published"
                        ? "bg-green-950/50 text-green-400 border-green-900 hover:bg-green-900/50"
                        : "bg-yellow-950/50 text-yellow-400 border-yellow-900 hover:bg-yellow-900/50"
                    }`}
                    title={p.status === "published" ? "Click to unpublish (revert to draft)" : "Click to publish"}
                  >
                    {p.status === "published" ? "Published" : "Draft — Approve"}
                  </button>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    <VisibilityToggle
                      label="Visible"
                      hidden={p.hidden}
                      busy={toggling === `${p.id}:hidden`}
                      onToggle={() => toggleField(p, "hidden")}
                    />
                    <VisibilityToggle
                      label="Bot"
                      hidden={p.hidden_bot}
                      busy={toggling === `${p.id}:hidden_bot`}
                      onToggle={() => toggleField(p, "hidden_bot")}
                    />
                    <VisibilityToggle
                      label="App"
                      hidden={p.hidden_app}
                      busy={toggling === `${p.id}:hidden_app`}
                      onToggle={() => toggleField(p, "hidden_app")}
                    />
                  </div>
                </td>
                <td className="px-4 py-3 space-x-2 whitespace-nowrap">
                  <button onClick={() => setEditing(p)} className="text-gold hover:underline text-xs">Edit</button>
                  <button onClick={() => setDeleting(p)} className="text-red-400 hover:underline text-xs">Delete</button>
                  {/* Delete Forever only ever appears once an item is already hidden —
                      never allowed on a visible item, per the two-stage delete rule. */}
                  {p.hidden && (
                    <button onClick={() => { setPurgeError(""); setPurging(p); }} className="text-red-600 hover:underline text-xs font-semibold">
                      Delete Forever
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">No PDFs found.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      )}

      <Pagination page={page} totalPages={totalPages} onChange={setPage} />

      <Modal open={showUpload} title="Upload Document" onClose={() => setShowUpload(false)}>
        <UploadForm onDone={() => { setShowUpload(false); load(); }} />
      </Modal>

      <Modal open={showBulkUpload} title="Bulk Upload Documents" onClose={() => setShowBulkUpload(false)}>
        <PdfBulkUploadModal onDone={() => { setShowBulkUpload(false); load(); }} />
      </Modal>

      <Modal open={!!editing} title="Edit PDF" onClose={() => setEditing(null)}>
        {editing && <EditForm pdf={editing} onDone={() => { setEditing(null); load(); }} />}
      </Modal>

      <Modal open={!!deleting} title="Delete PDF" onClose={() => setDeleting(null)}>
        {deleting && (
          <div className="space-y-4">
            <p className="text-sm text-gray-300">
              Are you sure? This will permanently hide <strong>{deleting.title}</strong>. It stays in the
              database and can be restored later via the Visible toggle; it is never actually deleted.
            </p>
            <div className="flex gap-3">
              <button onClick={confirmDelete} className="flex-1 rounded-lg bg-red-600 hover:bg-red-500 text-white py-2.5 text-sm font-medium transition-colors">Delete</button>
              <button onClick={() => setDeleting(null)} className="flex-1 rounded-lg border border-border py-2.5 text-sm text-gray-300 hover:bg-surface2">Cancel</button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!purging} title="Delete Forever" onClose={() => setPurging(null)}>
        {purging && (
          <PermanentDeleteModal
            itemName={purging.title}
            busy={purgeBusy}
            error={purgeError}
            onConfirm={confirmPurge}
            onCancel={() => setPurging(null)}
          />
        )}
      </Modal>
    </Layout>
  );
}

function Badge({ children, color }) {
  const colors = {
    green: "bg-green-950/50 text-green-400 border-green-900",
    red: "bg-red-950/50 text-red-400 border-red-900",
    blue: "bg-blue-950/50 text-blue-400 border-blue-900",
    gray: "bg-gray-800/50 text-gray-400 border-gray-700",
  };
  return <span className={`inline-block text-[10px] px-2 py-0.5 rounded border mr-1 ${colors[color]}`}>{children}</span>;
}
