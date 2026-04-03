'use client';

import { Task } from '@/lib/types';

function elapsed(from: string, to?: string): string {
  if (!from) return '';
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return `${h}h ${m}m`;
}

const statusColors: Record<string, string> = {
  queued: 'border-yellow-500/50 bg-yellow-500/5',
  running: 'border-blue-500/50 bg-blue-500/5',
  completed: 'border-green-500/50 bg-green-500/5',
  failed: 'border-red-500/50 bg-red-500/5',
  dismissed: 'border-zinc-500/50 bg-zinc-500/5',
  merged: 'border-purple-500/50 bg-purple-500/5',
  cancelled: 'border-zinc-500/50 bg-zinc-500/5',
};

const statusDots: Record<string, string> = {
  queued: 'bg-yellow-400',
  running: 'bg-blue-400 animate-pulse',
  completed: 'bg-green-400',
  failed: 'bg-red-400',
  dismissed: 'bg-zinc-400',
  merged: 'bg-purple-400',
  cancelled: 'bg-zinc-400',
};

interface TaskCardProps {
  task: Task;
  onClick: (task: Task) => void;
  onRedispatch?: (id: string) => void;
  onDismiss?: (id: string) => void;
}

export default function TaskCard({
  task,
  onClick,
  onRedispatch,
  onDismiss,
}: TaskCardProps) {
  const elapsedTime = task.started_at
    ? elapsed(task.started_at, task.finished_at || undefined)
    : '';

  return (
    <div
      className={`border rounded-lg p-3 cursor-pointer hover:bg-white/5 transition-colors ${statusColors[task.status] || 'border-zinc-700'}`}
      onClick={() => onClick(task)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDots[task.status]}`}
          />
          <span className="font-mono text-xs text-zinc-400 truncate">
            {task.slug || task.id.slice(-12)}
          </span>
        </div>
        {task.priority > 0 && (
          <span className="text-[10px] font-mono bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded flex-shrink-0">
            P{task.priority}
          </span>
        )}
      </div>

      <div className="mt-1.5">
        <span className="text-sm text-zinc-200 font-medium">
          {task.project_name}
        </span>
      </div>

      {task.prompt && (
        <p className="mt-1 text-xs text-zinc-500 line-clamp-2">
          {task.prompt.slice(0, 120)}
        </p>
      )}

      <div className="mt-2 flex items-center justify-between text-[11px] text-zinc-500">
        <span className="font-mono">{elapsedTime}</span>
        <div className="flex items-center gap-2">
          {task.cost_usd > 0 && (
            <span className="font-mono">${task.cost_usd.toFixed(2)}</span>
          )}
          {task.pr_url && (
            <a
              href={task.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-blue-400 hover:text-blue-300"
            >
              PR
            </a>
          )}
        </div>
      </div>

      {task.status === 'running' && task.last_log_size > 0 && (
        <div className="mt-2 h-1 bg-zinc-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500/60 rounded-full transition-all"
            style={{
              width: `${Math.min((task.last_log_size / 500000) * 100, 95)}%`,
            }}
          />
        </div>
      )}

      {task.status === 'failed' && (
        <div className="mt-2">
          {task.error_message && (
            <p className="text-[11px] text-red-400/80 font-mono line-clamp-2 mb-2">
              {task.error_message}
            </p>
          )}
          <div className="flex gap-1.5">
            {onRedispatch && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onRedispatch(task.id);
                }}
                className="text-[11px] px-2 py-0.5 rounded bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30 transition-colors"
              >
                Re-dispatch
              </button>
            )}
            {onDismiss && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDismiss(task.id);
                }}
                className="text-[11px] px-2 py-0.5 rounded bg-zinc-500/20 text-zinc-400 hover:bg-zinc-500/30 transition-colors"
              >
                Dismiss
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
