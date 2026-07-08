import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import Layout from "../components/Layout";
import { requireAdmin } from "../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
}

export default function AnalyticsPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/analytics")
      .then((r) => r.json())
      .then((d) => (d.ok ? setData(d) : setError(d.error || "Failed to load.")))
      .catch(() => setError("Network error."));
  }, []);

  if (error) return <Layout title="Analytics"><p className="text-red-400">{error}</p></Layout>;
  if (!data) return <Layout title="Analytics"><p className="text-gray-500">Loading…</p></Layout>;

  const { userGrowth, playsByCategory, topPdfs, dailyPlays, topTracks } = data;

  return (
    <Layout title="Analytics">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="bg-surface border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-4">User Growth (last 30 days)</h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={userGrowth}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
              <XAxis dataKey="date" stroke="#666" fontSize={11} />
              <YAxis stroke="#666" fontSize={11} allowDecimals={false} />
              <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2a2a2a", borderRadius: 8 }} />
              <Line type="monotone" dataKey="users" stroke="#C9A84C" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-surface border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Plays per Day (last 30 days)</h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={dailyPlays}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
              <XAxis dataKey="date" stroke="#666" fontSize={11} />
              <YAxis stroke="#666" fontSize={11} allowDecimals={false} />
              <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2a2a2a", borderRadius: 8 }} />
              <Line type="monotone" dataKey="plays" stroke="#C9A84C" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="bg-surface border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Plays per Category</h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={playsByCategory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
              <XAxis dataKey="category" stroke="#666" fontSize={11} />
              <YAxis stroke="#666" fontSize={11} allowDecimals={false} />
              <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2a2a2a", borderRadius: 8 }} />
              <Bar dataKey="plays" fill="#C9A84C" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-surface border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Top 10 Most Played Tracks</h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={topTracks} layout="vertical" margin={{ left: 40 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" horizontal={false} />
              <XAxis type="number" stroke="#666" fontSize={11} allowDecimals={false} />
              <YAxis
                type="category"
                dataKey="name"
                stroke="#666"
                fontSize={10}
                width={120}
                tickFormatter={(v) => (v.length > 18 ? v.slice(0, 18) + "…" : v)}
              />
              <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2a2a2a", borderRadius: 8 }} />
              <Bar dataKey="plays" fill="#C9A84C" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-surface border border-border rounded-xl p-5">
        <h2 className="text-sm font-medium text-gray-300 mb-4">Top 10 Most Downloaded PDFs</h2>
        <ul className="divide-y divide-border">
          {topPdfs.map((p, i) => (
            <li key={p.id} className="py-2.5 flex items-center justify-between text-sm">
              <span className="text-gray-200 truncate"><span className="text-gray-600 mr-2">{i + 1}.</span>{p.title}</span>
              <span className="text-xs text-gray-500 shrink-0 ml-2">{p.downloads} downloads</span>
            </li>
          ))}
          {topPdfs.length === 0 && <li className="py-2.5 text-sm text-gray-500">No downloads yet.</li>}
        </ul>
      </div>
    </Layout>
  );
}
