import Database from 'better-sqlite3';
import path from 'path';
import os from 'os';
import { Task, TaskStats } from './types';

const DB_PATH = path.join(os.homedir(), '.claude-fleet', 'tasks.db');

function getDb(): Database.Database {
  const db = new Database(DB_PATH, { readonly: true });
  db.pragma('journal_mode = WAL');
  db.pragma('busy_timeout = 5000');
  return db;
}

function getWriteDb(): Database.Database {
  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  db.pragma('busy_timeout = 5000');
  return db;
}

export function listTasks(status?: string, limit = 100): Task[] {
  const db = getDb();
  try {
    if (status) {
      return db
        .prepare(
          'SELECT * FROM tasks WHERE status = ? ORDER BY dispatched_at DESC LIMIT ?'
        )
        .all(status, limit) as Task[];
    }
    return db
      .prepare('SELECT * FROM tasks ORDER BY dispatched_at DESC LIMIT ?')
      .all(limit) as Task[];
  } finally {
    db.close();
  }
}

export function getTask(id: string): Task | null {
  const db = getDb();
  try {
    const task = db
      .prepare('SELECT * FROM tasks WHERE id = ?')
      .get(id) as Task | undefined;
    return task ?? null;
  } finally {
    db.close();
  }
}

export function getStats(): TaskStats {
  const db = getDb();
  try {
    const counts: Record<string, number> = {};
    const rows = db
      .prepare('SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status')
      .all() as { status: string; cnt: number }[];
    for (const row of rows) {
      counts[row.status] = row.cnt;
    }

    const totalCost = (
      db
        .prepare('SELECT COALESCE(SUM(cost_usd), 0) as total FROM tasks')
        .get() as { total: number }
    ).total;

    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const todayIso = todayStart.toISOString().replace('T', ' ').slice(0, 19);

    const todayCost = (
      db
        .prepare(
          "SELECT COALESCE(SUM(cost_usd), 0) as total FROM cost_log WHERE logged_at >= ?"
        )
        .get(todayIso) as { total: number }
    ).total;

    const completedToday = (
      db
        .prepare(
          "SELECT COUNT(*) as cnt FROM tasks WHERE status IN ('completed', 'merged') AND finished_at >= ?"
        )
        .get(todayIso) as { cnt: number }
    ).cnt;

    const stuckCount = (
      db
        .prepare(
          `SELECT COUNT(*) as cnt FROM tasks
           WHERE status = 'running'
           AND last_heartbeat < datetime('now', '-10 minutes')`
        )
        .get() as { cnt: number }
    ).cnt;

    return {
      counts,
      total: Object.values(counts).reduce((a, b) => a + b, 0),
      today_cost: todayCost,
      total_cost: totalCost,
      stuck_count: stuckCount,
      completed_today: completedToday,
    };
  } finally {
    db.close();
  }
}

export function updateTaskStatus(
  id: string,
  status: string,
  errorMessage?: string
): boolean {
  const db = getWriteDb();
  try {
    const now = new Date().toISOString().slice(0, 19) + 'Z';
    let sql = 'UPDATE tasks SET status = ?, updated_at = ?';
    const params: (string | null)[] = [status, now];

    if (status === 'failed' && errorMessage) {
      sql += ', error_message = ?';
      params.push(errorMessage);
    }
    if (status === 'queued') {
      sql += ', started_at = NULL, finished_at = NULL, error_message = ?';
      params.push('');
    }
    if (['completed', 'failed', 'dismissed', 'merged', 'cancelled'].includes(status)) {
      sql += ', finished_at = ?';
      params.push(now);
    }

    sql += ' WHERE id = ?';
    params.push(id);

    const result = db.prepare(sql).run(...params);
    return result.changes > 0;
  } finally {
    db.close();
  }
}

export function getRecentTasks(hours = 24): Task[] {
  const db = getDb();
  try {
    const cutoff = new Date(Date.now() - hours * 60 * 60 * 1000)
      .toISOString()
      .slice(0, 19) + 'Z';
    return db
      .prepare(
        "SELECT * FROM tasks WHERE updated_at >= ? OR status IN ('queued', 'running') ORDER BY dispatched_at DESC"
      )
      .all(cutoff) as Task[];
  } finally {
    db.close();
  }
}
