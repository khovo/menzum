import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import { requireAdmin } from "../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
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
        These 5 categories are fixed (they're the same genre tags the bot and Mini App use). You can
        rename how each one displays here without changing its underlying slug.
      </p>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-3">Slug</th>
              <th className="px-4 py-3">Display Name</th>
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
              <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-500">No categories.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Layout>
  );
}
