'use client';

import { useState } from 'react';

interface DispatchFormProps {
  onClose: () => void;
  onDispatched: () => void;
}

export default function DispatchForm({
  onClose,
  onDispatched,
}: DispatchFormProps) {
  const [projectName, setProjectName] = useState('');
  const [projectPath, setProjectPath] = useState('');
  const [slug, setSlug] = useState('');
  const [prompt, setPrompt] = useState('');
  const [priority, setPriority] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!projectName || !prompt) {
      setError('Project name and prompt are required');
      return;
    }

    setSubmitting(true);
    setError('');

    try {
      const res = await fetch('/api/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_name: projectName,
          project_path: projectPath,
          slug,
          prompt,
          priority,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to dispatch');
      }

      onDispatched();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to dispatch');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-lg mx-4">
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h2 className="text-lg font-semibold text-zinc-100">
            Dispatch Task
          </h2>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-300 text-xl px-2"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div>
            <label className="block text-xs text-zinc-500 uppercase tracking-wider mb-1">
              Project Name *
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full bg-black/30 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:border-blue-500 focus:outline-none font-mono"
              placeholder="e.g. dpspice"
            />
          </div>

          <div>
            <label className="block text-xs text-zinc-500 uppercase tracking-wider mb-1">
              Project Path
            </label>
            <input
              type="text"
              value={projectPath}
              onChange={(e) => setProjectPath(e.target.value)}
              className="w-full bg-black/30 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:border-blue-500 focus:outline-none font-mono"
              placeholder="e.g. ~/Developer/dpspice"
            />
          </div>

          <div>
            <label className="block text-xs text-zinc-500 uppercase tracking-wider mb-1">
              Slug
            </label>
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="w-full bg-black/30 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:border-blue-500 focus:outline-none font-mono"
              placeholder="e.g. fix-api-auth"
            />
          </div>

          <div>
            <label className="block text-xs text-zinc-500 uppercase tracking-wider mb-1">
              Prompt *
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
              className="w-full bg-black/30 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:border-blue-500 focus:outline-none font-mono resize-y"
              placeholder="Describe the task..."
            />
          </div>

          <div>
            <label className="block text-xs text-zinc-500 uppercase tracking-wider mb-1">
              Priority (0-10)
            </label>
            <input
              type="number"
              min={0}
              max={10}
              value={priority}
              onChange={(e) => setPriority(parseInt(e.target.value, 10) || 0)}
              className="w-24 bg-black/30 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:border-blue-500 focus:outline-none font-mono"
            />
          </div>

          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {submitting ? 'Dispatching...' : 'Dispatch'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
