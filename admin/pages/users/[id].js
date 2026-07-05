import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/router";
import Layout from "../../components/Layout";
import { requireAdmin } from "../../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: { id: context.params.id } };
}

function fmtDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleString();
}

export default function UserDetail({ id }) {
  const router = useRouter();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    fetch(`/api/users/${id}`)
      .then((r) => r.json())
      .then((d) => (d.ok ? setData(d) : setError(d.error || "Failed to load.")));
  }, [id]);

  useEffect(() => { load(); }, [load]);

  async function toggleBan() {
    setBusy(true);
    try {
      const action = data.user.banned ? "unban" : "ban";
      const reason = action === "ban" ? window.prompt("Reason for ban (optional):") || "" : undefined;
      await fetch(`/api/users/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reason }),
      });
      load();
    } finally {
      setBusy(false);
    }
  }

  if (error) return <Layout title="User"><p className="text-red-400">{error}</p></Layout>;
  if (!data) return <Layout title="User"><p className="text-gray-500">Loading…</p></Layout>;

  const { user, listen_history, favorites, pdf_favorites } = data;

  return (
    <Layout title={user.first_name}>
      <button onClick={() => router.push("/users")} className="text-xs text-gray-500 hover:text-gold mb-4">← Back to Users</button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-surface border border-border rounded-xl p-5 lg:col-span-1">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Profile</h2>
          <dl className="space-y-2.5 text-sm">
            <Row label="User ID" value={user.id} />
            <Row label="Name" value={user.first_name} />
            <Row label="Joined" value={fmtDate(user.joined_at)} />
            <Row label="Last Active" value={fmtDate(user.last_active)} />
            <Row label="Total Plays" value={user.total_plays} />
            <Row label="State" value={user.state} />
            <Row
              label="Status"
              value={user.banned ? `Banned${user.ban_reason ? ` — ${user.ban_reason}` : ""}` : "Active"}
            />
          </dl>
          <button
            onClick={toggleBan}
            disabled={busy}
            className={`w-full mt-5 rounded-lg py-2.5 text-sm font-medium transition-colors ${
              user.banned
                ? "bg-green-900/40 text-green-400 border border-green-800 hover:bg-green-900/60"
                : "bg-red-900/40 text-red-400 border border-red-800 hover:bg-red-900/60"
            }`}
          >
            {user.banned ? "Unban User" : "Ban User"}
          </button>
        </div>

        <div className="bg-surface border border-border rounded-xl p-5 lg:col-span-2">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Listen History (most recent 50)</h2>
          <ul className="divide-y divide-border max-h-64 overflow-y-auto">
            {listen_history.map((h, i) => (
              <li key={i} className="py-2 flex items-center justify-between text-sm">
                <span className="text-gray-200 truncate">{h.name}</span>
                <span className="text-xs text-gray-500 shrink-0 ml-2">{fmtDate(h.played_at)}</span>
              </li>
            ))}
            {listen_history.length === 0 && <li className="py-2 text-sm text-gray-500">No listen history.</li>}
          </ul>
        </div>

        <div className="bg-surface border border-border rounded-xl p-5 lg:col-span-1">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Favorite Tracks</h2>
          <ul className="divide-y divide-border">
            {favorites.map((f) => <li key={f.id} className="py-2 text-sm text-gray-200 truncate">{f.name}</li>)}
            {favorites.length === 0 && <li className="py-2 text-sm text-gray-500">No favorites.</li>}
          </ul>
        </div>

        <div className="bg-surface border border-border rounded-xl p-5 lg:col-span-2">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Favorite PDFs</h2>
          <ul className="divide-y divide-border">
            {pdf_favorites.map((f) => <li key={f.id} className="py-2 text-sm text-gray-200 truncate">{f.title}</li>)}
            {pdf_favorites.length === 0 && <li className="py-2 text-sm text-gray-500">No favorite PDFs.</li>}
          </ul>
        </div>
      </div>
    </Layout>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-gray-200 text-right">{value}</dd>
    </div>
  );
}
