"""Fleet Dashboard SQLite Database — primary data store.

Migrates from file-based JSON/MD to SQLite while keeping JSON files as
backup/sync format. SQLite eliminates race conditions from concurrent
file reads and stale glob caching.
"""

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

FLEET_DIR = Path.home() / ".claude-fleet"
DB_PATH = FLEET_DIR / "fleet.db"

# Thread-local connections are not needed — FastAPI runs in a single thread
# with async. We use check_same_thread=False for safety.
_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    """Get or create the SQLite connection."""
    global _conn
    if _conn is None:
        FLEET_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            slug TEXT,
            branch TEXT,
            project_name TEXT,
            project_path TEXT,
            subdir TEXT,
            dispatched_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            merged_at TEXT,
            status TEXT DEFAULT 'queued',
            base_branch TEXT DEFAULT 'main',
            prompt TEXT,
            prompt_file TEXT,
            budget_usd REAL,
            permission_mode TEXT,
            tmux_session TEXT,
            pr_url TEXT,
            merged_into TEXT,
            error_message TEXT,
            raw_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_name);
        CREATE INDEX IF NOT EXISTS idx_tasks_finished ON tasks(finished_at);

        CREATE TABLE IF NOT EXISTS review_items (
            filename TEXT PRIMARY KEY,
            task_id TEXT,
            project TEXT,
            type TEXT,
            priority TEXT DEFAULT 'normal',
            created_at TEXT,
            review_category TEXT,
            body TEXT,
            summary TEXT,
            branch TEXT,
            pr_status TEXT DEFAULT 'unknown',
            archived INTEGER DEFAULT 0,
            archived_at TEXT,
            raw_yaml TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_review_active ON review_items(archived);
        CREATE INDEX IF NOT EXISTS idx_review_task ON review_items(task_id);

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            freeze_projects TEXT,
            freeze_from TEXT,
            freeze_until TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS backlog (
            id TEXT PRIMARY KEY,
            slug TEXT,
            priority INTEGER DEFAULT 0,
            project_name TEXT,
            project_path TEXT,
            prompt TEXT,
            budget_usd REAL,
            estimated_minutes INTEGER,
            category TEXT,
            raw_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_backlog_priority ON backlog(priority);

        CREATE TABLE IF NOT EXISTS auto_heal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            bug_id TEXT,
            project TEXT,
            action TEXT,
            result TEXT,
            details TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_heal_timestamp ON auto_heal_log(timestamp);
    """)
    conn.commit()


# ── Migration: JSON → SQLite ──────────────────────────────


def migrate_tasks() -> int:
    """Import task manifests from JSON files into SQLite. Returns count."""
    conn = get_conn()
    tasks_dir = FLEET_DIR / "tasks"
    if not tasks_dir.exists():
        return 0

    count = 0
    for f in tasks_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            task_id = data.get("id", f.stem)
            # Upsert — update if exists, insert if not
            conn.execute("""
                INSERT INTO tasks (id, slug, branch, project_name, project_path,
                    subdir, dispatched_at, started_at, finished_at, merged_at,
                    status, base_branch, prompt, prompt_file, budget_usd,
                    permission_mode, tmux_session, pr_url, merged_into,
                    error_message, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    merged_at=excluded.merged_at,
                    pr_url=excluded.pr_url,
                    error_message=excluded.error_message,
                    raw_json=excluded.raw_json
            """, (
                task_id,
                data.get("slug", ""),
                data.get("branch", ""),
                data.get("project_name", ""),
                data.get("project_path", ""),
                data.get("subdir", ""),
                data.get("dispatched_at", ""),
                data.get("started_at", ""),
                data.get("finished_at", ""),
                data.get("merged_at", ""),
                data.get("status", "queued"),
                data.get("base_branch", "main"),
                data.get("prompt", ""),
                data.get("prompt_file", ""),
                data.get("budget_usd"),
                data.get("permission_mode", ""),
                data.get("tmux_session", ""),
                data.get("pr_url", ""),
                data.get("merged_into", ""),
                data.get("error_message", ""),
                json.dumps(data),
            ))
            count += 1
        except (json.JSONDecodeError, OSError):
            pass
    conn.commit()
    return count


def migrate_review_items() -> int:
    """Import review queue items from markdown files into SQLite."""
    conn = get_conn()
    review_dir = FLEET_DIR / "review-queue"
    if not review_dir.exists():
        return 0

    count = 0
    # Active items
    for f in review_dir.glob("*.md"):
        count += _import_review_file(conn, f, archived=False)
    # Archived items
    archive_dir = review_dir / "archived"
    if archive_dir.exists():
        for f in archive_dir.glob("*.md"):
            count += _import_review_file(conn, f, archived=True)
    conn.commit()
    return count


def _import_review_file(conn: sqlite3.Connection, f: Path, archived: bool) -> int:
    """Import a single review queue markdown file."""
    try:
        text = f.read_text()
        if not text.startswith("---"):
            return 0
        parts = text.split("---", 2)
        if len(parts) < 3:
            return 0
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return 0
        body = parts[2].strip()

        conn.execute("""
            INSERT INTO review_items (filename, task_id, project, type, priority,
                created_at, review_category, body, archived, raw_yaml)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                type=excluded.type,
                priority=excluded.priority,
                review_category=excluded.review_category,
                archived=excluded.archived
        """, (
            f.name,
            meta.get("task_id", ""),
            meta.get("project", ""),
            meta.get("type", ""),
            meta.get("priority", "normal"),
            meta.get("created_at", ""),
            meta.get("review_category", ""),
            body,
            1 if archived else 0,
            yaml.dump(meta),
        ))
        return 1
    except OSError:
        return 0


def migrate_events() -> int:
    """Import events from events.json into SQLite."""
    conn = get_conn()
    events_file = FLEET_DIR / "events.json"
    if not events_file.exists():
        return 0

    count = 0
    try:
        events = json.loads(events_file.read_text())
        for event in events:
            freeze_projects = json.dumps(event.get("freeze_projects", []))
            conn.execute("""
                INSERT INTO events (title, start, end, freeze_projects,
                    freeze_from, freeze_until, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                event.get("title", ""),
                event.get("start", ""),
                event.get("end", ""),
                freeze_projects,
                event.get("freeze_from", ""),
                event.get("freeze_until", ""),
                event.get("notes", ""),
            ))
            count += 1
    except (json.JSONDecodeError, OSError):
        pass
    conn.commit()
    return count


def migrate_backlog() -> int:
    """Import backlog from backlog.json into SQLite."""
    conn = get_conn()
    backlog_file = FLEET_DIR / "backlog.json"
    if not backlog_file.exists():
        return 0

    count = 0
    try:
        data = json.loads(backlog_file.read_text())
        for task in data.get("tasks", []):
            task_id = task.get("id", task.get("slug", ""))
            conn.execute("""
                INSERT INTO backlog (id, slug, priority, project_name,
                    project_path, prompt, budget_usd, estimated_minutes,
                    category, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    priority=excluded.priority,
                    prompt=excluded.prompt,
                    raw_json=excluded.raw_json
            """, (
                task_id,
                task.get("slug", ""),
                task.get("priority", 0),
                task.get("project_name", ""),
                task.get("project_path", ""),
                task.get("prompt", ""),
                task.get("budget_usd"),
                task.get("estimated_minutes"),
                task.get("category", ""),
                json.dumps(task),
            ))
            count += 1
    except (json.JSONDecodeError, OSError):
        pass
    conn.commit()
    return count


def run_migration() -> dict[str, int]:
    """Run all migrations. Safe to run repeatedly (upserts)."""
    results = {
        "tasks": migrate_tasks(),
        "review_items": migrate_review_items(),
        "events": migrate_events(),
        "backlog": migrate_backlog(),
    }
    return results


# ── Query helpers ─────────────────────────────────────────


def get_all_tasks() -> list[dict]:
    """Get all tasks, newest first."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT raw_json FROM tasks ORDER BY id DESC"
    ).fetchall()
    result = []
    for row in rows:
        try:
            result.append(json.loads(row["raw_json"]))
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def get_tasks_by_status(status: str) -> list[dict]:
    """Get tasks filtered by status."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT raw_json FROM tasks WHERE status = ? ORDER BY id DESC",
        (status,)
    ).fetchall()
    result = []
    for row in rows:
        try:
            result.append(json.loads(row["raw_json"]))
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def update_task(task_id: str, updates: dict) -> bool:
    """Update specific fields of a task. Also updates raw_json."""
    conn = get_conn()
    # First get the current raw_json
    row = conn.execute(
        "SELECT raw_json FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not row:
        return False

    try:
        data = json.loads(row["raw_json"])
    except (json.JSONDecodeError, TypeError):
        data = {}

    data.update(updates)

    # Build SET clause for known columns
    known_cols = {
        "status", "started_at", "finished_at", "merged_at",
        "pr_url", "error_message", "branch",
    }
    sets = []
    params = []
    for key, val in updates.items():
        if key in known_cols:
            sets.append(f"{key} = ?")
            params.append(val)

    sets.append("raw_json = ?")
    params.append(json.dumps(data))
    params.append(task_id)

    conn.execute(
        f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    conn.commit()

    # Also update the JSON file for backward compatibility
    task_file = FLEET_DIR / "tasks" / f"{task_id}.json"
    if task_file.exists():
        try:
            task_file.write_text(json.dumps(data, indent=2))
        except OSError:
            pass

    return True


def get_task(task_id: str) -> Optional[dict]:
    """Get a single task by ID or partial match."""
    conn = get_conn()
    # Exact match
    row = conn.execute(
        "SELECT raw_json FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row:
        try:
            return json.loads(row["raw_json"])
        except (json.JSONDecodeError, TypeError):
            return None
    # Partial match
    row = conn.execute(
        "SELECT raw_json FROM tasks WHERE id LIKE ?", (f"%{task_id}%",)
    ).fetchone()
    if row:
        try:
            return json.loads(row["raw_json"])
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def get_active_review_items() -> list[dict]:
    """Get non-archived review items."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM review_items WHERE archived = 0 ORDER BY created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def archive_review_item(task_id: str) -> Optional[str]:
    """Archive a review item by task_id. Returns filename if found."""
    conn = get_conn()
    row = conn.execute(
        "SELECT filename FROM review_items WHERE task_id LIKE ? AND archived = 0",
        (f"%{task_id}%",)
    ).fetchone()
    if not row:
        return None
    filename = row["filename"]
    conn.execute(
        "UPDATE review_items SET archived = 1, archived_at = ? WHERE filename = ?",
        (datetime.now().isoformat(), filename),
    )
    conn.commit()

    # Also move the actual file for backward compatibility
    review_dir = FLEET_DIR / "review-queue"
    archive_dir = review_dir / "archived"
    archive_dir.mkdir(exist_ok=True)
    src = review_dir / filename
    if src.exists():
        try:
            src.rename(archive_dir / filename)
        except OSError:
            pass

    return filename


def get_all_events() -> list[dict]:
    """Get all events."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM events ORDER BY start DESC").fetchall()
    result = []
    for row in rows:
        event = dict(row)
        # Parse freeze_projects back from JSON
        try:
            event["freeze_projects"] = json.loads(event.get("freeze_projects", "[]"))
        except (json.JSONDecodeError, TypeError):
            event["freeze_projects"] = []
        result.append(event)
    return result


def add_event(event: dict) -> int:
    """Add an event. Returns the new event ID."""
    conn = get_conn()
    freeze_projects = json.dumps(event.get("freeze_projects", []))
    cursor = conn.execute("""
        INSERT INTO events (title, start, end, freeze_projects,
            freeze_from, freeze_until, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        event.get("title", ""),
        event.get("start", ""),
        event.get("end", ""),
        freeze_projects,
        event.get("freeze_from", ""),
        event.get("freeze_until", ""),
        event.get("notes", ""),
    ))
    conn.commit()
    return cursor.lastrowid


def get_all_backlog() -> list[dict]:
    """Get all backlog items sorted by priority."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT raw_json FROM backlog ORDER BY priority ASC"
    ).fetchall()
    result = []
    for row in rows:
        try:
            result.append(json.loads(row["raw_json"]))
        except (json.JSONDecodeError, TypeError):
            pass
    return result


# ── Stats queries (for charts) ────────────────────────────


def get_daily_completions(days: int = 7) -> list[dict]:
    """Tasks completed per day for the last N days."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT DATE(finished_at) as day, COUNT(*) as count,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
               SUM(CASE WHEN status='merged' THEN 1 ELSE 0 END) as merged,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed
        FROM tasks
        WHERE finished_at IS NOT NULL
          AND finished_at != ''
          AND DATE(finished_at) >= DATE('now', ?)
        GROUP BY DATE(finished_at)
        ORDER BY day ASC
    """, (f"-{days} days",)).fetchall()
    return [dict(row) for row in rows]


def get_project_breakdown() -> list[dict]:
    """Task count per project."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT project_name, COUNT(*) as count,
               SUM(CASE WHEN status='completed' OR status='merged' THEN 1 ELSE 0 END) as done,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
               SUM(CASE WHEN status='running' OR status='queued' THEN 1 ELSE 0 END) as active
        FROM tasks
        WHERE project_name IS NOT NULL AND project_name != ''
        GROUP BY project_name
        ORDER BY count DESC
    """).fetchall()
    return [dict(row) for row in rows]


def get_queue_depth_history(hours: int = 24) -> list[dict]:
    """Approximate queue depth over time based on dispatched/started/finished timestamps.

    We reconstruct queue depth at each hour by counting tasks that were
    dispatched but not yet started or finished at that point in time.
    """
    conn = get_conn()
    # Get all tasks with timestamps
    rows = conn.execute("""
        SELECT id, dispatched_at, started_at, finished_at, status
        FROM tasks
        WHERE dispatched_at IS NOT NULL AND dispatched_at != ''
    """).fetchall()

    tasks = [dict(row) for row in rows]
    now = datetime.utcnow()

    # Build hourly snapshots
    snapshots = []
    for h in range(hours, -1, -1):
        from datetime import timedelta
        point = now - timedelta(hours=h)
        point_iso = point.isoformat() + "Z"

        queued = 0
        running = 0
        for t in tasks:
            dispatched = t.get("dispatched_at", "")
            started = t.get("started_at", "")
            finished = t.get("finished_at", "")

            if not dispatched or dispatched > point_iso:
                continue  # Not yet dispatched at this point
            if finished and finished <= point_iso:
                continue  # Already finished
            if started and started <= point_iso:
                running += 1
            else:
                queued += 1

        snapshots.append({
            "hour": point.strftime("%H:%M"),
            "timestamp": point_iso,
            "queued": queued,
            "running": running,
        })

    return snapshots


def log_auto_heal(bug_id: str, project: str, action: str, result: str, details: str = "") -> None:
    """Log an auto-heal action."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO auto_heal_log (bug_id, project, action, result, details)
        VALUES (?, ?, ?, ?, ?)
    """, (bug_id, project, action, result, details))
    conn.commit()


def get_auto_heal_log(limit: int = 50) -> list[dict]:
    """Get recent auto-heal log entries."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM auto_heal_log ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


# ── Sync: watch JSON files for external changes ──────────


def sync_from_json() -> dict[str, int]:
    """Re-import from JSON files to catch external changes (daemon writes).

    Called periodically to keep SQLite in sync with file-based writes
    from the worker daemon and other scripts.
    """
    return {
        "tasks": migrate_tasks(),
        "backlog": migrate_backlog(),
    }
