import { useEffect, useState } from "react";
import Layout from "../../components/Layout";
import Modal from "../../components/Modal";
import { requireAdmin } from "../../lib/requireAdmin";
import { PERMISSIONS, ROLES, ROLE_LABELS } from "../../lib/roles";

export async function getServerSideProps(context) {
  const guard = requireAdmin(context, { permission: PERMISSIONS.ADMINS });
  if (guard) return guard;
  return { props: {} };
}

const ROLE_OPTIONS = Object.values(ROLES);

function CreateAdminForm({ onDone }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(ROLES.CONTENT_MANAGER);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/admins", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, name, password, role }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Could not create admin.");
      setEmail(""); setName(""); setPassword("");
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="bg-surface border border-border rounded-xl p-4 mb-5 flex flex-wrap items-end gap-3">
      {error && <div className="w-full text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">{error}</div>}
      <div className="flex-1 min-w-[180px]">
        <label className="block text-xs text-gray-400 mb-1.5">Email</label>
        <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="input" />
      </div>
      <div className="flex-1 min-w-[160px]">
        <label className="block text-xs text-gray-400 mb-1.5">Name (optional)</label>
        <input value={name} onChange={(e) => setName(e.target.value)} className="input" />
      </div>
      <div className="flex-1 min-w-[160px]">
        <label className="block text-xs text-gray-400 mb-1.5">Password</label>
        <input required type="password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} className="input" placeholder="min. 8 characters" />
      </div>
      <div className="min-w-[170px]">
        <label className="block text-xs text-gray-400 mb-1.5">Role</label>
        <select value={role} onChange={(e) => setRole(e.target.value)} className="input">
          {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
        </select>
      </div>
      <button disabled={busy} className="btn-gold">{busy ? "Creating…" : "+ Add Admin"}</button>
    </form>
  );
}

function RoleBadge({ role }) {
  const colors = {
    [ROLES.SUPER_ADMIN]: "bg-gold/10 text-gold border-gold/30",
    [ROLES.CONTENT_MANAGER]: "bg-blue-950/50 text-blue-400 border-blue-900",
    [ROLES.MODERATOR]: "bg-purple-950/50 text-purple-400 border-purple-900",
    [ROLES.ANALYST]: "bg-gray-800/50 text-gray-400 border-gray-700",
  };
  return <span className={`inline-block text-[10px] px-2 py-0.5 rounded border ${colors[role] || colors[ROLES.ANALYST]}`}>{ROLE_LABELS[role] || role}</span>;
}

export default function AdminsPage() {
  const [admins, setAdmins] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState(null);
  const [editRole, setEditRole] = useState(ROLES.ANALYST);
  const [deleting, setDeleting] = useState(null);
  const [error, setError] = useState("");

  function load() {
    setLoading(true);
    fetch("/api/admins")
      .then((r) => r.json())
      .then((d) => (d.ok ? setAdmins(d.admins) : setError(d.error || "Failed to load.")))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  function startEdit(a) {
    setEditingId(a.id);
    setEditRole(a.role);
  }

  async function saveRole(id) {
    await fetch(`/api/admins/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: editRole }),
    });
    setEditingId(null);
    load();
  }

  async function confirmDelete() {
    const res = await fetch(`/api/admins/${deleting.id}`, { method: "DELETE" });
    const data = await res.json();
    setDeleting(null);
    if (res.ok && data.ok) load();
    else setError(data.error || "Could not remove admin.");
  }

  return (
    <Layout title="Admins">
      <p className="text-sm text-gray-500 mb-5 max-w-2xl">
        Manage who can access this panel and what they can do. Super Admins can do everything, including
        managing other admins; other roles are scoped to specific sections (see the sidebar for each role).
      </p>

      {error && <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2 mb-4">{error}</div>}

      <CreateAdminForm onDone={load} />

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {admins.map((a) => (
              <tr key={a.id} className="border-b border-border last:border-0 hover:bg-surface2/50">
                <td className="px-4 py-3 text-gray-200">{a.email}</td>
                <td className="px-4 py-3 text-gray-400">{a.name || "—"}</td>
                <td className="px-4 py-3">
                  {editingId === a.id ? (
                    <select value={editRole} onChange={(e) => setEditRole(e.target.value)} className="input py-1">
                      {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                    </select>
                  ) : (
                    <RoleBadge role={a.role} />
                  )}
                </td>
                <td className="px-4 py-3 space-x-2 whitespace-nowrap">
                  {a.envManaged ? (
                    <span className="text-xs text-gray-600">Environment-configured</span>
                  ) : editingId === a.id ? (
                    <>
                      <button onClick={() => saveRole(a.id)} className="text-gold hover:underline text-xs">Save</button>
                      <button onClick={() => setEditingId(null)} className="text-gray-500 hover:underline text-xs">Cancel</button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => startEdit(a)} className="text-gold hover:underline text-xs">Change role</button>
                      <button onClick={() => setDeleting(a)} className="text-red-400 hover:underline text-xs">Remove</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!loading && admins.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-500">No admins.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Modal open={!!deleting} title="Remove Admin" onClose={() => setDeleting(null)}>
        {deleting && (
          <div className="space-y-4">
            <p className="text-sm text-gray-300">
              Remove <strong>{deleting.email}</strong>'s access to this panel? This can't be undone —
              they'll need a new account created to sign in again.
            </p>
            <div className="flex gap-3">
              <button onClick={confirmDelete} className="flex-1 rounded-lg bg-red-600 hover:bg-red-500 text-white py-2.5 text-sm font-medium transition-colors">Remove</button>
              <button onClick={() => setDeleting(null)} className="flex-1 rounded-lg border border-border py-2.5 text-sm text-gray-300 hover:bg-surface2">Cancel</button>
            </div>
          </div>
        )}
      </Modal>
    </Layout>
  );
}
