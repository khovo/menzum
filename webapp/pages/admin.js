/**
 * pages/admin.js
 * --------------
 * Baraka Analytics — Secret Admin Dashboard
 *
 * ROUTE: https://almadih.vercel.app/admin
 *
 * PROTECTION MODEL (two layers):
 *   1. The password field in the UI collects a token.
 *   2. That token is sent as "Authorization: Bearer <token>" to
 *      /api/webapp/admin-stats on the BOT project.
 *   3. The API validates it against ADMIN_TOKEN (server-only env var).
 *   4. If wrong → 401 → "Invalid token" message in UI.
 *   The password is NEVER in the JS bundle. The NEXT_PUBLIC_ version of
 *   the API base URL is the only public env var needed here.
 *
 * CHARTS (recharts):
 *   • AreaChart  — New users per day, last 14 days (neon cyan)
 *   • BarChart   — Top 5 trending tracks, last 7 days (neon gold/green)
 *
 * DATA auto-refreshes every 60 seconds while the dashboard is open.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import Head from 'next/head';
import {
  AreaChart, Area,
  BarChart, Bar,
  XAxis, YAxis,
  CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

// ── Design tokens (dark futuristic — separate from bot UI palette) ────────────
const D = {
  bg:        '#050a14',
  surface:   '#08111f',
  card:      '#0c1a2e',
  cardBright:'#0f2040',
  border:    '#0f2a4a',
  borderBright: '#1a4a7a',
  cyan:      '#00e5ff',
  cyanDim:   '#0088aa',
  cyanGlow:  'rgba(0, 229, 255, 0.12)',
  gold:      '#ffd166',
  goldDim:   '#886600',
  green:     '#06d6a0',
  text:      '#c8d8f0',
  textMuted: '#4a6a9a',
  textBright:'#e8f4ff',
};

// ── Reusable stat card ────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color, delay }) {
  return (
    <div className="a-stat-card" style={{
      borderColor: color + '33',
      animationDelay: `${delay}ms`,
    }}>
      <div className="a-stat-glow" style={{ background: color + '0a' }} />
      <div className="a-stat-value" style={{ color }}>{value}</div>
      <div className="a-stat-label">{label}</div>
      {sub && <div className="a-stat-sub">{sub}</div>}
    </div>
  );
}

// ── Custom recharts tooltip ───────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: D.card, border: `1px solid ${D.borderBright}`,
      borderRadius: 10, padding: '8px 14px', fontSize: 12,
    }}>
      <div style={{ color: D.textMuted, marginBottom: 4 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.name} style={{ color: p.color, fontWeight: 700 }}>
          {p.value} {p.name}
        </div>
      ))}
    </div>
  );
}

// ── Skeleton bar for charts ───────────────────────────────────────────────────
function ChartSkeleton() {
  return (
    <div style={{
      height: 180, borderRadius: 12,
      background: `linear-gradient(90deg, ${D.card} 25%, ${D.cardBright} 50%, ${D.card} 75%)`,
      backgroundSize: '200% 100%',
      animation: 'adminSkeletonShimmer 1.4s ease infinite',
    }} />
  );
}

// ── Login screen ──────────────────────────────────────────────────────────────
function LoginScreen({ onLogin, error, loading }) {
  const [pw, setPw] = useState('');

  return (
    <div className="a-login-screen">
      <div className="a-login-card">
        {/* Logo */}
        <div className="a-login-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"
              fill={D.cyan + '22'} stroke={D.cyan} strokeWidth={1.5}/>
            <path d="M9 12l2 2 4-4" stroke={D.cyan} strokeWidth={1.5}
              strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        <h1 className="a-login-title">Baraka Analytics</h1>
        <p className="a-login-sub">Admin access only</p>

        <form onSubmit={(e) => { e.preventDefault(); onLogin(pw); }}
          style={{ width: '100%' }}>
          <div className="a-input-wrap">
            <input
              type="password"
              className="a-input"
              placeholder="Enter admin token"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              autoComplete="current-password"
              autoFocus
            />
          </div>
          {error && (
            <div className="a-login-error">{error}</div>
          )}
          <button
            type="submit"
            className="a-login-btn"
            disabled={loading || !pw}
          >
            {loading ? (
              <span className="a-spinner" />
            ) : (
              'Access Dashboard →'
            )}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Main dashboard ────────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const [token,     setToken]     = useState('');
  const [authed,    setAuthed]    = useState(false);
  const [loginErr,  setLoginErr]  = useState('');
  const [loginLoad, setLoginLoad] = useState(false);
  const [stats,     setStats]     = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [lastSync,  setLastSync]  = useState(null);
  const refreshRef = useRef(null);

  // ── Fetch stats ─────────────────────────────────────────────────────────────
  const fetchStats = useCallback(async (t) => {
    if (!t) return;
    setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/api/webapp/admin-stats`, {
        headers: { Authorization: `Bearer ${t}` },
      });
      const data = await res.json();
      if (data.ok) {
        setStats(data.stats);
        setLastSync(new Date());
      } else if (res.status === 401) {
        setAuthed(false);
        setLoginErr('Session expired. Re-enter token.');
      }
    } catch (err) {
      console.error('fetchStats error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Auto-refresh every 60s ───────────────────────────────────────────────
  useEffect(() => {
    if (!authed || !token) return;
    fetchStats(token);
    refreshRef.current = setInterval(() => fetchStats(token), 60_000);
    return () => clearInterval(refreshRef.current);
  }, [authed, token, fetchStats]);

  // ── Login handler ────────────────────────────────────────────────────────
  const handleLogin = async (pw) => {
    setLoginLoad(true);
    setLoginErr('');
    try {
      const res  = await fetch(`${API_BASE}/api/webapp/admin-stats`, {
        headers: { Authorization: `Bearer ${pw}` },
      });
      const data = await res.json();
      if (data.ok) {
        setToken(pw);
        setStats(data.stats);
        setLastSync(new Date());
        setAuthed(true);
      } else {
        setLoginErr(res.status === 401 ? 'Invalid token. Try again.' : data.error);
      }
    } catch {
      setLoginErr('Connection error. Check your internet.');
    } finally {
      setLoginLoad(false);
    }
  };

  // ── Not logged in ────────────────────────────────────────────────────────
  if (!authed) {
    return (
      <>
        <Head>
          <title>Baraka Analytics</title>
          <meta name="robots" content="noindex, nofollow" />
        </Head>
        <LoginScreen onLogin={handleLogin} error={loginErr} loading={loginLoad} />
      </>
    );
  }

  // ── Format numbers ───────────────────────────────────────────────────────
  const fmt = (n) => n?.toLocaleString() ?? '—';

  return (
    <>
      <Head>
        <title>Baraka Analytics — Al-Madih</title>
        <meta name="robots" content="noindex, nofollow" />
      </Head>

      <div className="a-dashboard">

        {/* ── Header ───────────────────────────────────────────────────── */}
        <header className="a-header">
          <div className="a-header-brand">
            <div className="a-header-dot" />
            <span className="a-header-title">Baraka Analytics</span>
          </div>
          <div className="a-header-right">
            {loading && <div className="a-spinner-sm" />}
            {lastSync && (
              <span className="a-sync-time">
                Synced {lastSync.toLocaleTimeString()}
              </span>
            )}
            <button
              className="a-refresh-btn"
              onClick={() => fetchStats(token)}
              disabled={loading}
            >↺ Refresh</button>
          </div>
        </header>

        {/* ── Stat Cards ───────────────────────────────────────────────── */}
        <div className="a-stats-grid">
          <StatCard label="Total Users"    value={fmt(stats?.totalUsers)}   color={D.cyan}  delay={0}   sub={`${fmt(stats?.activeUsers)} active today`} />
          <StatCard label="Total Plays"    value={fmt(stats?.totalPlays)}   color={D.gold}  delay={60}  />
          <StatCard label="Catalog Size"   value={fmt(stats?.totalFiles)}   color={D.green} delay={120} sub="audio files" />
        </div>

        {/* ── Charts Row ───────────────────────────────────────────────── */}
        <div className="a-charts-row">

          {/* User Growth Chart */}
          <div className="a-chart-card">
            <div className="a-chart-header">
              <span className="a-chart-title" style={{ color: D.cyan }}>
                📈 User Growth
              </span>
              <span className="a-chart-sub">Last 14 days</span>
            </div>
            {!stats ? <ChartSkeleton /> : (
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={stats.userGrowth}
                  margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                  <defs>
                    <linearGradient id="cyanGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={D.cyan} stopOpacity={0.25} />
                      <stop offset="95%" stopColor={D.cyan} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={D.border} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: D.textMuted, fontSize: 10 }}
                    axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: D.textMuted, fontSize: 10 }}
                    axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Area type="monotone" dataKey="users" name="new users"
                    stroke={D.cyan} strokeWidth={2}
                    fill="url(#cyanGrad)"
                    dot={{ fill: D.cyan, r: 3, strokeWidth: 0 }}
                    activeDot={{ fill: D.cyan, r: 5, strokeWidth: 0 }} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Trending Tracks Chart */}
          <div className="a-chart-card">
            <div className="a-chart-header">
              <span className="a-chart-title" style={{ color: D.gold }}>
                🔥 Trending Now
              </span>
              <span className="a-chart-sub">Last 7 days</span>
            </div>
            {!stats ? <ChartSkeleton /> : (
              stats.trendingTracks.length === 0 ? (
                <div className="a-chart-empty">
                  No plays recorded yet.<br/>Start listening to see trends.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={stats.trendingTracks} layout="vertical"
                    margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
                    <defs>
                      <linearGradient id="goldGrad" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%"   stopColor={D.green} stopOpacity={0.9} />
                        <stop offset="100%" stopColor={D.gold}  stopOpacity={0.9} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={D.border} strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" tick={{ fill: D.textMuted, fontSize: 10 }}
                      axisLine={false} tickLine={false} allowDecimals={false} />
                    <YAxis type="category" dataKey="name" width={110}
                      tick={{ fill: D.text, fontSize: 10 }}
                      axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="plays" name="plays" fill="url(#goldGrad)"
                      radius={[0, 6, 6, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )
            )}
          </div>

        </div>

      </div>
    </>
  );
}
