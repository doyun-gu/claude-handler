'use client';

import { Task, TaskStatus } from '@/lib/types';
import TaskCard from './TaskCard';

const columns: { key: TaskStatus; label: string; color: string }[] = [
  { key: 'queued', label: 'Queued', color: 'text-yellow-400' },
  { key: 'running', label: 'Running', color: 'text-blue-400' },
  { key: 'completed', label: 'Completed', color: 'text-green-400' },
  { key: 'failed', label: 'Failed', color: 'text-red-400' },
];

interface KanbanBoardProps {
  tasks: Task[];
  onTaskClick: (task: Task) => void;
  onRedispatch: (id: string) => void;
  onDismiss: (id: string) => void;
}

export default function KanbanBoard({
  tasks,
  onTaskClick,
  onRedispatch,
  onDismiss,
}: KanbanBoardProps) {
  const grouped: Record<string, Task[]> = {};
  for (const col of columns) {
    grouped[col.key] = [];
  }
  for (const task of tasks) {
    if (grouped[task.status]) {
      grouped[task.status].push(task);
    } else if (task.status === 'merged') {
      grouped['completed'].push(task);
    }
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      {columns.map((col) => (
        <div key={col.key} className="min-h-[200px]">
          <div className="flex items-center justify-between mb-3">
            <h3 className={`text-sm font-semibold ${col.color}`}>
              {col.label}
            </h3>
            <span className="text-xs text-zinc-500 font-mono">
              {grouped[col.key].length}
            </span>
          </div>
          <div className="space-y-2">
            {grouped[col.key].map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onClick={onTaskClick}
                onRedispatch={
                  task.status === 'failed' ? onRedispatch : undefined
                }
                onDismiss={task.status === 'failed' ? onDismiss : undefined}
              />
            ))}
            {grouped[col.key].length === 0 && (
              <div className="text-xs text-zinc-600 text-center py-8 border border-dashed border-zinc-800 rounded-lg">
                No tasks
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
