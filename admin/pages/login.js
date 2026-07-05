import { useState } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import { getAdminFromCookieHeader } from "../lib/auth";

export async function getServerSideProps(context) {
  // Already logged in? Skip straight to the dashboard.
  const admin = getAdminFromCookieHeader(context.req.headers.cookie);
  if (admin) {
    return { redirect: { destination: "/", permanent: false } };
  }
  return { props: {} };
}

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        setError(data.error || "Login failed.");
        return;
      }
      router.push("/");
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4">
      <Head>
        <title>Login · Al-Madih Admin</title>
      </Head>
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-3xl mb-2">🌙</div>
          <h1 className="text-gold text-2xl font-bold tracking-wide">Al-Madih</h1>
          <p className="text-gray-500 text-sm mt-1">Admin Panel</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-surface border border-border rounded-2xl p-6 space-y-4 shadow-2xl"
        >
          {error && (
            <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs text-gray-400 mb-1.5">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-surface2 border border-border rounded-lg px-3 py-2.5 text-gray-100 text-sm focus:outline-none focus:border-gold/60 focus:ring-1 focus:ring-gold/30"
              placeholder="admin@almadih.app"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1.5">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-surface2 border border-border rounded-lg px-3 py-2.5 text-gray-100 text-sm focus:outline-none focus:border-gold/60 focus:ring-1 focus:ring-gold/30"
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-gold hover:bg-gold-bright text-black font-medium rounded-lg py-2.5 text-sm transition-colors disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
