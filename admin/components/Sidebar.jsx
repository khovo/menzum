import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/router";
import clsx from "clsx";
import { PERMISSIONS, ROLE_LABELS, hasPermission } from "../lib/roles";

const NAV = [
  { href: "/", label: "Dashboard", icon: "📊", permission: PERMISSIONS.DASHBOARD },
  { href: "/audio", label: "Audio", icon: "🎵", permission: PERMISSIONS.AUDIO },
  { href: "/pdfs", label: "PDFs", icon: "📄", permission: PERMISSIONS.PDFS },
  { href: "/playlists", label: "Playlists", icon: "🎧", permission: PERMISSIONS.PLAYLISTS },
  { href: "/users", label: "Users", icon: "👥", permission: PERMISSIONS.USERS },
  { href: "/categories", label: "Categories", icon: "🏷️", permission: PERMISSIONS.CATEGORIES },
  { href: "/notifications", label: "Notifications", icon: "📣", permission: PERMISSIONS.NOTIFICATIONS },
  { href: "/analytics", label: "Analytics", icon: "📈", permission: PERMISSIONS.ANALYTICS },
  { href: "/admins", label: "Admins", icon: "🛡️", permission: PERMISSIONS.ADMINS },
];

export default function Sidebar() {
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

  // While the role hasn't loaded yet, show every item rather than flashing
  // an empty sidebar — getServerSideProps' requireAdmin() already guarantees
  // only an authenticated session reaches this page.
  const visibleNav = admin
    ? NAV.filter((item) => hasPermission(admin.role, item.permission))
    : NAV;

  return (
    <aside className="w-60 shrink-0 bg-surface border-r border-border min-h-screen flex flex-col">
      <div className="px-6 py-6 border-b border-border">
        <div className="text-gold font-bold text-lg tracking-wide">Al-Madih</div>
        <div className="text-xs text-gray-500 mt-0.5">Admin Panel</div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {visibleNav.map((item) => {
          const active = router.pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                active
                  ? "bg-gold/10 text-gold border border-gold/30"
                  : "text-gray-400 hover:text-gray-100 hover:bg-surface2"
              )}
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="p-3 border-t border-border">
        {admin && (
          <div className="px-3 pb-2 mb-1">
            <div className="text-xs text-gray-300 truncate">{admin.name || admin.email}</div>
            <div className="text-[10px] text-gold/80 mt-0.5">{ROLE_LABELS[admin.role] || admin.role}</div>
          </div>
        )}
        <button
          onClick={handleLogout}
          className="w-full px-3 py-2.5 rounded-lg text-sm text-gray-400 hover:text-red-400 hover:bg-surface2 transition-colors text-left"
        >
          🚪 Logout
        </button>
      </div>
    </aside>
  );
}
