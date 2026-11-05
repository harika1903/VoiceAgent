import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Save, Trash2, Info } from 'lucide-react';
import { agents, kb, type Agent, type AgentSpec, type KBDocument } from '../services/api';
import { useToast } from '../components/ui/Toast';
import Modal from '../components/ui/Modal';
import Tabs from '../components/ui/Tabs';
import TestCallPanel from '../components/playground/TestCallPanel';

const VOICES = [
  { value: '', label: 'Default (server setting)' },
  { value: 'aura-2-thalia-en', label: 'Thalia (Female, Warm)' },
  { value: 'aura-2-luna-en', label: 'Luna (Female, Soft)' },
  { value: 'aura-2-asteria-en', label: 'Asteria (Female, Clear)' },
  { value: 'aura-2-orion-en', label: 'Orion (Male, Deep)' },
  { value: 'aura-2-arcas-en', label: 'Arcas (Male, Warm)' },
];

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'Hindi' },
  { value: 'ta', label: 'Tamil' },
  { value: 'te', label: 'Telugu' },
  { value: 'kn', label: 'Kannada' },
  { value: 'ml', label: 'Malayalam' },
  { value: 'es', label: 'Spanish' },
  { value: 'fr', label: 'French' },
  { value: 'de', label: 'German' },
  { value: 'ja', label: 'Japanese' },
];

const DEFAULT_SPEC: AgentSpec = {
  name: '',
  system_prompt: '',
  greeting_instruction: 'Greet the caller briefly and ask how you can help.',
  language: 'en',
  voice: null,
  llm_model: null,
  speaker_lock: true,
  kb_file: '',
  kb_top_k: 3,
};

const inputCls = (hasError?: boolean) =>
  `w-full rounded-lg border px-3 py-2 text-sm bg-zinc-800 text-zinc-100 placeholder:text-zinc-500 ${hasError ? 'border-red-700 bg-red-500/10' : 'border-zinc-700'} focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-500`;

