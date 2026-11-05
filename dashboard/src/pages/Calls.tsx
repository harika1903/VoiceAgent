import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PhoneCall, ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { agents, calls, type Agent, type CallHistoryResponse } from '../services/api';
import { formatDuration, formatDate } from '../utils/format';
import Badge from '../components/ui/Badge';

const PAGE_SIZE = 20;

export default function Calls() {
  const navigate = useNavigate();
  const [data, setData] = useState<CallHistoryResponse | null>(null);
  const [agentList, setAgentList] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [agentFilter, setAgentFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  useEffect(() => {
    agents.list().then(setAgentList).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    calls
      .list({ limit: PAGE_SIZE, offset, agent_id: agentFilter || undefined, status: statusFilter || undefined })
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [offset, agentFilter, statusFilter]);

  function resetFilters() {
    setAgentFilter('');
    setStatusFilter('');
    setOffset(0);
  }

  const hasFilters = agentFilter || statusFilter;
  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-zinc-100">Call Logs</h1>
        <p className="mt-1 text-sm text-zinc-400">View and analyze your call history</p>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <select
            value={agentFilter}
            onChange={(e) => { setAgentFilter(e.target.value); setOffset(0); }}
            className="appearance-none pl-9 pr-8 py-2 rounded-lg border border-zinc-800 bg-zinc-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">All agents</option>
            {agentList.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>

        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}
          className="px-3 py-2 rounded-lg border border-zinc-800 bg-zinc-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">All statuses</option>
          {['active', 'ended', 'failed', 'queued', 'connecting'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        {hasFilters && (
          <button onClick={resetFilters} className="text-sm text-indigo-400 hover:text-indigo-400 font-medium">
            Clear filters
          </button>
        )}

        {data && (
          <span className="ml-auto text-sm text-zinc-400">{data.total} total calls</span>
        )}
      </div>

      {/* Table */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-800/60">
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Agent</th>
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Status</th>
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Type</th>
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Duration</th>
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Date</th>
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Summary</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                [...Array(5)].map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    {[...Array(6)].map((_, j) => (
                      <td key={j} className="px-5 py-3"><div className="h-4 w-20 bg-zinc-800 rounded" /></td>
                    ))}
                  </tr>
                ))
              ) : !data || data.calls.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-5 py-16 text-center">
                    <PhoneCall size={40} className="mx-auto mb-3 text-zinc-600" />
                    <p className="text-zinc-400 font-medium">No calls found</p>
                    <p className="text-zinc-500 text-xs mt-1">
                      {hasFilters ? 'Try adjusting your filters' : 'Start a test call from the Agents page'}
                    </p>
                  </td>
                </tr>
              ) : (
                data.calls.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/calls/${c.id}`)}
                    className="border-b border-zinc-800 hover:bg-zinc-800 cursor-pointer transition-colors"
                  >
                    <td className="px-5 py-3 font-medium text-zinc-100">{c.agent_id}</td>
                    <td className="px-5 py-3"><Badge status={c.status} /></td>
                    <td className="px-5 py-3 text-zinc-400 capitalize">{c.call_type || '—'}</td>
                    <td className="px-5 py-3 text-zinc-400">{formatDuration(c.duration_secs)}</td>
                    <td className="px-5 py-3 text-zinc-400">{formatDate(c.created_at)}</td>
                    <td className="px-5 py-3 text-zinc-400 max-w-[200px] truncate">{c.summary || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-zinc-800 px-5 py-3">
            <span className="text-sm text-zinc-400">
              Page {currentPage} of {totalPages}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0}
                className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-3 py-1.5 text-sm text-zinc-400 hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ChevronLeft size={16} /> Prev
              </button>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={currentPage >= totalPages}
                className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-3 py-1.5 text-sm text-zinc-400 hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
