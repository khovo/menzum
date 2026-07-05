export default function Pagination({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between mt-4 text-sm text-gray-400">
      <span>
        Page {page} of {totalPages}
      </span>
      <div className="flex gap-2">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          className="px-3 py-1.5 rounded-lg border border-border bg-surface2 disabled:opacity-40 disabled:cursor-not-allowed hover:border-gold/50"
        >
          ← Prev
        </button>
        <button
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          className="px-3 py-1.5 rounded-lg border border-border bg-surface2 disabled:opacity-40 disabled:cursor-not-allowed hover:border-gold/50"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
