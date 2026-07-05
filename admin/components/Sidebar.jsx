import Link from "next/link";
import { useRouter } from "next/router";
import clsx from "clsx";

const NAV = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/audio", label: "Audio", icon: "🎵" },
  { href: "/pdfs", label: "PDFs", icon: "📄" },
  { href: "/users", label: "Users", icon: "👥" },
  { href: "/categories", label: "Categories", icon: "🏷️" },
  { href: "/analytics", label: "Analytics", icon: "📈" },
];

export default function Sidebar() {
  const router = useRouter();

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
  }

  return (
    <aside className="w-60 shrink-0 bg-surface border-r border-border min-h-screen flex flex-col">
      <div className="px-6 py-6 border-b border-border">
        <div className="text-gold font-bold text-lg tracking-wide">Al-Madih</div>
        <div className="text-xs text-gray-500 mt-0.5">Admin Panel</div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map((item) => {
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
