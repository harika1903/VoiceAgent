import type { LucideIcon } from 'lucide-react';

export default function ComingSoon({ icon: Icon, title, description }: { icon: LucideIcon; title: string; description: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-700 bg-zinc-900 py-20 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-zinc-800">
        <Icon size={26} className="text-zinc-500" />
      </div>
      <h2 className="text-lg font-semibold text-zinc-100">{title}</h2>
      <p className="mt-1.5 max-w-sm text-sm text-zinc-400">{description}</p>
      <span className="mt-4 rounded-full bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-400">Coming soon</span>
    </div>
  );
}
