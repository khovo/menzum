import { useEffect, useState, useCallback } from "react";
import Layout from "../../components/Layout";
import Modal from "../../components/Modal";
import Pagination from "../../components/Pagination";
import { requireAdmin } from "../../lib/requireAdmin";
import { PERMISSIONS } from "../../lib/roles";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context, { permission: PERMISSIONS.PLAYLISTS });
  if (guard) return guard;
  return { props: {} };
}

function fmtDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString();
}

function ViewPlaylist({ id }) {
  const [playlist, setPlaylist] = useState(null);

  useEffect(() => {
    fetch(`/api/playlists/${id}`)
      .then((r) => r.json())
      .then((d) => d.ok && setPlaylist(d.playlist));
  }, [id]);

  if (!playlist) return <p className="text-sm text-gray-500">Loading…</p>;

  return (
    <div className="space-y-3">
      <div className="text-xs text-gray-500">
        Created by user {playlist.creator_id} · {fmtDate(playlist.created_at)} · {playlist.play_count} plays
      </div>
      <ol className="divide-y divide-border border border-border rounded-lg max-h-72 overflow-y-auto">
        {playlist.tracks.map((t, i) => (
          <li key={i} className="px-3 py-2 text-sm text-gray-200 flex gap-2">
            <span className="text-gray-600">{i + 1}.</span>{t.name}
          </li>
        ))}
        {playlist.tracks.length === 0 && <li className="px-3 py-4 text-sm text-gray-500">No tracks.</li>}
      </ol>
    </div>
  );
}

export default function PlaylistsPage() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [viewingId, setViewingId] = useState(null);
  const [editingTitle, setEditingTitle] = useState(null);
  const [titleValue, setTitleValue] = useState("");
  const [deleting, setDeleting] = useState(null);
  const [toggling, setToggling] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ page, search });
    fetch(`/api/playlists?${params}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) { setItems(d.items); setTotalPages(d.totalPages); }
      })
      .finally(() => setLoading(false));
  }, [page, search]);

  useEffect(() => { load(); }, [load]);

  async function saveTitle(id) {
    await fetch(`/api/playlists/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: titleValue }),
    });
    setEditingTitle(null);
    load();
  }

  async function toggleFeatured(item) {
    setToggling(item.id);
    try {
      await fetch(`/api/playlists/${item.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ featured: !item.featured }),
      });
      load();
    } finally {
      setToggling(null);
    }
  }

  async function confirmDelete() {
    const res = await fetch(`/api/playlists/${deleting.id}`, { method: "DELETE" });
    const data = await res.json();
    setDeleting(null);
    if (res.ok && data.ok) load();
  }

  return (
    <Layout title="Playlists">
      <p className="text-sm text-gray-500 mb-5 max-w-2xl">
        Playlists are created by users in the bot's chat (share-link `pl_xxxxxx` codes). You can rename
        them for internal reference, mark ones worth featuring, or remove spam/junk playlists outright.
      </p>

      <div className="flex flex-wrap items-center gap-3 mb-5">
        <input
          placeholder="Search by playlist id or creator…"
          value={search}
          onChange={(e) => { setPage(1); setSearch(e.target.value); }}
          className="input max-w-xs"
        />
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-3">ID</th>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Creator</th>
              <th className="px-4 py-3">Tracks</th>
              <th className="px-4 py-3">Plays</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id} className="border-b border-border last:border-0 hover:bg-surface2/50">
                <td className="px-4 py-3 text-gray-500 font-mono text-xs">{p.id}</td>
                <td className="px-4 py-3 text-gray-200">
                  {editingTitle === p.id ? (
                    <input autoFocus value={titleValue} onChange={(e) => setTitleValue(e.target.value)} className="input py-1" />
                  ) : (
                    p.title || <span className="text-gray-600">Untitled</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-400">{p.creator_name}</td>
                <td className="px-4 py-3 text-gray-400">{p.track_count}</td>
                <td className="px-4 py-3 text-gray-400">{p.play_count}</td>
                <td className="px-4 py-3 text-gray-400">{fmtDate(p.created_at)}</td>
                <td className="px-4 py-3 space-x-2 whitespace-nowrap">
                  {editingTitle === p.id ? (
                    <>
                      <button onClick={() => saveTitle(p.id)} className="text-gold hover:underline text-xs">Save</button>
                      <button onClick={() => setEditingTitle(null)} className="text-gray-500 hover:underline text-xs">Cancel</button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => setViewingId(p.id)} className="text-gold hover:underline text-xs">View</button>
                      <button onClick={() => { setEditingTitle(p.id); setTitleValue(p.title || ""); }} className="text-gold hover:underline text-xs">Rename</button>
                      <button
                        onClick={() => toggleFeatured(p)}
                        disabled={toggling === p.id}
                        className={`hover:underline text-xs disabled:opacity-50 ${p.featured ? "text-yellow-400" : "text-gray-400"}`}
                      >
                        {p.featured ? "★ Featured" : "☆ Feature"}
                      </button>
                      <button onClick={() => setDeleting(p)} className="text-red-400 hover:underline text-xs">Delete</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">No playlists found.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} onChange={setPage} />

      <Modal open={!!viewingId} title="Playlist" onClose={() => setViewingId(null)}>
        {viewingId && <ViewPlaylist id={viewingId} />}
      </Modal>

      <Modal open={!!deleting} title="Delete Playlist" onClose={() => setDeleting(null)}>
        {deleting && (
          <div className="space-y-4">
            <p className="text-sm text-gray-300">
              Permanently delete playlist <strong>{deleting.title || deleting.id}</strong>? Unlike audio/PDF
              deletes, this removes the document entirely — the share link will stop working.
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
