import { useEffect, useState } from 'react';
import { Pencil } from 'lucide-react';
import { settings, type OrgProfile, type UsageSummary } from '../services/api';
import { useToast } from '../components/ui/Toast';

export default function Settings() {
  const { toast } = useToast();

  const [org, setOrg] = useState<OrgProfile | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const [editingName, setEditingName] = useState(false);
  const [orgName, setOrgName] = useState('');
  const [savingOrg, setSavingOrg] = useState(false);

  useEffect(() => {
    Promise.all([settings.getOrg(), settings.usage()])
      .then(([o, u]) => {
        setOrg(o);
        setOrgName(o.name);
        setUsage(u);
      })
      .catch((e) => { toast('error', 'Failed to load settings'); console.error(e); })
      .finally(() => setLoading(false));
  }, []);

  const handleSaveOrg = async () => {
    if (!orgName.trim()) return;
    setSavingOrg(true);
    try {
      const updated = await settings.updateOrg(orgName.trim());
      setOrg(updated);
      setEditingName(false);
      toast('success', 'Organization name updated');
    } catch (e: unknown) {
      toast('error', e instanceof Error ? e.message : 'Update failed');
    } finally {
      setSavingOrg(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-800 border-t-indigo-600" />
      </div>
    );
  }

  const fmtDuration = (secs: number) => {
    if (secs < 60) return `${Math.round(secs)}s`;
    const m = Math.floor(secs / 60);
    const s = Math.round(secs % 60);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">Settings</h1>
        <p className="mt-1 text-sm text-zinc-400">Manage your organization profile</p>
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold text-zinc-100">Organization</h2>
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="w-32 text-sm text-zinc-400">Org ID</span>
            <span className="font-mono text-sm text-zinc-100">{org?.id}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="w-32 text-sm text-zinc-400">Name</span>
            {editingName ? (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  className="rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-100 px-3 py-1.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  onKeyDown={(e) => e.key === 'Enter' && handleSaveOrg()}
                />
                <button onClick={handleSaveOrg} disabled={savingOrg} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-700 disabled:opacity-50">
                  {savingOrg ? '...' : 'Save'}
                </button>
                <button onClick={() => { setEditingName(false); setOrgName(org?.name || ''); }} className="text-sm text-zinc-400 hover:text-zinc-300">
                  Cancel
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-sm text-zinc-100">{org?.name}</span>
                <button onClick={() => setEditingName(true)} className="rounded p-1 text-zinc-500 hover:text-zinc-400">
                  <Pencil size={14} />
                </button>
              </div>
            )}
          </div>
          {org?.max_concurrent_calls && (
            <div className="flex items-center gap-3">
              <span className="w-32 text-sm text-zinc-400">Concurrency</span>
              <span className="text-sm text-zinc-100">{org.max_concurrent_calls} calls max</span>
            </div>
          )}
          <div className="flex items-center gap-3">
            <span className="w-32 text-sm text-zinc-400">Created</span>
            <span className="text-sm text-zinc-100">{org?.created_at ? new Date(org.created_at).toLocaleDateString() : '—'}</span>
          </div>
        </div>
      </div>

      {usage && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-zinc-100">Usage (Last 30 Days)</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-lg bg-zinc-800 p-4">
              <p className="text-2xl font-bold text-zinc-100">{usage.total_calls}</p>
              <p className="text-sm text-zinc-400">Total Calls</p>
            </div>
            <div className="rounded-lg bg-zinc-800 p-4">
              <p className="text-2xl font-bold text-zinc-100">{fmtDuration(usage.total_duration_secs)}</p>
              <p className="text-sm text-zinc-400">Total Duration</p>
            </div>
            <div className="rounded-lg bg-zinc-800 p-4">
              <p className="text-2xl font-bold text-zinc-100">{fmtDuration(usage.avg_duration_secs)}</p>
              <p className="text-sm text-zinc-400">Avg Duration</p>
            </div>
          </div>
        </div>
      )}

      <p className="text-sm text-zinc-500">
        Need an API key? Manage those on the <a href="/dashboard/keys" className="text-indigo-400 hover:underline">API Keys</a> page.
      </p>
    </div>
  );
}
