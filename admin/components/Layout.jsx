import { useEffect, useState } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import Sidebar from "./Sidebar";
import { ROLE_LABELS } from "../lib/roles";

export default function Layout({ title, children }) {
  const router = useRouter();
  const [admin, setAdmin] = useState(null);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => r.json())
      .then((d) => d.ok && setAdmin(d.admin))
      .catch(() => {});
  }, []);

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
  }

  return (
    <div className="min-h-screen bg-bg flex">
      <Head>
        <title>{title ? `${title} · Al-Madih Admin` : "Al-Madih Admin"}</title>
      </Head>
      <Sidebar admin={admin} />
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="flex items-center justify-between px-6 md:px-8 py-4 border-b border-border bg-surface/40">
          <h1 className="text-lg font-semibold text-gray-100">{title || "Al-Madih Admin"}</h1>
          <div className="flex items-center gap-3">
            {admin && (
              <div className="text-right leading-tight hidden sm:block">
                <div className="text-sm text-gray-200 truncate max-w-[180px]">{admin.name || admin.email}</div>
                <div className="text-[10px] text-gold/80">{ROLE_LABELS[admin.role] || admin.role}</div>
              </div>
            )}
            <div className="w-8 h-8 rounded-full bg-gold/10 border border-gold/30 flex items-center justify-center text-gold text-sm font-medium shrink-0">
              {(admin?.name || admin?.email || "?").slice(0, 1).toUpperCase()}
            </div>
            <button
              onClick={handleLogout}
              className="px-3 py-1.5 rounded-lg text-xs text-gray-400 border border-border hover:text-red-400 hover:border-red-900 hover:bg-surface2 transition-colors"
            >
              Logout
            </button>
          </div>
        </header>
        <main className="flex-1 min-w-0 p-6 md:p-8">{children}</main>
      </div>
    </div>
  );
}
