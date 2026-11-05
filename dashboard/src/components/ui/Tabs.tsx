import { type ReactNode, useState } from 'react';

export interface TabItem {
  key: string;
  label: string;
  content: ReactNode;
}

export default function Tabs({ tabs, initial }: { tabs: TabItem[]; initial?: string }) {
  const [active, setActive] = useState(initial || tabs[0]?.key);
  const current = tabs.find((t) => t.key === active) ?? tabs[0];

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 shadow-sm">
      <div className="flex gap-1 overflow-x-auto border-b border-zinc-800 px-3 pt-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActive(t.key)}
            className={`shrink-0 rounded-t-lg px-3.5 py-2 text-sm font-medium transition-colors ${
              t.key === current.key
                ? 'border-b-2 border-indigo-400 text-indigo-400'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="px-5 py-5">{current?.content}</div>
    </div>
  );
}
