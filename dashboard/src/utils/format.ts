export function formatDuration(secs: number | null | undefined): string {
  if (secs == null || secs <= 0) return '—'
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  if (m === 0) return `${s}s`
  return `${m}m ${s}s`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`
  if (diff < 604800_000) return `${Math.floor(diff / 86400_000)}d ago`
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatDateFull(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })
}

export function truncate(s: string | null | undefined, max: number): string {
  if (!s) return '—'
  return s.length <= max ? s : s.slice(0, max) + '…'
}
