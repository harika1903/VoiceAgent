import { useEffect, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { calls, settings, type CallHistoryItem, type UsageSummary } from '../services/api';
import { formatDuration } from '../utils/format';
import { useToast } from '../components/ui/Toast';

const STATUS_COLORS: Record<string, string> = {
  ended: '#10b981',
  active: '#6366f1',
  failed: '#ef4444',
  queued: '#f59e0b',
  connecting: '#f59e0b',
};

function bucketByDay(items: CallHistoryItem[], days: number) {
  const buckets = new Map<string, number>();
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    buckets.set(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }), 0);
  }
  for (const c of items) {
    if (!c.created_at) continue;
    const d = new Date(c.created_at);
    const key = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    if (buckets.has(key)) buckets.set(key, (buckets.get(key) || 0) + 1);
  }
  return Array.from(buckets.entries()).map(([date, count]) => ({ date, count }));
}

function bucketByStatus(items: CallHistoryItem[]) {
  const buckets = new Map<string, number>();
  for (const c of items) buckets.set(c.status, (buckets.get(c.status) || 0) + 1);
  return Array.from(buckets.entries()).map(([status, value]) => ({ status, value }));
}

export default function Analytics() {
  const { toast } = useToast();
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [allCalls, setAllCalls] = useState<CallHistoryItem[] | null>(null);

  useEffect(() => {
    Promise.all([settings.usage(30), calls.list({ limit: 200 })])
      .then(([u, c]) => {
        setUsage(u);
        setAllCalls(c.calls);
      })
      .catch((e) => { toast('error', 'Failed to load analytics'); console.error(e); });
  }, []);

  const loading = allCalls === null;
  const daily = allCalls ? bucketByDay(allCalls, 14) : [];
  const byStatus = allCalls ? bucketByStatus(allCalls) : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">Analytics</h1>
        <p className="mt-1 text-sm text-zinc-400">Call volume and usage over the last 30 days</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <p className="text-sm font-medium text-zinc-400">Total Calls</p>
          <p className="mt-2 text-2xl font-semibold text-zinc-100">{usage?.total_calls ?? (loading ? '…' : '—')}</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <p className="text-sm font-medium text-zinc-400">Total Duration</p>
          <p className="mt-2 text-2xl font-semibold text-zinc-100">{usage ? formatDuration(usage.total_duration_secs) : loading ? '…' : '—'}</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <p className="text-sm font-medium text-zinc-400">Avg Duration</p>
          <p className="mt-2 text-2xl font-semibold text-zinc-100">{usage ? formatDuration(usage.avg_duration_secs) : loading ? '…' : '—'}</p>
        </div>
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="mb-4 text-sm font-semibold text-zinc-100">Call Volume — Last 14 Days</h2>
        {loading ? (
          <div className="flex h-64 items-center justify-center text-sm text-zinc-500">Loading…</div>
        ) : daily.every((d) => d.count === 0) ? (
          <div className="flex h-64 items-center justify-center text-sm text-zinc-500">No calls in this period</div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 12, fill: '#a1a1aa' }} axisLine={false} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: '#a1a1aa' }} axisLine={false} tickLine={false} width={28} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #27272a', background: '#18181b', color: '#f4f4f5' }} />
              <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={28} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="mb-4 text-sm font-semibold text-zinc-100">Calls by Status</h2>
        {loading ? (
          <div className="flex h-64 items-center justify-center text-sm text-zinc-500">Loading…</div>
        ) : byStatus.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-sm text-zinc-500">No calls yet</div>
        ) : (
          <div className="flex flex-col items-center gap-4 sm:flex-row">
            <ResponsiveContainer width="100%" height={220} className="sm:max-w-[220px]">
              <PieChart>
                <Pie data={byStatus} dataKey="value" nameKey="status" innerRadius={50} outerRadius={80} paddingAngle={2}>
                  {byStatus.map((entry) => (
                    <Cell key={entry.status} fill={STATUS_COLORS[entry.status] || '#a1a1aa'} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #27272a', background: '#18181b', color: '#f4f4f5' }} />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-1 flex-wrap gap-3">
              {byStatus.map((s) => (
                <div key={s.status} className="flex items-center gap-2 text-sm">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: STATUS_COLORS[s.status] || '#a1a1aa' }} />
                  <span className="capitalize text-zinc-300">{s.status}</span>
                  <span className="text-zinc-500">({s.value})</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <p className="text-xs text-zinc-500">
        Based on the {allCalls?.length ?? 0} most recent calls. Per-agent breakdowns aren't available from the backend yet.
      </p>
    </div>
  );
}