export default function AgentBuilder() {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === 'new';
  const navigate = useNavigate();
  const { toast } = useToast();

  const [agentId, setAgentId] = useState('');
  const [spec, setSpec] = useState<AgentSpec>({ ...DEFAULT_SPEC });
  const [version, setVersion] = useState(1);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [kbDocs, setKbDocs] = useState<KBDocument[] | null>(null);

  useEffect(() => {
    if (!isNew && id) {
      agents.get(id).then((a: Agent) => {
        setAgentId(a.id);
        setVersion(a.version);
        setSpec({
          name: a.name,
          system_prompt: a.system_prompt,
          greeting_instruction: a.greeting_instruction,
          language: a.language,
          voice: a.voice,
          llm_model: a.llm_model,
          speaker_lock: a.speaker_lock,
          kb_file: a.kb_file,
          kb_top_k: a.kb_top_k,
        });
      }).catch((e) => {
        toast('error', 'Failed to load agent');
        console.error(e);
      }).finally(() => setLoading(false));
    }
  }, [id, isNew, toast]);

  useEffect(() => {
    kb.list().then(setKbDocs).catch(() => setKbDocs([]));
  }, []);

  const update = (field: keyof AgentSpec, value: unknown) => {
    setSpec((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => { const n = { ...prev }; delete n[field]; return n; });
  };

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!spec.name.trim()) e.name = 'Name is required';
    else if (spec.name.length > 120) e.name = 'Name must be 120 characters or less';
    if (!spec.system_prompt.trim()) e.system_prompt = 'System prompt is required';
    if (isNew && !agentId.trim()) e.agentId = 'Agent ID is required';
    else if (isNew && !/^[a-z0-9_-]{1,63}$/.test(agentId)) e.agentId = 'Lowercase letters, digits, - or _ only (max 63)';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      if (isNew) {
        const created = await agents.create(agentId, spec);
        toast('success', `Agent "${created.name}" created`);
        navigate(`/agents/${created.id}`, { replace: true });
      } else {
        const updated = await agents.update(id!, spec);
        setVersion(updated.version);
        toast('success', `Agent updated to v${updated.version}`);
      }
    } catch (e: unknown) {
      toast('error', e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await agents.delete(id!);
      toast('success', 'Agent deleted');
      navigate('/agents', { replace: true });
    } catch (e: unknown) {
      toast('error', e instanceof Error ? e.message : 'Delete failed');
    }
    setShowDelete(false);
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-800 border-t-indigo-600" />
      </div>
    );
  }

  const basicInfoTab = (
    <div className="space-y-4">
      {isNew && (
        <div>
          <label className="mb-1 block text-sm font-medium text-zinc-300">Agent ID</label>
          <input
            type="text"
            value={agentId}
            onChange={(e) => { setAgentId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '')); setErrors((p) => { const n = { ...p }; delete n.agentId; return n; }); }}
            placeholder="my-agent"
            className={inputCls(!!errors.agentId)}
          />
          {errors.agentId && <p className="mt-1 text-xs text-red-400">{errors.agentId}</p>}
          <p className="mt-1 text-xs text-zinc-400">Permanent identifier. Lowercase, digits, hyphens, underscores.</p>
        </div>
      )}
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">Name</label>
        <input
          type="text"
          value={spec.name}
          onChange={(e) => update('name', e.target.value)}
          placeholder="My Voice Agent"
          className={inputCls(!!errors.name)}
        />
        {errors.name && <p className="mt-1 text-xs text-red-400">{errors.name}</p>}
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">Language</label>
        <select value={spec.language} onChange={(e) => update('language', e.target.value)} className={inputCls()}>
          {LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
        </select>
      </div>
    </div>
  );

  const behaviorTab = (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">System Prompt</label>
        <textarea
          value={spec.system_prompt}
          onChange={(e) => update('system_prompt', e.target.value)}
          rows={12}
          placeholder="You are a helpful voice assistant for..."
          className={`${inputCls(!!errors.system_prompt)} font-mono`}
        />
        {errors.system_prompt && <p className="mt-1 text-xs text-red-400">{errors.system_prompt}</p>}
        <p className="mt-1 text-xs text-zinc-400">{spec.system_prompt.length}/20,000 characters — defines how the agent behaves and responds.</p>
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">First Message / Greeting</label>
        <textarea
          value={spec.greeting_instruction}
          onChange={(e) => update('greeting_instruction', e.target.value)}
          rows={2}
          placeholder="Greet the caller briefly and ask how you can help."
          className={inputCls()}
        />
        <p className="mt-1 text-xs text-zinc-400">What the agent says first when a caller connects.</p>
      </div>
    </div>
  );

  const voiceTab = (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">Voice</label>
        <select value={spec.voice || ''} onChange={(e) => update('voice', e.target.value || null)} className={inputCls()}>
          {VOICES.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
        </select>
        <p className="mt-1 text-xs text-zinc-400">Deepgram Aura-2 text-to-speech voices supported by this platform.</p>
      </div>
      <div className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-800 p-3">
        <button
          type="button"
          role="switch"
          aria-checked={spec.speaker_lock}
          onClick={() => update('speaker_lock', !spec.speaker_lock)}
          className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors ${spec.speaker_lock ? 'bg-indigo-600' : 'bg-zinc-700'}`}
        >
          <span className={`inline-block h-5 w-5 transform rounded-full bg-zinc-100 shadow transition-transform ${spec.speaker_lock ? 'translate-x-5.5' : 'translate-x-0.5'} mt-0.5`} />
        </button>
        <div>
          <p className="text-sm font-medium text-zinc-100">Speaker Lock</p>
          <p className="text-xs text-zinc-400">When enabled, the agent only responds to the voice registered at the start of the call. Other voices (e.g. a TV or bystander) are ignored.</p>
        </div>
      </div>
    </div>
  );

  const modelTab = (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">LLM Model</label>
        <input
          type="text"
          value={spec.llm_model || ''}
          onChange={(e) => update('llm_model', e.target.value || null)}
          placeholder="Default (server setting)"
          className={inputCls()}
        />
        <p className="mt-1 text-xs text-zinc-400">Leave empty to use the platform default. Example: openai/gpt-oss-120b (Groq).</p>
      </div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-800 p-3 text-xs text-zinc-400">
        STT (Deepgram Nova) and TTS provider are configured at the platform level and aren't yet exposed per-agent.
      </div>
    </div>
  );

  const kbTab = (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">Catalog File Path</label>
        <input
          type="text"
          value={spec.kb_file}
          onChange={(e) => update('kb_file', e.target.value)}
          placeholder="data/catalog.json"
          className={inputCls()}
        />
        <p className="mt-1 text-xs text-zinc-400">Path to a JSON product/FAQ catalog this agent searches during calls.</p>
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">Search Results (Top-K): {spec.kb_top_k}</label>
        <input
          type="range"
          min={1}
          max={10}
          value={spec.kb_top_k}
          onChange={(e) => update('kb_top_k', Number(e.target.value))}
          className="w-full accent-indigo-600"
        />
        <div className="flex justify-between text-xs text-zinc-500">
          <span>1</span><span>5</span><span>10</span>
        </div>
      </div>
      <div className="flex gap-2 rounded-lg border border-blue-800 bg-blue-500/10 p-3 text-xs text-blue-400">
        <Info size={14} className="mt-0.5 shrink-0" />
        <p>
          Documents uploaded on the <a href="/dashboard/kb" className="underline">Knowledge Base</a> page are shared across your whole
          organization, not per-agent — the backend only attaches a single catalog file to each agent. Your org currently has{' '}
          {kbDocs === null ? '…' : kbDocs.length} uploaded document{kbDocs?.length === 1 ? '' : 's'}.
        </p>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <div className="flex-1 space-y-4">
        <div className="mb-2 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-zinc-100">
            {isNew ? 'Create Agent' : spec.name || 'Edit Agent'}
          </h1>
          {!isNew && (
            <span className="rounded-full bg-indigo-500/15 px-3 py-1 text-sm font-medium text-indigo-400">
              v{version}
            </span>
          )}
        </div>

        <Tabs
          tabs={[
            { key: 'basic', label: 'Basic Info', content: basicInfoTab },
            { key: 'behavior', label: 'Behavior', content: behaviorTab },
            { key: 'voice', label: 'Voice', content: voiceTab },
            { key: 'model', label: 'Model', content: modelTab },
            { key: 'kb', label: 'Knowledge Base', content: kbTab },
          ]}
        />

        {/* Save bar */}
        <div className="flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900 px-5 py-4 shadow-sm">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            <Save size={16} />
            {saving ? 'Saving...' : isNew ? 'Create Agent' : 'Save Changes'}
          </button>
          {!isNew && (
            <>
              <span className="text-xs text-zinc-500">Saving creates version {version + 1}. Live calls keep the version they started with.</span>
              <button
                onClick={() => setShowDelete(true)}
                className="ml-auto inline-flex items-center gap-2 rounded-lg border border-red-800 px-4 py-2.5 text-sm font-medium text-red-400 hover:bg-red-500/10"
              >
                <Trash2 size={16} />
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      {/* Right: Test Playground */}
      <div className="w-full lg:w-80 xl:w-96 shrink-0">
        <div className="sticky top-6">
          <TestCallPanel agentId={isNew ? '' : id!} disabled={isNew} />
        </div>
      </div>

      <Modal open={showDelete} onClose={() => setShowDelete(false)} title="Delete Agent">
        <p className="mb-4 text-sm text-zinc-400">
          Are you sure you want to delete <strong>{spec.name}</strong>? Active calls will finish, but no new calls can be started.
        </p>
        <div className="flex justify-end gap-3">
          <button onClick={() => setShowDelete(false)} className="rounded-lg border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-300 hover:bg-zinc-800">
            Cancel
          </button>
          <button onClick={handleDelete} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700">
            Delete Agent
          </button>
        </div>
      </Modal>
    </div>
  );
}
