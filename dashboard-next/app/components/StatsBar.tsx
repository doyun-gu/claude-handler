'use client';

import { TaskStats } from '@/lib/types';

interface StatsBarProps {
  stats: TaskStats | null;
}

export default function StatsBar({ stats }: StatsBarProps) {
  if (!stats) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="bg-zinc-900 border border-zinc-800 rounded-lg p-3 animate-pulse"
          >
            <div className="h-3 bg-zinc-800 rounded w-16 mb-2" />
            <div className="h-6 bg-zinc-800 rounded w-10" />
          </div>
        ))}
      </div>
    );
  }

  const cards = [
    {
      label: 'Queued',
      value: stats.counts['queued'] || 0,
      color: 'text-yellow-400',
    },
    {
      label: 'Running',
      value: stats.counts['running'] || 0,
      color: 'text-blue-400',
    },
    {
      label: 'Completed',
      value: (stats.counts['completed'] || 0) + (stats.counts['merged'] || 0),
      color: 'text-green-400',
    },
    {
      label: 'Failed',
      value: stats.counts['failed'] || 0,
      color: 'text-red-400',
    },
    {
      label: 'Today',
      value: stats.completed_today,
      color: 'text-emerald-400',
    },
    {
      label: 'Cost Today',
      value: `$${stats.today_cost.toFixed(2)}`,
      color: 'text-amber-400',
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-zinc-900 border border-zinc-800 rounded-lg p-3"
        >
          <div className="text-[11px] text-zinc-500 uppercase tracking-wider">
            {card.label}
          </div>
          <div className={`text-xl font-semibold font-mono mt-1 ${card.color}`}>
            {card.value}
          </div>
        </div>
      ))}
    </div>
  );
}
