import { NextRequest, NextResponse } from 'next/server';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const TASKS_DIR = path.join(os.homedir(), '.claude-fleet', 'tasks');
const TASK_DB = path.join(os.homedir(), 'Developer', 'claude-handler', 'task-db.py');

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { project_name, project_path, prompt, priority = 0, slug } = body;

    if (!project_name || !prompt) {
      return NextResponse.json(
        { error: 'project_name and prompt are required' },
        { status: 400 }
      );
    }

    const taskId = `${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${Date.now().toString(36)}-${slug || 'web-dispatch'}`;
    const branch = `worker/${slug || 'task'}-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`;

    const manifest = {
      id: taskId,
      slug: slug || `web-${taskId.slice(-8)}`,
      branch,
      project_name,
      project_path: project_path || '',
      status: 'queued',
      prompt,
      priority,
      dispatched_at: new Date().toISOString().slice(0, 19) + 'Z',
      budget_usd: 5.0,
      max_turns: 200,
    };

    // Write manifest JSON
    const manifestPath = path.join(TASKS_DIR, `${taskId}.json`);
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

    // Add to SQLite via task-db.py
    execSync(`python3 "${TASK_DB}" add "${manifestPath}"`, {
      timeout: 10000,
    });

    return NextResponse.json({ success: true, task_id: taskId });
  } catch (error) {
    console.error('Error dispatching task:', error);
    return NextResponse.json(
      { error: 'Failed to dispatch task' },
      { status: 500 }
    );
  }
}
