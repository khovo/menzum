/**
 * `trend` is optional: { value: "+12%", direction: "up" | "down" }. Omit it
 * for a plain stat tile — every existing call site does, so this stays
 * backward compatible.
 */
export default function StatCard({ label, value, icon, trend }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-5 flex items-center gap-4">
      <div className="w-11 h-11 rounded-lg bg-gold/10 flex items-center justify-center text-xl shrink-0">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <div className="text-2xl font-semibold text-gray-100 truncate">{value}</div>
          {trend && (
            <span
              className={`text-xs font-medium shrink-0 ${
                trend.direction === "down" ? "text-red-400" : "text-green-400"
              }`}
            >
              {trend.direction === "down" ? "▼" : "▲"} {trend.value}
            </span>
          )}
        </div>
        <div className="text-xs text-gray-500 mt-0.5">{label}</div>
      </div>
    </div>
  );
}
