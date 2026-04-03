'use client';

import { useCallback, useEffect, useState } from 'react';
import { Task, TaskStats } from '@/lib/types';
import KanbanBoard from './components/KanbanBoard';
import StatsBar from './components/StatsBar';
import StatusBar from './components/StatusBar';
import TaskDetail from './components/TaskDetail';
import DispatchForm from './components/DispatchForm';

export default function Dashboard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [stats, setStats] = useState<TaskStats | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [showDispatch, setShowDispatch] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [tasksRes, statsRes] = await Promise.all([
        fetch('/api/tasks?recent=48'),
        fetch('/api/stats'),
      ]);

      if (tasksRes.ok) {
        const data = await tasksRes.json();
        setTasks(data.tasks);
      }
      if (statsRes.ok) {
        const data = await statsRes.json();
        setStats(data);
      }
      setLastRefresh(new Date());
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleRedispatch = async (id: string) => {
    try {
      const res = await fetch(`/api/tasks/${id}/redispatch`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchData();
        setSelectedTask(null);
      }
    } catch (error) {
      console.error('Failed to redispatch:', error);
    }
  };

  const handleDismiss = async (id: string) => {
    try {
      const res = await fetch(`/api/tasks/${id}/dismiss`, { method: 'POST' });
      if (res.ok) {
        fetchData();
        setSelectedTask(null);
      }
    } catch (error) {
      console.error('Failed to dismiss:', error);
    }
  };

  const handleBulkAction = async (
    action: 'dismiss-all-failed' | 'redispatch-all-failed'
  ) => {
    try {
      const res = await fetch('/api/tasks/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      if (res.ok) fetchData();
    } catch (error) {
      console.error('Bulk action failed:', error);
    }
  };

  const failedCount = tasks.filter((t) => t.status === 'failed').length;

  return (
    <div className="min-h-screen p-4 md:p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <header className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-zinc-100">
              Fleet Dashboard
            </h1>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-[11px] text-zinc-500">Live</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-zinc-600 font-mono">
              {lastRefresh.toLocaleTimeString()}
            </span>
            <button
              onClick={fetchData}
              className="text-xs px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300 transition-colors"
            >
              Refresh
            </button>
            <button
              onClick={() => setShowDispatch(true)}
              className="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 transition-colors"
            >
              + Dispatch
            </button>
          </div>
        </div>

        <StatusBar />
      </header>

      {/* Stats */}
      <section className="mb-6">
        <StatsBar stats={stats} />
      </section>

      {/* Bulk actions */}
      {failedCount > 0 && (
        <div className="mb-4 flex items-center gap-3 px-1">
          <span className="text-xs text-zinc-500">
            {failedCount} failed tasks:
          </span>
          <button
            onClick={() => handleBulkAction('redispatch-all-failed')}
            className="text-[11px] px-2.5 py-1 rounded bg-yellow-500/15 text-yellow-300 hover:bg-yellow-500/25 transition-colors"
          >
            Re-dispatch All
          </button>
          <button
            onClick={() => handleBulkAction('dismiss-all-failed')}
            className="text-[11px] px-2.5 py-1 rounded bg-zinc-500/15 text-zinc-400 hover:bg-zinc-500/25 transition-colors"
          >
            Dismiss All
          </button>
        </div>
      )}

      {/* Kanban board */}
      <section>
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="min-h-[200px]">
                <div className="h-4 bg-zinc-800 rounded w-20 mb-3 animate-pulse" />
                <div className="space-y-2">
                  {Array.from({ length: 2 }).map((_, j) => (
                    <div
                      key={j}
                      className="h-24 bg-zinc-900 border border-zinc-800 rounded-lg animate-pulse"
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <KanbanBoard
            tasks={tasks}
            onTaskClick={setSelectedTask}
            onRedispatch={handleRedispatch}
            onDismiss={handleDismiss}
          />
        )}
      </section>

      {/* Task detail modal */}
      {selectedTask && (
        <TaskDetail
          task={selectedTask}
          onClose={() => setSelectedTask(null)}
          onRedispatch={handleRedispatch}
          onDismiss={handleDismiss}
        />
      )}

      {/* Dispatch form modal */}
      {showDispatch && (
        <DispatchForm
          onClose={() => setShowDispatch(false)}
          onDispatched={fetchData}
        />
      )}
    </div>
  );
}
