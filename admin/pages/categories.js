import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import Modal from "../components/Modal";
import VisibilityToggle from "../components/VisibilityToggle";
import { requireAdmin } from "../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
}

function CreateCategoryForm({ onDone }) {
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
        body: JSON.stringify({ display_name: displayName }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Could not create category.");
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
      <div className="flex-1 min-w-[200px]">
        <label className="block text-xs text-gray-400 mb-1.5">Category Name</label>
        <input
          required
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="ራያ, ست خاصة, Ramadan Specials…"
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
  const [deleting, setDeleting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [togglingHidden, setTogglingHidden] = useState(null); // slug currently being hidden/shown

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

  async function confirmDelete() {
    const res = await fetch(`/api/categories?slug=${encodeURIComponent(deleting.slug)}`, { method: "DELETE" });
    const data = await res.json();
    if (res.ok && data.ok) {
      setCategories((prev) => prev.filter((c) => c.slug !== deleting.slug));
    }
    setDeleting(null);
  }

  // Works for BOTH fixed and custom categories — hiding is the only way to
  // remove a fixed category from the public app-facing list, since its slug
  // can never actually be deleted.
  async function toggleHidden(cat) {
    setTogglingHidden(cat.slug);
    try {
      await fetch("/api/categories", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: cat.slug, hidden: !cat.hidden }),
      });
      load();
    } finally {
      setTogglingHidden(null);
    }
  }

  // Reordering is scoped to custom categories only — swap sort_order with
  // the neighboring custom row so fixed categories always stay on top.
  async function moveCategory(cat, direction) {
    const customList = categories.filter((c) => c.custom);
    const idx = customList.findIndex((c) => c.slug === cat.slug);
    const swapIdx = idx + direction;
    if (swapIdx < 0 || swapIdx >= customList.length) return;
    const other = customList[swapIdx];

    await Promise.all([
      fetch("/api/categories", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: cat.slug, sort_order: other.sort_order }),
      }),
      fetch("/api/categories", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: other.slug, sort_order: cat.sort_order }),
      }),
    ]);
    load();
  }

  return (
    <Layout title="Categories">
      <p className="text-sm text-gray-500 mb-5 max-w-2xl">
        The 5 built-in categories (neshida/eshq/abret/katbare/raya) are fixed — the same genre tags the
        bot and Mini App use — and can't be deleted, only renamed or hidden from the app's category list.
        Custom categories you create below can be renamed, hidden, or deleted outright, and are assignable
        from the Audio page's category dropdown. Hiding or deleting a category never affects tracks already
        tagged with it — they stay tagged and remain reachable under "All."
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
              <th className="px-4 py-3">Visibility</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => {
              const customList = categories.filter((x) => x.custom);
              const customIdx = customList.findIndex((x) => x.slug === c.slug);
              return (
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
                  <VisibilityToggle
                    label="App list"
                    hidden={c.hidden}
                    busy={togglingHidden === c.slug}
                    onToggle={() => toggleHidden(c)}
                  />
                </td>
                <td className="px-4 py-3 space-x-2 whitespace-nowrap">
                  {editingSlug === c.slug ? (
                    <>
                      <button onClick={() => save(c.slug)} className="text-gold hover:underline text-xs">Save</button>
                      <button onClick={() => setEditingSlug(null)} className="text-gray-500 hover:underline text-xs">Cancel</button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => startEdit(c)} className="text-gold hover:underline text-xs">Rename</button>
                      {c.custom && (
                        <>
                          <button onClick={() => setDeleting(c)} className="text-red-400 hover:underline text-xs">Delete</button>
                          <button
                            onClick={() => moveCategory(c, -1)}
                            disabled={customIdx <= 0}
                            className="text-gray-400 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed text-xs"
                            title="Move up"
                          >▲</button>
                          <button
                            onClick={() => moveCategory(c, 1)}
                            disabled={customIdx >= customList.length - 1}
                            className="text-gray-400 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed text-xs"
                            title="Move down"
                          >▼</button>
                        </>
                      )}
                    </>
                  )}
                </td>
              </tr>
              );
            })}
            {!loading && categories.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No categories.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Modal open={!!deleting} title="Delete Category" onClose={() => setDeleting(null)}>
        {deleting && (
          <div className="space-y-4">
            <p className="text-sm text-gray-300">
              Are you sure you want to delete <strong>{deleting.display_name}</strong>? This removes the
              category itself — tracks already tagged with it keep that tag, but it disappears from every
              category dropdown and picker.
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
