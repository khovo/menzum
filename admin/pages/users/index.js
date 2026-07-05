import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Layout from "../../components/Layout";
import Pagination from "../../components/Pagination";
import { requireAdmin } from "../../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
}

function fmtDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString();
}

export default function UsersPage() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ page, search });
    fetch(`/api/users?${params}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) { setItems(d.items); setTotalPages(d.totalPages); }
      })
      .finally(() => setLoading(false));
  }, [page, search]);

  useEffect(() => { load(); }, [load]);

  return (
    <Layout title="Users">
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <input
          placeholder="Search by name…"
          value={search}
          onChange={(e) => { setPage(1); setSearch(e.target.value); }}
          className="input max-w-xs"
        />
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Joined</th>
              <th className="px-4 py-3">Last Active</th>
              <th className="px-4 py-3">Plays</th>
              <th className="px-4 py-3">Favorites</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((u) => (
              <tr key={u.id} className="border-b border-border last:border-0 hover:bg-surface2/50">
                <td className="px-4 py-3 text-gray-200">{u.first_name}</td>
                <td className="px-4 py-3 text-gray-400">{fmtDate(u.joined_at)}</td>
                <td className="px-4 py-3 text-gray-400">{fmtDate(u.last_active)}</td>
                <td className="px-4 py-3 text-gray-400">{u.total_plays}</td>
                <td className="px-4 py-3 text-gray-400">{u.favorites_count}</td>
                <td className="px-4 py-3">
                  {u.banned
                    ? <span className="text-[10px] px-2 py-0.5 rounded border bg-red-950/50 text-red-400 border-red-900">Banned</span>
                    : <span className="text-[10px] px-2 py-0.5 rounded border bg-green-950/50 text-green-400 border-green-900">Active</span>}
                </td>
                <td className="px-4 py-3">
                  <Link href={`/users/${u.id}`} className="text-gold hover:underline text-xs">View →</Link>
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">No users found.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} onChange={setPage} />
    </Layout>
  );
}
