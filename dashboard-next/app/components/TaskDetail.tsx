'use client';

import { Task } from '@/lib/types';
import LogViewer from './LogViewer';

function formatDate(iso: string): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

interface TaskDetailProps {
  task: Task;
  onClose: () => void;
  onRedispatch: (id: string) => void;
  onDismiss: (id: string) => void;
}

export default function TaskDetail({
  task,
  onClose,
  onRedispatch,
  onDismiss,
}: TaskDetailProps) {
  const dependsOn = (() => {
    try {
      return JSON.parse(task.depends_on || '[]');
    } catch {
      return [];
    }
  })();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-4xl max-h-[90vh] overflow-y-auto mx-4">
        {/* Header */}
        <div className="flex items-start justify-between p-4 border-b border-zinc-800">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">
              {task.slug || task.id}
            </h2>
            <p className="text-sm text-zinc-500 font-mono mt-0.5">{task.id}</p>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-300 text-xl px-2"
          >
            ×
          </button>
        </div>

        {/* Details grid */}
        <div className="p-4 grid grid-cols-2 md:grid-cols-3 gap-3 border-b border-zinc-800">
          <Field label="Status" value={task.status} />
          <Field label="Project" value={task.project_name} />
          <Field label="Branch" value={task.branch} mono />
          <Field label="Priority" value={task.priority.toString()} />
          <Field label="Cost" value={`$${task.cost_usd.toFixed(2)}`} />
          <Field label="Route" value={task.route || '—'} />
          <Field label="Dispatched" value={formatDate(task.dispatched_at)} />
          <Field label="Started" value={formatDate(task.started_at)} />
          <Field label="Finished" value={formatDate(task.finished_at)} />
          {task.eval_result && (
            <>
              <Field label="Eval" value={task.eval_result} />
              <Field label="Eval Score" value={task.eval_score.toString()} />
              <Field
                label="Eval Cost"
                value={`$${task.eval_cost_usd.toFixed(2)}`}
              />
            </>
          )}
          {dependsOn.length > 0 && (
            <Field label="Depends On" value={dependsOn.join(', ')} mono />
          )}
        </div>

        {/* Prompt */}
        {task.prompt && (
          <div className="p-4 border-b border-zinc-800">
            <div className="text-[11px] text-zinc-500 uppercase tracking-wider mb-1">
              Prompt
            </div>
            <pre className="text-sm text-zinc-300 whitespace-pre-wrap font-mono bg-black/30 rounded-lg p-3 max-h-40 overflow-auto">
              {task.prompt}
            </pre>
          </div>
        )}

        {/* Error */}
        {task.error_message && (
          <div className="p-4 border-b border-zinc-800">
            <div className="text-[11px] text-red-400 uppercase tracking-wider mb-1">
              Error
            </div>
            <pre className="text-sm text-red-300 whitespace-pre-wrap font-mono bg-red-500/5 border border-red-500/20 rounded-lg p-3">
              {task.error_message}
            </pre>
          </div>
        )}

        {/* PR Link */}
        {task.pr_url && (
          <div className="p-4 border-b border-zinc-800">
            <a
              href={task.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 hover:text-blue-300 text-sm underline"
            >
              View Pull Request →
            </a>
          </div>
        )}

        {/* Log viewer */}
        <div className="p-4 border-b border-zinc-800">
          <LogViewer
            taskId={task.id}
            isRunning={task.status === 'running'}
          />
        </div>

        {/* Actions */}
        <div className="p-4 flex gap-2 justify-end">
          {task.status === 'failed' && (
            <>
              <button
                onClick={() => onRedispatch(task.id)}
                className="px-3 py-1.5 text-sm rounded bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30 transition-colors"
              >
                Re-dispatch
              </button>
              <button
                onClick={() => onDismiss(task.id)}
                className="px-3 py-1.5 text-sm rounded bg-zinc-500/20 text-zinc-400 hover:bg-zinc-500/30 transition-colors"
              >
                Dismiss
              </button>
            </>
          )}
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] text-zinc-600 uppercase tracking-wider">
        {label}
      </div>
      <div
        className={`text-sm text-zinc-300 truncate ${mono ? 'font-mono' : ''}`}
      >
        {value || '—'}
      </div>
    </div>
  );
}
