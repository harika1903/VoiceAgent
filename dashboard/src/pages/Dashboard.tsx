import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts'
import { PhoneCall, Clock, Timer, Bot } from 'lucide-react'
import { agents, calls, settings, type Agent, type CallHistoryItem, type UsageSummary } from '../services/api'
import { formatDuration, formatDate } from '../utils/format'
import Badge from '../components/ui/Badge'
import { SkeletonCard, SkeletonRow } from '../components/ui/Skeleton'

function bucketByDay(items: CallHistoryItem[], days: number) {
  const buckets = new Map<string, number>()
  const now = new Date()
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now)
    d.setDate(d.getDate() - i)
    buckets.set(d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }), 0)
  }
  for (const c of items) {
    if (!c.created_at) continue
    const key = new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    if (buckets.has(key)) buckets.set(key, (buckets.get(key) || 0) + 1)
  }
  return Array.from(buckets.entries()).map(([date, count]) => ({ date, count }))
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [agentList, setAgentList] = useState<Agent[] | null>(null)
  const [recentCalls, setRecentCalls] = useState<CallHistoryItem[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      settings.usage(30).catch(() => null),
      agents.list().catch(() => []),
      calls.list({ limit: 50 }).catch(() => ({ calls: [] })),
    ]).then(([u, a, c]) => {
      setUsage(u)
      setAgentList(a as Agent[])
      setRecentCalls(c?.calls || [])
    }).catch(() => setError('Failed to load dashboard data'))
  }, [])

  if (error) {
    return <div className="text-center py-20 text-zinc-400">{error}</div>
  }

  const stats = [
    { label: 'Total Agents', value: agentList?.length ?? '—', icon: Bot, color: 'text-violet-400 bg-violet-500/10' },
    { label: 'Total Calls', value: usage?.total_calls ?? '—', icon: PhoneCall, color: 'text-indigo-400 bg-indigo-500/10' },
    { label: 'Total Duration', value: usage ? formatDuration(usage.total_duration_secs) : '—', icon: Clock, color: 'text-emerald-400 bg-emerald-500/10' },
    { label: 'Avg Duration', value: usage ? formatDuration(usage.avg_duration_secs) : '—', icon: Timer, color: 'text-amber-600 bg-amber-500/10' },
  ]

  const chartData = recentCalls ? bucketByDay(recentCalls, 14) : []

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {usage === null && agentList === null
          ? [...Array(4)].map((_, i) => <SkeletonCard key={i} />)
          : stats.map((s) => (
              <div key={s.label} className="bg-zinc-900 rounded-xl border border-zinc-800 p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-medium text-zinc-400">{s.label}</span>
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${s.color}`}>
                    <s.icon className="w-[18px] h-[18px]" />
                  </div>
                </div>
                <p className="text-2xl font-semibold text-zinc-100">{s.value}</p>
              </div>
            ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Call activity chart */}
        <div className="lg:col-span-2 bg-zinc-900 rounded-xl border border-zinc-800 p-5">
          <h2 className="mb-4 text-sm font-semibold text-zinc-100">Call Activity — Last 14 Days</h2>
          {recentCalls === null ? (
            <div className="flex h-56 items-center justify-center text-sm text-zinc-500">Loading…</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartData}>
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#a1a1aa' }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #27272a', background: '#18181b', color: '#f4f4f5' }} />
                <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={22} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Recent agents */}
        <div className="bg-zinc-900 rounded-xl border border-zinc-800">
          <div className="px-5 py-4 border-b border-zinc-800">
            <h2 className="text-sm font-semibold text-zinc-100">Recent Agents</h2>
          </div>
          <div className="divide-y divide-zinc-800">
            {agentList === null ? (
              [...Array(3)].map((_, i) => <div key={i} className="h-14 animate-pulse bg-zinc-800 m-3 rounded-lg" />)
            ) : agentList.length === 0 ? (
              <p className="px-5 py-10 text-center text-sm text-zinc-500">No agents yet</p>
            ) : (
              agentList.slice(0, 5).map((a) => (
                <button
                  key={a.id}
                  onClick={() => navigate(`/agents/${a.id}`)}
                  className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-800"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-zinc-100">{a.name}</p>
                    <p className="truncate text-xs text-zinc-500">{a.id}</p>
                  </div>
                  <span className="shrink-0 rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">v{a.version}</span>
                </button>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Recent calls */}
      <div className="bg-zinc-900 rounded-xl border border-zinc-800">
        <div className="px-5 py-4 border-b border-zinc-800">
          <h2 className="text-sm font-semibold text-zinc-100">Recent Calls</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800">
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Agent</th>
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Status</th>
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Duration</th>
                <th className="px-5 py-3 text-left font-medium text-zinc-400">Date</th>
              </tr>
            </thead>
            <tbody>
              {recentCalls === null
                ? [...Array(5)].map((_, i) => <SkeletonRow key={i} />)
                : recentCalls.length === 0
                  ? (
                    <tr>
                      <td colSpan={4} className="px-5 py-12 text-center text-zinc-500">
                        No calls yet. Start a test call from the Agents page.
                      </td>
                    </tr>
                  )
                  : recentCalls.slice(0, 10).map((c) => (
                    <tr
                      key={c.id}
                      onClick={() => navigate(`/calls/${c.id}`)}
                      className="border-b border-zinc-800 hover:bg-zinc-800 cursor-pointer transition-colors"
                    >
                      <td className="px-5 py-3 font-medium text-zinc-100">{c.agent_id}</td>
                      <td className="px-5 py-3"><Badge status={c.status} /></td>
                      <td className="px-5 py-3 text-zinc-400">{formatDuration(c.duration_secs)}</td>
                      <td className="px-5 py-3 text-zinc-400">{formatDate(c.created_at)}</td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
