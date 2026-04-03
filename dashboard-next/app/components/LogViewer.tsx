'use client';

import { useEffect, useRef, useState } from 'react';

interface LogViewerProps {
  taskId: string;
  isRunning: boolean;
}

export default function LogViewer({ taskId, isRunning }: LogViewerProps) {
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState('');
  const [totalSize, setTotalSize] = useState(0);
  const [autoScroll, setAutoScroll] = useState(true);
  const logRef = useRef<HTMLPreElement>(null);
  const offsetRef = useRef(0);

  useEffect(() => {
    offsetRef.current = 0;
    setLog('');
    setSummary('');

    async function fetchLog() {
      try {
        const res = await fetch(`/api/logs/${taskId}`);
        if (!res.ok) return;
        const data = await res.json();
        setLog(data.log || '');
        setSummary(data.summary || '');
        setTotalSize(data.totalSize || 0);
        offsetRef.current = data.totalSize || 0;
      } catch {
        // ignore
      }
    }

    fetchLog();
  }, [taskId]);

  // Live tail for running tasks
  useEffect(() => {
    if (!isRunning) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(
          `/api/logs/${taskId}?offset=${offsetRef.current}`
        );
        if (!res.ok) return;
        const data = await res.json();
        if (data.log) {
          setLog((prev) => prev + data.log);
          offsetRef.current = data.totalSize;
          setTotalSize(data.totalSize);
        }
      } catch {
        // ignore
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [taskId, isRunning]);

  useEffect(() => {
    if (autoScroll && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log, autoScroll]);

  return (
    <div className="flex flex-col h-full">
      {summary && (
        <div className="mb-3 p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
          <div className="text-[11px] text-zinc-500 uppercase tracking-wider mb-1">
            Summary
          </div>
          <pre className="text-xs text-zinc-300 whitespace-pre-wrap font-mono">
            {summary}
          </pre>
        </div>
      )}

      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] text-zinc-500 uppercase tracking-wider">
          Log Output
          {totalSize > 0 && (
            <span className="ml-2 text-zinc-600 normal-case">
              ({(totalSize / 1024).toFixed(1)} KB)
            </span>
          )}
        </div>
        {isRunning && (
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`text-[11px] px-2 py-0.5 rounded ${
              autoScroll
                ? 'bg-blue-500/20 text-blue-300'
                : 'bg-zinc-700 text-zinc-400'
            }`}
          >
            Auto-scroll {autoScroll ? 'ON' : 'OFF'}
          </button>
        )}
      </div>

      <pre
        ref={logRef}
        className="flex-1 bg-black/50 border border-zinc-800 rounded-lg p-3 overflow-auto text-xs text-zinc-400 font-mono leading-relaxed min-h-[300px] max-h-[500px]"
      >
        {log || 'No log output available.'}
      </pre>
    </div>
  );
}
