export function SkeletonCard() {
  return (
    <div className="bg-zinc-900 rounded-xl border border-zinc-800 p-6 animate-pulse">
      <div className="h-3 w-20 bg-zinc-800 rounded mb-3" />
      <div className="h-7 w-16 bg-zinc-800 rounded" />
    </div>
  )
}

export function SkeletonRow() {
  return (
    <tr className="animate-pulse">
      {[...Array(5)].map((_, i) => (
        <td key={i} className="px-4 py-3"><div className="h-4 bg-zinc-800 rounded w-20" /></td>
      ))}
    </tr>
  )
}
