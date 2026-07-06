import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import { requireAdmin } from "../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
}

function CreateCategoryForm({ onDone }) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, display_name: displayName }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Could not create category.");
      setSlug("");
      setDisplayName("");
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="bg-surface border border-border rounded-xl p-4 mb-5 flex flex-wrap items-end gap-3">
      {error && <div className="w-full text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">{error}</div>}
      <div className="flex-1 min-w-[160px]">
        <label className="block text-xs text-gray-400 mb-1.5">Slug</label>
        <input
          required
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder="ramadan-specials"
          className="input"
        />
      </div>
      <div className="flex-1 min-w-[160px]">
        <label className="block text-xs text-gray-400 mb-1.5">Display Name</label>
        <input
          required
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Ramadan Specials"
          className="input"
        />
      </div>
      <button disabled={busy} className="btn-gold">{busy ? "Creating…" : "+ Add Category"}</button>
    </form>
  );
}

export default function CategoriesPage() {
  const [categories, setCategories] = useState([]);
  const [editingSlug, setEditingSlug] = useState(null);
  const [editValue, setEditValue] = useState("");
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    fetch("/api/categories")
      .then((r) => r.json())
      .then((d) => d.ok && setCategories(d.categories))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  function startEdit(cat) {
    setEditingSlug(cat.slug);
    setEditValue(cat.display_name);
  }

  async function save(slug) {
    await fetch("/api/categories", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, display_name: editValue }),
    });
    setEditingSlug(null);
    load();
  }

  return (
    <Layout title="Categories">
      <p className="text-sm text-gray-500 mb-5 max-w-2xl">
        The 5 built-in categories (neshida/eshq/abret/katbare/raya) are fixed — the same genre tags the
        bot and Mini App use — and can't be removed, only renamed. Custom categories you create below can
        also be assigned to tracks from the Audio page's category dropdown.
      </p>

      <CreateCategoryForm onDone={load} />

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-3">Slug</th>
              <th className="px-4 py-3">Display Name</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Tracks</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => (
              <tr key={c.slug} className="border-b border-border last:border-0 hover:bg-surface2/50">
                <td className="px-4 py-3 text-gray-500 font-mono text-xs">{c.slug}</td>
                <td className="px-4 py-3 text-gray-200">
                  {editingSlug === c.slug ? (
                    <input
                      autoFocus
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      className="input py-1"
                    />
                  ) : (
                    c.display_name
                  )}
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-block text-[10px] px-2 py-0.5 rounded border ${
                    c.custom
                      ? "bg-blue-950/50 text-blue-400 border-blue-900"
                      : "bg-gray-800/50 text-gray-400 border-gray-700"
                  }`}>
                    {c.custom ? "Custom" : "Fixed"}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400">{c.track_count}</td>
                <td className="px-4 py-3">
                  {editingSlug === c.slug ? (
                    <div className="space-x-2">
                      <button onClick={() => save(c.slug)} className="text-gold hover:underline text-xs">Save</button>
                      <button onClick={() => setEditingSlug(null)} className="text-gray-500 hover:underline text-xs">Cancel</button>
                    </div>
                  ) : (
                    <button onClick={() => startEdit(c)} className="text-gold hover:underline text-xs">Rename</button>
                  )}
                </td>
              </tr>
            ))}
            {!loading && categories.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-500">No categories.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Layout>
  );
}
