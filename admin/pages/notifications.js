import { useState } from "react";
import Layout from "../components/Layout";
import Modal from "../components/Modal";
import { requireAdmin } from "../lib/requireAdmin";
import { PERMISSIONS } from "../lib/roles";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context, { permission: PERMISSIONS.NOTIFICATIONS });
  if (guard) return guard;
  return { props: {} };
}

const TARGETS = [
  { value: "all", label: "All users" },
  { value: "app", label: "App users only" },
  { value: "bot", label: "Bot-only users" },
];

export default function NotificationsPage() {
  const [message, setMessage] = useState("");
  const [target, setTarget] = useState("all");
  const [previewCount, setPreviewCount] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  async function preview() {
    setPreviewing(true);
    setError("");
    try {
      const res = await fetch("/api/notifications/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message || "(preview)", target, dry_run: true }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Could not preview.");
      setPreviewCount(data.targetCount);
    } catch (err) {
      setError(err.message);
    } finally {
      setPreviewing(false);
    }
  }

  async function send() {
    setSending(true);
    setError("");
    setResult(null);
    try {
      const res = await fetch("/api/notifications/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, target }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Send failed.");
      setResult(data);
      setMessage("");
      setPreviewCount(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
      setConfirming(false);
    }
  }

  return (
    <Layout title="Notifications">
      <p className="text-sm text-gray-500 mb-5 max-w-2xl">
        Send a plain-text Telegram message to your users. This is separate from the bot's own rich
        broadcast tool (BML markup/buttons) — use this for quick, plain announcements from the admin panel.
      </p>

      {error && <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2 mb-4">{error}</div>}

      {result && (
        <div className="text-sm text-green-400 bg-green-950/40 border border-green-900 rounded-lg px-3 py-2 mb-4">
          Sent: {result.delivered} delivered, {result.failed} failed, out of {result.targetCount} targeted.
          {result.aborted && " Stopped early after repeated consecutive failures."}
        </div>
      )}

      <div className="bg-surface border border-border rounded-xl p-5 space-y-4 max-w-2xl">
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Audience</label>
          <div className="flex gap-4">
            {TARGETS.map((t) => (
              <label key={t.value} className="flex items-center gap-2 text-sm text-gray-300">
                <input
                  type="radio"
                  name="target"
                  value={t.value}
                  checked={target === t.value}
                  onChange={() => { setTarget(t.value); setPreviewCount(null); }}
                />
                {t.label}
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Message</label>
          <textarea
            value={message}
            onChange={(e) => { setMessage(e.target.value); setPreviewCount(null); }}
            rows={5}
            className="input"
            placeholder="Write your announcement…"
          />
        </div>

        <div className="flex items-center gap-3">
          <button onClick={preview} disabled={previewing} className="rounded-lg border border-border px-4 py-2.5 text-sm text-gray-300 hover:bg-surface2 disabled:opacity-50">
            {previewing ? "Checking…" : "Preview audience size"}
          </button>
          {previewCount !== null && (
            <span className="text-sm text-gray-400">{previewCount.toLocaleString()} user{previewCount === 1 ? "" : "s"} will receive this.</span>
          )}
        </div>

        <button
          onClick={() => setConfirming(true)}
          disabled={!message.trim() || sending}
          className="btn-gold w-full disabled:opacity-50"
        >
          {sending ? "Sending…" : "Send Notification"}
        </button>
      </div>

      <Modal open={confirming} title="Confirm Broadcast" onClose={() => setConfirming(false)}>
        <div className="space-y-4">
          <p className="text-sm text-gray-300">
            Send this message to <strong>{TARGETS.find((t) => t.value === target)?.label.toLowerCase()}</strong>?
            This delivers immediately and can't be recalled.
          </p>
          <div className="bg-surface2 border border-border rounded-lg p-3 text-sm text-gray-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
            {message}
          </div>
          <div className="flex gap-3">
            <button onClick={send} disabled={sending} className="flex-1 rounded-lg bg-gold hover:bg-gold-bright text-black font-medium py-2.5 text-sm transition-colors disabled:opacity-50">
              {sending ? "Sending…" : "Confirm & Send"}
            </button>
            <button onClick={() => setConfirming(false)} className="flex-1 rounded-lg border border-border py-2.5 text-sm text-gray-300 hover:bg-surface2">Cancel</button>
          </div>
        </div>
      </Modal>
    </Layout>
  );
}
