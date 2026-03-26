'use client';

import { useEffect, useState } from 'react';

interface SystemInfo {
  hostname: string;
  uptime: number;
  cpu_count: number;
  cpu_model: string;
  load_avg: number[];
  memory: {
    total: number;
    free: number;
    used: number;
    percent: string;
  };
  daemon_alive: boolean;
  tmux_sessions: string[];
}

export default function StatusBar() {
  const [system, setSystem] = useState<SystemInfo | null>(null);

  useEffect(() => {
    async function fetch_system() {
      try {
        const res = await fetch('/api/system');
        if (res.ok) setSystem(await res.json());
      } catch {
        // ignore
      }
    }
    fetch_system();
    const interval = setInterval(fetch_system, 30000);
    return () => clearInterval(interval);
  }, []);

  if (!system) return null;

  const formatUptime = (s: number) => {
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    if (d > 0) return `${d}d ${h}h`;
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${m}m`;
  };

  const formatBytes = (b: number) => {
    const gb = b / (1024 * 1024 * 1024);
    return `${gb.toFixed(1)} GB`;
  };

  return (
    <div className="bg-zinc-900/80 border border-zinc-800 rounded-lg px-4 py-2 flex items-center gap-6 text-xs text-zinc-400 overflow-x-auto">
      <div className="flex items-center gap-1.5">
        <span className="text-zinc-500">Host:</span>
        <span className="text-zinc-300 font-mono">{system.hostname}</span>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-zinc-500">Up:</span>
        <span className="font-mono">{formatUptime(system.uptime)}</span>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-zinc-500">Load:</span>
        <span className="font-mono">
          {system.load_avg.map((l) => l.toFixed(1)).join(' ')}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-zinc-500">RAM:</span>
        <span className="font-mono">
          {formatBytes(system.memory.used)} / {formatBytes(system.memory.total)}{' '}
          ({system.memory.percent}%)
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <span
          className={`w-2 h-2 rounded-full ${
            system.daemon_alive ? 'bg-green-400' : 'bg-red-400'
          }`}
        />
        <span>Daemon</span>
      </div>

      {system.tmux_sessions.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-zinc-500">tmux:</span>
          <span className="font-mono">
            {system.tmux_sessions.length} sessions
          </span>
        </div>
      )}
    </div>
  );
}
