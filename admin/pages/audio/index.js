import { useEffect, useState, useCallback } from "react";
import Layout from "../../components/Layout";
import Modal from "../../components/Modal";
import Pagination from "../../components/Pagination";
import VisibilityToggle from "../../components/VisibilityToggle";
import { requireAdmin } from "../../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
}

/**
 * Category options come from /api/categories at runtime (fixed 5 + any
 * custom ones created on the Categories page) rather than the static
 * CATEGORY_SLUGS constant, so a newly-created custom category shows up here
 * immediately without a redeploy.
 */
function useCategoryOptions() {
  const [categories, setCategories] = useState([]);
  useEffect(() => {
    fetch("/api/categories")
      .then((r) => r.json())
      .then((d) => d.ok && setCategories(d.categories));
  }, []);
  return categories;
}

function UploadForm({ categories, onDone }) {
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [category, setCategory] = useState("");
  const [audioFile, setAudioFile] = useState(null);
  const [thumbFile, setThumbFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    if (!audioFile) return setError("Please choose an audio file.");
    setBusy(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("title", title);
      fd.append("artist", artist);
      fd.append("category", category);
      fd.append("audio", audioFile);
      if (thumbFile) fd.append("thumbnail", thumbFile);

      const res = await fetch("/api/audio", { method: "POST", body: fd });
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
      <Field label="Title">
        <input required value={title} onChange={(e) => setTitle(e.target.value)} className="input" />
      </Field>
      <Field label="Artist">
        <input value={artist} onChange={(e) => setArtist(e.target.value)} className="input" />
      </Field>
      <Field label="Category">
        <select value={category} onChange={(e) => setCategory(e.target.value)} className="input">
          <option value="">— none —</option>
          {categories.map((c) => <option key={c.slug} value={c.slug}>{c.display_name}</option>)}
        </select>
      </Field>
      <Field label="Audio file">
        <input type="file" accept="audio/*" required onChange={(e) => setAudioFile(e.target.files[0])} className="input" />
      </Field>
      <Field label="Thumbnail (optional)">
        <input type="file" accept="image/*" onChange={(e) => setThumbFile(e.target.files[0])} className="input" />
      </Field>
      <button disabled={busy} className="btn-gold w-full">{busy ? "Uploading…" : "Upload"}</button>
    </form>
  );
}

function EditForm({ track, categories, onDone }) {
  const [title, setTitle] = useState(track.display_name);
  const [artist, setArtist] = useState(track.artist || "");
  const [category, setCategory] = useState(track.genre || "");
  const [thumbFile, setThumbFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("title", title);
      fd.append("artist", artist);
      fd.append("category", category);
      if (thumbFile) fd.append("thumbnail", thumbFile);

      const res = await fetch(`/api/audio/${track.id}`, { method: "PUT", body: fd });
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
      <Field label="Title">
        <input required value={title} onChange={(e) => setTitle(e.target.value)} className="input" />
      </Field>
      <Field label="Artist">
        <input value={artist} onChange={(e) => setArtist(e.target.value)} className="input" />
      </Field>
      <Field label="Category">
        <select value={category} onChange={(e) => setCategory(e.target.value)} className="input">
          <option value="">— none —</option>
          {categories.map((c) => <option key={c.slug} value={c.slug}>{c.display_name}</option>)}
        </select>
      </Field>
      <Field label="Replace thumbnail (optional)">
        <input type="file" accept="image/*" onChange={(e) => setThumbFile(e.target.files[0])} className="input" />
      </Field>
      <button disabled={busy} className="btn-gold w-full">{busy ? "Saving…" : "Save changes"}</button>
    </form>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1.5">{label}</label>
      {children}
    </div>
  );
}

export default function AudioPage() {
  const categories = useCategoryOptions();
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [toggling, setToggling] = useState(null); // `${id}:${field}` while a PATCH is in flight

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ page, search, category });
    fetch(`/api/audio?${params}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) {
          setItems(d.items);
          setTotalPages(d.totalPages);
        }
      })
      .finally(() => setLoading(false));
  }, [page, search, category]);

  useEffect(() => { load(); }, [load]);

  async function confirmDelete() {
    const res = await fetch(`/api/audio/${deleting.id}`, { method: "DELETE" });
    const data = await res.json();
    if (res.ok && data.ok) {
      // Remove locally right away — soft-delete keeps the doc (hidden:true)
      // but the admin list shouldn't keep showing it as if nothing happened.
      setItems((prev) => prev.filter((t) => t.id !== deleting.id));
    }
    setDeleting(null);
  }

  async function toggleField(item, field) {
    const key = `${item.id}:${field}`;
    setToggling(key);
    try {
      await fetch(`/api/audio/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field, value: !item[field] }),
      });
      load();
    } finally {
      setToggling(null);
    }
  }

  return (
    <Layout title="Audio">
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <input
          placeholder="Search by name…"
          value={search}
          onChange={(e) => { setPage(1); setSearch(e.target.value); }}
          className="input max-w-xs"
        />
        <select value={category} onChange={(e) => { setPage(1); setCategory(e.target.value); }} className="input max-w-[160px]">
          <option value="">All categories</option>
          {categories.map((c) => <option key={c.slug} value={c.slug}>{c.display_name}</option>)}
        </select>
        <button onClick={() => setShowUpload(true)} className="btn-gold ml-auto">+ Upload Audio</button>
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Artist</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">Plays</th>
              <th className="px-4 py-3">Storage</th>
              <th className="px-4 py-3">Visibility</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.id} className="border-b border-border last:border-0 hover:bg-surface2/50">
                <td className="px-4 py-3 text-gray-200 max-w-[240px] truncate">{t.display_name}</td>
                <td className="px-4 py-3 text-gray-400">{t.artist || "—"}</td>
                <td className="px-4 py-3 text-gray-400">{t.genre || "—"}</td>
                <td className="px-4 py-3 text-gray-400">{t.play_count}</td>
                <td className="px-4 py-3">
                  {t.has_r2 ? <Badge color="green">R2</Badge> : <Badge color="gray">none</Badge>}
                  {t.has_telegram && <Badge color="blue">Telegram</Badge>}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    <VisibilityToggle
                      label="Visible"
                      hidden={t.hidden}
                      busy={toggling === `${t.id}:hidden`}
                      onToggle={() => toggleField(t, "hidden")}
                    />
                    <VisibilityToggle
                      label="Bot"
                      hidden={t.hidden_bot}
                      busy={toggling === `${t.id}:hidden_bot`}
                      onToggle={() => toggleField(t, "hidden_bot")}
                    />
                    <VisibilityToggle
                      label="App"
                      hidden={t.hidden_app}
                      busy={toggling === `${t.id}:hidden_app`}
                      onToggle={() => toggleField(t, "hidden_app")}
                    />
                  </div>
                </td>
                <td className="px-4 py-3 space-x-2 whitespace-nowrap">
                  <button onClick={() => setEditing(t)} className="text-gold hover:underline text-xs">Edit</button>
                  <button onClick={() => setDeleting(t)} className="text-red-400 hover:underline text-xs">Delete</button>
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">No tracks found.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} onChange={setPage} />

      <Modal open={showUpload} title="Upload Audio" onClose={() => setShowUpload(false)}>
        <UploadForm categories={categories} onDone={() => { setShowUpload(false); load(); }} />
      </Modal>

      <Modal open={!!editing} title="Edit Track" onClose={() => setEditing(null)}>
        {editing && <EditForm track={editing} categories={categories} onDone={() => { setEditing(null); load(); }} />}
      </Modal>

      <Modal open={!!deleting} title="Delete Track" onClose={() => setDeleting(null)}>
        {deleting && (
          <div className="space-y-4">
            <p className="text-sm text-gray-300">
              Are you sure? This will permanently hide <strong>{deleting.display_name}</strong>. It stays in
              the database and can be restored later via the Visible toggle; it is never actually deleted.
            </p>
            <div className="flex gap-3">
              <button onClick={confirmDelete} className="flex-1 rounded-lg bg-red-600 hover:bg-red-500 text-white py-2.5 text-sm font-medium transition-colors">Delete</button>
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
