import { useEffect, useState } from 'react';
import { Copy, Key, Plus, Trash2 } from 'lucide-react';
import { settings, type ApiKeyItem } from '../services/api';
import { useToast } from '../components/ui/Toast';
import Modal from '../components/ui/Modal';

export default function ApiKeys() {
  const { toast } = useToast();

  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [showCreate, setShowCreate] = useState(false);
  const [label, setLabel] = useState('');
  const [creating, setCreating] = useState(false);
  const [newRawKey, setNewRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    settings
      .listKeys()
      .then((r) => setKeys(r.keys))
      .catch((e) => { toast('error', 'Failed to load API keys'); console.error(e); })
      .finally(() => setLoading(false));
  }, []);

  const handleCreate = async () => {
    if (!label.trim()) return;
    setCreating(true);
    try {
      const result = await settings.createKey(label.trim());
      setNewRawKey(result.raw_key);
      const refreshed = await settings.listKeys();
      setKeys(refreshed.keys);
      setLabel('');
    } catch (e: unknown) {
      toast('error', e instanceof Error ? e.message : 'Create key failed');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id: number) => {
    try {
      await settings.revokeKey(id);
      setKeys((prev) => prev.filter((k) => k.id !== id));
      toast('success', 'API key revoked');
    } catch (e: unknown) {
      toast('error', e instanceof Error ? e.message : 'Revoke failed');
    }
  };

  const copyKey = () => {
    if (newRawKey) {
      navigator.clipboard.writeText(newRawKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">API Keys</h1>
          <p className="mt-1 text-sm text-zinc-400">Manage programmatic access to your organization</p>
        </div>
        <button
          onClick={() => { setShowCreate(true); setNewRawKey(null); setCopied(false); }}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
        >
          <Plus size={16} />
          Create Key
        </button>
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900 shadow-sm">
        {loading ? (
          <div className="flex h-40 items-center justify-center">
            <div className="h-7 w-7 animate-spin rounded-full border-4 border-indigo-800 border-t-indigo-600" />
          </div>
        ) : keys.length === 0 ? (
          <p className="py-16 text-center text-sm text-zinc-400">No API keys yet. Create one to access the API.</p>
        ) : (
          <div className="divide-y divide-zinc-800">
            {keys.map((k) => (
              <div key={k.id} className="flex items-center justify-between px-5 py-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Key size={14} className="shrink-0 text-zinc-500" />
                    <span className="text-sm font-medium text-zinc-100">{k.label}</span>
                    {k.revoked_at && (
                      <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-xs text-red-400">Revoked</span>
                    )}
                  </div>
                  <p className="mt-0.5 font-mono text-xs text-zinc-400">{k.prefix}... &middot; Created {new Date(k.created_at).toLocaleDateString()}</p>
                </div>
                {!k.revoked_at && (
                  <button
                    onClick={() => handleRevoke(k.id)}
                    className="shrink-0 rounded-lg p-1.5 text-zinc-500 hover:bg-red-500/10 hover:text-red-400"
                    title="Revoke key"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <Modal open={showCreate} onClose={() => { setShowCreate(false); setNewRawKey(null); }} title={newRawKey ? 'Key Created' : 'Create API Key'}>
        {newRawKey ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-amber-800 bg-amber-500/10 p-4">
              <p className="mb-2 text-sm font-medium text-amber-400">Copy your API key now. It won't be shown again.</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 break-all rounded bg-zinc-900 px-3 py-2 font-mono text-sm text-zinc-100">{newRawKey}</code>
                <button onClick={copyKey} className="shrink-0 rounded-lg border border-zinc-700 p-2 hover:bg-zinc-800" title="Copy">
                  <Copy size={16} className={copied ? 'text-emerald-400' : 'text-zinc-400'} />
                </button>
              </div>
              {copied && <p className="mt-1 text-xs text-emerald-400">Copied to clipboard!</p>}
            </div>
            <div className="flex justify-end">
              <button
                onClick={() => { setShowCreate(false); setNewRawKey(null); }}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-zinc-300">Label</label>
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Production, Development"
                className="w-full rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-100 placeholder:text-zinc-500 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              />
            </div>
            <div className="flex justify-end gap-3">
              <button onClick={() => setShowCreate(false)} className="rounded-lg border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-300 hover:bg-zinc-800">
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !label.trim()}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {creating ? 'Creating...' : 'Create Key'}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
