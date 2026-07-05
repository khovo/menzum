export default function StatCard({ label, value, icon }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-5 flex items-center gap-4">
      <div className="w-11 h-11 rounded-lg bg-gold/10 flex items-center justify-center text-xl shrink-0">
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-2xl font-semibold text-gray-100 truncate">{value}</div>
        <div className="text-xs text-gray-500 mt-0.5">{label}</div>
      </div>
    </div>
  );
}
