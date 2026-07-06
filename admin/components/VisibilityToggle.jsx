/**
 * components/VisibilityToggle.jsx
 * --------------------------------
 * One-click boolean toggle button (green = visible, red = hidden). Used for
 * the three independent visibility flags on audio/pdf docs: the master
 * `hidden` flag plus the per-platform `hidden_bot`/`hidden_app` flags.
 * Unlike the Delete action (which asks for confirmation), this fires
 * immediately — it's meant to be reversible with one more click.
 */
export default function VisibilityToggle({ label, hidden, onToggle, busy }) {
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onToggle}
      title={`Click to ${hidden ? "show" : "hide"} (${label})`}
      className={`text-[10px] px-2 py-1 rounded border font-medium transition-colors disabled:opacity-50 ${
        hidden
          ? "bg-red-950/50 text-red-400 border-red-900 hover:bg-red-900/50"
          : "bg-green-950/50 text-green-400 border-green-900 hover:bg-green-900/50"
      }`}
    >
      {label}: {hidden ? "Hidden" : "Visible"}
    </button>
  );
}
