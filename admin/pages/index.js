import { useEffect, useState } from "react";
import Link from "next/link";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import Layout from "../components/Layout";
import StatCard from "../components/StatCard";
import { requireAdmin } from "../lib/requireAdmin";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context);
  if (guard) return guard;
  return { props: {} };
}

function formatBytes(bytes) {
  if (!bytes) return "0 MB";
  const mb = bytes / (1024 * 1024);
  if (mb > 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${mb.toFixed(1)} MB`;
}

function StoragePanel() {
  const [storage, setStorage] = useState(null);

  useEffect(() => {
    fetch("/api/dashboard/storage")
      .then((r) => r.json())
      .then((d) => d.ok && setStorage(d))
      .catch(() => {});
  }, []);

  if (!storage) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-medium text-gray-300">R2 Storage</h2>
          <span className="text-xs text-gray-500">{formatBytes(storage.r2.totalBytes)} used</span>
        </div>
        <div className="w-full h-2 rounded-full bg-surface2 overflow-hidden">
          <div className="h-full bg-gold" style={{ width: `${storage.r2.usedPercent}%` }} />
        </div>
        <div className="text-xs text-gray-500 mt-2">
          {storage.r2.usedPercent.toFixed(1)}% of {formatBytes(storage.r2.limitBytes)}
          {(storage.r2.audio.truncated || storage.r2.pdf.truncated) && " (partial count — bucket is large)"}
        </div>
      </div>
      <div className="bg-surface border border-border rounded-xl p-5">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-medium text-gray-300">MongoDB Storage</h2>
          <span className="text-xs text-gray-500">{formatBytes(storage.mongo.dataSizeBytes)} used</span>
        </div>
        <div className="w-full h-2 rounded-full bg-surface2 overflow-hidden">
          <div className="h-full bg-gold" style={{ width: `${storage.mongo.usedPercent}%` }} />
        </div>
        <div className="text-xs text-gray-500 mt-2">
          {storage.mongo.usedPercent.toFixed(1)}% of {formatBytes(storage.mongo.limitBytes)}
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/dashboard/stats")
      .then((r) => r.json())
      .then((d) => (d.ok ? setData(d) : setError(d.error || "Failed to load.")))
      .catch(() => setError("Network error."));
  }, []);

  if (error) return <Layout title="Dashboard"><p className="text-red-400">{error}</p></Layout>;
  if (!data) return <Layout title="Dashboard"><p className="text-gray-500">Loading…</p></Layout>;

  const { stats, dailyPlays, topTracks, recentAudio, recentPdfs } = data;

  return (
    <Layout title="Dashboard">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        <StatCard label="App Users" value={stats.totalAppUsers.toLocaleString()} icon="📱" />
        <StatCard label="Bot Users" value={stats.totalBotUsers.toLocaleString()} icon="🤖" />
        <StatCard label="Total Audio" value={stats.totalAudio.toLocaleString()} icon="🎵" />
        <StatCard label="Total PDFs" value={stats.totalPdfs.toLocaleString()} icon="📄" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
        <StatCard label="Total Users" value={stats.totalUsers.toLocaleString()} icon="👥" />
        <StatCard label="Total Plays" value={stats.totalPlays.toLocaleString()} icon="▶️" />
        <StatCard label="R2 Storage Used" value={formatBytes(stats.storageUsedBytes)} icon="💾" />
      </div>

      <StoragePanel />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div className="bg-surface border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Daily Plays (last 30 days)</h2>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={dailyPlays}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
              <XAxis dataKey="date" stroke="#666" fontSize={11} />
              <YAxis stroke="#666" fontSize={11} allowDecimals={false} />
              <Tooltip contentStyle={{ background: "#141414", border: "1px solid #2a2a2a", borderRadius: 8 }} />
              <Line type="monotone" dataKey="plays" stroke="#C9A84C" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-surface border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Top 10 Most Played Tracks</h2>
          <ResponsiveContainer width="100%" height={240}>
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-gray-300">Recent Audio Uploads</h2>
            <Link href="/audio" className="text-xs text-gold hover:underline">View all →</Link>
          </div>
          <ul className="divide-y divide-border">
            {recentAudio.map((a) => (
              <li key={a.id} className="py-2.5 flex items-center justify-between text-sm">
                <span className="text-gray-200 truncate">{a.name}</span>
                <span className="text-xs text-gray-500 shrink-0 ml-2">{a.artist || "—"}</span>
              </li>
            ))}
            {recentAudio.length === 0 && <li className="py-2.5 text-sm text-gray-500">No audio yet.</li>}
          </ul>
        </div>

        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-gray-300">Recent PDF Uploads</h2>
            <Link href="/pdfs" className="text-xs text-gold hover:underline">View all →</Link>
          </div>
          <ul className="divide-y divide-border">
            {recentPdfs.map((p) => (
              <li key={p.id} className="py-2.5 text-sm text-gray-200 truncate">{p.title}</li>
            ))}
            {recentPdfs.length === 0 && <li className="py-2.5 text-sm text-gray-500">No PDFs yet.</li>}
          </ul>
        </div>
      </div>
    </Layout>
  );
}
