const colorMap: Record<string, string> = {
  active: 'bg-emerald-500/10 text-emerald-400',
  connected: 'bg-emerald-500/10 text-emerald-400',
  ended: 'bg-zinc-500/10 text-zinc-400',
  completed: 'bg-zinc-500/10 text-zinc-400',
  ending: 'bg-zinc-500/10 text-zinc-400',
  failed: 'bg-red-500/10 text-red-400',
  queued: 'bg-amber-500/10 text-amber-400',
  connecting: 'bg-amber-500/10 text-amber-400',
  recovering: 'bg-amber-500/10 text-amber-400',
  created: 'bg-blue-500/10 text-blue-400',
  dialing: 'bg-blue-500/10 text-blue-400',
};

const sizeMap = {
  sm: 'text-xs px-2 py-0.5',
  md: 'text-sm px-2.5 py-0.5',
};

export default function Badge({ status, size = 'sm' }: { status: string; size?: 'sm' | 'md' }) {
  const colors = colorMap[status.toLowerCase()] || 'bg-zinc-500/10 text-zinc-400';
  return (
    <span className={`inline-flex items-center rounded-full font-medium capitalize ${colors} ${sizeMap[size]}`}>
      {status}
    </span>
  );
}
