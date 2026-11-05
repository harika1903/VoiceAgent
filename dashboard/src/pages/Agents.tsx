import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bot, Plus, Search } from 'lucide-react';
import { agents, type Agent } from '../services/api';
import Badge from '../components/ui/Badge';

export default function Agents() {
  const [list, setList] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    agents.list().then(setList).catch(console.error).finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter((a) => a.name.toLowerCase().includes(q) || a.id.toLowerCase().includes(q));
  }, [list, query]);

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Agents</h1>
          <p className="mt-1 text-sm text-zinc-400">Create and manage your AI voice agents</p>
        </div>
        <button
          onClick={() => navigate('/agents/new')}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
        >
          <Plus size={18} />
          Create Agent
        </button>
      </div>

      {!loading && list.length > 0 && (
        <div className="relative mb-5 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search agents..."
            className="w-full rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-100 placeholder:text-zinc-500 py-2 pl-9 pr-3 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
      )}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-48 animate-pulse rounded-xl bg-zinc-800" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-700 py-16">
          <Bot size={48} className="mb-4 text-zinc-500" />
          <h3 className="text-lg font-semibold text-zinc-300">No agents yet</h3>
          <p className="mb-6 mt-1 text-sm text-zinc-400">Create your first AI voice agent to get started</p>
          <button
            onClick={() => navigate('/agents/new')}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            <Plus size={18} />
            Create Agent
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-700 py-16">
          <Search size={40} className="mb-3 text-zinc-600" />
          <p className="text-zinc-400">No agents match &ldquo;{query}&rdquo;</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((agent) => (
            <div
              key={agent.id}
              onClick={() => navigate(`/agents/${agent.id}`)}
              className="cursor-pointer rounded-xl border border-zinc-800 bg-zinc-900 p-5 shadow-sm transition hover:border-indigo-700 hover:shadow-md"
            >
              <div className="mb-3 flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/15">
                    <Bot size={18} className="text-indigo-400" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-zinc-100">{agent.name}</h3>
                    <p className="text-xs text-zinc-400">{agent.id}</p>
                  </div>
                </div>
                <Badge status={`v${agent.version}`} />
              </div>
              <p className="mb-3 line-clamp-2 text-sm text-zinc-400">{agent.system_prompt}</p>
              <div className="flex items-center gap-3 text-xs text-zinc-400">
                <span className="rounded bg-zinc-800 px-2 py-0.5">{agent.language}</span>
                {agent.voice && <span className="truncate">{agent.voice}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
