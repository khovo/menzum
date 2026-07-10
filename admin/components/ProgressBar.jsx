/**
 * components/ProgressBar.jsx
 * ----------------------------
 * Thin upload-progress bar, shared by every presigned-upload form (single +
 * bulk, PDFs + audio) — see lib/uploadClient.js's onProgress callback.
 */
export default function ProgressBar({ fraction }) {
  const pct = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
  return (
    <div className="w-full h-1.5 rounded-full bg-surface2 overflow-hidden">
      <div className="h-full bg-gold transition-[width] duration-150" style={{ width: `${pct}%` }} />
    </div>
  );
}
