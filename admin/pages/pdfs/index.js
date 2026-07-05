import { useEffect, useState, useCallback } from "react";
import Layout from "../../components/Layout";
import Modal from "../../components/Modal";
import Pagination from "../../components/Pagination";
import { requireAdmin } from "../../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
}

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
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    if (!file) return setError("Please choose a PDF file.");
    setBusy(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("title", title);
      fd.append("description", description);
      fd.append("pdf", file);
      const res = await fetch("/api/pdfs", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Upload failed.");
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
        <label className="block text-xs text-gray-400 mb-1.5">PDF file (no size limit)</label>
        <input type="file" accept="application/pdf" required onChange={(e) => setFile(e.target.files[0])} className="input" />
      </div>
      <button disabled={busy} className="btn-gold w-full">{busy ? "Uploading…" : "Upload"}</button>
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
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ page, search });
    fetch(`/api/pdfs?${params}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) { setItems(d.items); setTotalPages(d.totalPages); }
      })
      .finally(() => setLoading(false));
  }, [page, search]);

  useEffect(() => { load(); }, [load]);

  async function confirmDelete() {
    await fetch(`/api/pdfs/${deleting.id}`, { method: "DELETE" });
    setDeleting(null);
    load();
  }

  return (
    <Layout title="PDFs">
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <input
          placeholder="Search by title…"
          value={search}
          onChange={(e) => { setPage(1); setSearch(e.target.value); }}
          className="input max-w-xs"
        />
        <button onClick={() => setShowUpload(true)} className="btn-gold ml-auto">+ Upload PDF</button>
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Size</th>
              <th className="px-4 py-3">Downloads</th>
              <th className="px-4 py-3">Storage</th>
              <th className="px-4 py-3">Status</th>
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
                <td className="px-4 py-3">{p.hidden ? <Badge color="red">Hidden</Badge> : <Badge color="green">Visible</Badge>}</td>
                <td className="px-4 py-3 space-x-2 whitespace-nowrap">
                  <button onClick={() => setEditing(p)} className="text-gold hover:underline text-xs">Edit</button>
                  <button onClick={() => setDeleting(p)} className="text-red-400 hover:underline text-xs">
                    {p.hidden ? "Hidden" : "Hide"}
                  </button>
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No PDFs found.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} onChange={setPage} />

      <Modal open={showUpload} title="Upload PDF" onClose={() => setShowUpload(false)}>
        <UploadForm onDone={() => { setShowUpload(false); load(); }} />
      </Modal>

      <Modal open={!!editing} title="Edit PDF" onClose={() => setEditing(null)}>
        {editing && <EditForm pdf={editing} onDone={() => { setEditing(null); load(); }} />}
      </Modal>

      <Modal open={!!deleting} title="Hide PDF" onClose={() => setDeleting(null)}>
        {deleting && (
          <div className="space-y-4">
            <p className="text-sm text-gray-300">
              Soft-delete <strong>{deleting.title}</strong>? It stays in the database and can be restored
              later; it is never actually deleted.
            </p>
            <div className="flex gap-3">
              <button onClick={confirmDelete} className="btn-gold flex-1">Confirm Hide</button>
              <button onClick={() => setDeleting(null)} className="flex-1 rounded-lg border border-border py-2.5 text-sm text-gray-300 hover:bg-surface2">Cancel</button>
            </div>
          </div>
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
