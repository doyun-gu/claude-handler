#!/usr/bin/env python3
"""
SQLite Task Database for Fleet Worker Daemon.

Replaces filesystem JSON as the source of truth for task state.
Provides atomic task claiming, status transitions, and queryable history.

Usage:
  python3 task-db.py init                    # Create/migrate schema
  python3 task-db.py import-json             # Import existing JSON tasks
  python3 task-db.py claim                   # Atomically claim next queued task
  python3 task-db.py status <id> <status>    # Update task status
  python3 task-db.py get <id>                # Get task details
  python3 task-db.py list [status]           # List tasks by status
  python3 task-db.py add <json-file>         # Add task from JSON manifest
  python3 task-db.py heartbeat <id>          # Record task heartbeat
  python3 task-db.py stuck [--minutes N]     # Find stuck tasks (no heartbeat)
  python3 task-db.py cost-today              # Show today's cost estimate
  python3 task-db.py stats                   # Summary statistics
"""

import sqlite3
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

FLEET_DIR = Path.home() / ".claude-fleet"
DB_PATH = FLEET_DIR / "tasks.db"
TASKS_DIR = FLEET_DIR / "tasks"


def get_db(readonly=False):
    """Get a database connection with WAL mode and proper settings."""
    db = sqlite3.connect(
        str(DB_PATH),
        timeout=10,
        isolation_level=None if readonly else "DEFERRED",
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    db.execute("PRAGMA busy_timeout = 5000")
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    """Create the schema if it doesn't exist."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            slug TEXT NOT NULL,
            branch TEXT NOT NULL,
            project_name TEXT NOT NULL,
            project_path TEXT NOT NULL,
            subdir TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            prompt TEXT DEFAULT '',
            prompt_file TEXT DEFAULT '',
            budget_usd REAL DEFAULT 5.0,
            max_turns INTEGER DEFAULT 200,
            permission_mode TEXT DEFAULT 'dangerously-skip-permissions',
            tmux_session TEXT DEFAULT '',
            base_branch TEXT DEFAULT 'main',
            priority INTEGER DEFAULT 0,
            depends_on TEXT DEFAULT '[]',
            group_name TEXT DEFAULT '',
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            merged_from TEXT DEFAULT '[]',
            pid INTEGER DEFAULT 0,
            pgid INTEGER DEFAULT 0,
            dispatched_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            last_heartbeat TEXT,
            last_log_size INTEGER DEFAULT 0,
            pr_url TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            cost_usd REAL DEFAULT 0.0,
            eval_result TEXT DEFAULT '',
            eval_rounds INTEGER DEFAULT 0,
            eval_score INTEGER DEFAULT 0,
            eval_cost_usd REAL DEFAULT 0.0,
            route TEXT DEFAULT '',
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_name);
        CREATE INDEX IF NOT EXISTS idx_tasks_dispatched ON tasks(dispatched_at);

        CREATE TABLE IF NOT EXISTS cost_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            cost_usd REAL NOT NULL,
            logged_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            log_size INTEGER DEFAULT 0,
            pid_alive BOOLEAN DEFAULT 1,
            checked_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );
    """)
    db.close()

    # Migrate existing databases: add eval columns if missing
    db = get_db()
    for col, coltype, default in [
        ("eval_result", "TEXT", "''"),
        ("eval_rounds", "INTEGER", "0"),
        ("eval_score", "INTEGER", "0"),
        ("eval_cost_usd", "REAL", "0.0"),
        ("route", "TEXT", "''"),
    ]:
        try:
            db.execute(f"ALTER TABLE tasks ADD COLUMN {col} {coltype} DEFAULT {default}")
        except Exception:
            pass  # Column already exists
    db.commit()
    db.close()

    print(f"Database initialized at {DB_PATH}", file=sys.stderr)


def import_json():
    """Import existing JSON task manifests into SQLite."""
    if not TASKS_DIR.exists():
        print("No tasks directory found.", file=sys.stderr)
        return

    db = get_db()
    imported = 0
    skipped = 0

    for f in sorted(TASKS_DIR.glob("*.json")):
        try:
            d = json.load(open(f))
            task_id = d.get("id", f.stem)

            # Check if already exists — sync status if JSON has terminal state
            existing = db.execute("SELECT id, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if existing:
                json_status = d.get("status", "queued")
                db_status = existing["status"]
                terminal = {"failed", "completed", "dismissed", "merged", "cancelled"}
                non_terminal = {"queued", "running", "dispatched"}
                # Update DB if: JSON is terminal and DB isn't, OR statuses differ
                # and JSON is the more authoritative terminal state
                if (json_status in terminal and db_status in non_terminal) or \
                   (json_status != db_status and json_status in terminal):
                    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    db.execute(
                        "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                        (json_status, now, task_id)
                    )
                    imported += 1  # count as update
                else:
                    skipped += 1
                continue

            # Read prompt from .prompt file if referenced
            prompt = d.get("prompt", "")
            prompt_file = d.get("prompt_file", "")
            if not prompt and prompt_file:
                prompt_path = Path(prompt_file) if prompt_file.startswith("/") else TASKS_DIR / prompt_file
                if prompt_path.exists():
                    prompt = prompt_path.read_text()

            db.execute("""
                INSERT INTO tasks (
                    id, slug, branch, project_name, project_path, subdir,
                    status, prompt, prompt_file, budget_usd, max_turns,
                    permission_mode, tmux_session, base_branch, priority,
                    depends_on, group_name, retry_count, max_retries,
                    merged_from, dispatched_at, started_at, finished_at,
                    pr_url, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                d.get("slug", ""),
                d.get("branch", ""),
                d.get("project_name", d.get("project", "")),
                d.get("project_path", ""),
                d.get("subdir", ""),
                d.get("status", "queued"),
                prompt,
                prompt_file,
                d.get("budget_usd", 5.0),
                d.get("max_turns", 200),
                d.get("permission_mode", "dangerously-skip-permissions"),
                d.get("tmux_session", ""),
                d.get("base_branch", "main"),
                d.get("priority", 0),
                json.dumps(d.get("depends_on", [])),
                d.get("group", ""),
                d.get("retry_count", 0),
                d.get("max_retries", 3),
                json.dumps(d.get("merged_from", [])),
                d.get("dispatched_at", ""),
                d.get("started_at", ""),
                d.get("finished_at", ""),
                d.get("pr_url", ""),
                d.get("error_message", ""),
            ))
            imported += 1
        except Exception as e:
            print(f"  Error importing {f.name}: {e}", file=sys.stderr)

    db.commit()
    db.close()
    print(f"Imported {imported} tasks, skipped {skipped} existing.", file=sys.stderr)


def claim_task(blocked_projects=None):
    """
    Atomically claim the next queued task.
    Returns task dict or None if no tasks available.

    This is the critical operation that JSON files cannot do atomically.
    BEGIN IMMEDIATE acquires a write lock upfront, preventing two daemons
    from claiming the same task.
    """
    if blocked_projects is None:
        blocked_projects = set()

    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        db.execute("BEGIN IMMEDIATE")

        # Get projects that already have running tasks
        running_projects = {
            row["project_name"]
            for row in db.execute(
                "SELECT DISTINCT project_name FROM tasks WHERE status = 'running'"
            ).fetchall()
        }
        all_blocked = running_projects | blocked_projects

        # Build exclusion clause
        if all_blocked:
            placeholders = ",".join("?" for _ in all_blocked)
            query = f"""
                SELECT * FROM tasks
                WHERE status = 'queued'
                AND project_name NOT IN ({placeholders})
                ORDER BY priority DESC, dispatched_at ASC
                LIMIT 1
            """
            task = db.execute(query, list(all_blocked)).fetchone()
        else:
            task = db.execute("""
                SELECT * FROM tasks
                WHERE status = 'queued'
                ORDER BY priority DESC, dispatched_at ASC
                LIMIT 1
            """).fetchone()

        if not task:
            db.execute("COMMIT")
            db.close()
            return None

        # Check dependencies
        depends_on = json.loads(task["depends_on"] or "[]")
        if depends_on:
            completed = {
                row["slug"]
                for row in db.execute(
                    "SELECT slug FROM tasks WHERE status IN ('completed', 'merged')"
                ).fetchall()
            }
            completed_ids = {
                row["id"]
                for row in db.execute(
                    "SELECT id FROM tasks WHERE status IN ('completed', 'merged')"
                ).fetchall()
            }
            for dep in depends_on:
                if dep not in completed and dep not in completed_ids:
                    # Dependencies not met, skip this task
                    db.execute("COMMIT")
                    db.close()
                    return None

        # Claim it
        db.execute("""
            UPDATE tasks
            SET status = 'running', started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
        """, (now, now, task["id"]))

        db.execute("COMMIT")
        result = dict(task)
        db.close()
        return result

    except Exception as e:
        db.execute("ROLLBACK")
        db.close()
        raise e


def update_status(task_id, status, **kwargs):
    """Update task status with optional extra fields."""
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sets = ["status = ?", "updated_at = ?"]
    vals = [status, now]

    if status in ("completed", "failed"):
        sets.append("finished_at = ?")
        vals.append(now)

    for key, val in kwargs.items():
        if key in ("pr_url", "error_message", "pid", "pgid", "cost_usd",
                   "eval_result", "eval_rounds", "eval_score", "eval_cost_usd",
                   "route"):
            sets.append(f"{key} = ?")
            vals.append(val)

    vals.append(task_id)
    db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", vals)
    db.commit()
    db.close()


def record_heartbeat(task_id, log_size=0, pid_alive=True):
    """Record a heartbeat for a running task."""
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    db.execute("""
        INSERT INTO heartbeats (task_id, log_size, pid_alive, checked_at)
        VALUES (?, ?, ?, ?)
    """, (task_id, log_size, pid_alive, now))

    db.execute("""
        UPDATE tasks SET last_heartbeat = ?, last_log_size = ?, updated_at = ?
        WHERE id = ?
    """, (now, log_size, now, task_id))

    db.commit()
    db.close()


def _is_project_process_alive(project_name):
    """Check if a project's PID file points to a live process."""
    pidfile = Path("/tmp/fleet-running") / f"{project_name}.pid"
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError, PermissionError, OSError):
        return False


def find_stuck(minutes=10):
    """
    Find tasks that appear stuck.
    A task is stuck if:
    1. Status is 'running'
    2. No heartbeat in the last N minutes, OR
    3. Log size hasn't changed between last two heartbeats
    4. AND the project's PID file process is dead (safety check)

    If the PID is alive, we trust the process is working even if
    log capture is broken (e.g., macOS script -q binary output).
    """
    db = get_db(readonly=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    stuck = []

    running = db.execute(
        "SELECT * FROM tasks WHERE status = 'running'"
    ).fetchall()

    for task in running:
        reason = None

        # Safety: if the project's process is alive, skip stuck detection.
        # Log-based detection can false-positive when log capture is broken.
        if _is_project_process_alive(task["project_name"]):
            continue

        # Check heartbeat freshness
        if not task["last_heartbeat"] or task["last_heartbeat"] < cutoff:
            reason = f"no heartbeat in {minutes}m"

        # Check log growth (get last two heartbeats)
        if not reason:
            beats = db.execute("""
                SELECT log_size FROM heartbeats
                WHERE task_id = ?
                ORDER BY checked_at DESC
                LIMIT 2
            """, (task["id"],)).fetchall()

            if len(beats) >= 2 and beats[0]["log_size"] == beats[1]["log_size"]:
                if beats[0]["log_size"] > 0:  # has output but stopped growing
                    reason = f"log frozen at {beats[0]['log_size']} bytes"

        # Check if PID is dead
        if not reason:
            latest = db.execute("""
                SELECT pid_alive FROM heartbeats
                WHERE task_id = ?
                ORDER BY checked_at DESC
                LIMIT 1
            """, (task["id"],)).fetchone()
            if latest and not latest["pid_alive"]:
                reason = "process dead"

        if reason:
            stuck.append({
                "id": task["id"],
                "slug": task["slug"],
                "project": task["project_name"],
                "reason": reason,
                "last_heartbeat": task["last_heartbeat"],
                "started_at": task["started_at"],
            })

    db.close()
    return stuck


def recover_stuck(minutes=10):
    """Find stuck tasks and mark them as failed. Returns count recovered."""
    stuck = find_stuck(minutes)
    if not stuck:
        return 0
    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for s in stuck:
        db.execute("""
            UPDATE tasks SET status = 'failed', finished_at = ?, updated_at = ?,
            error_message = ? WHERE id = ? AND status = 'running'
        """, (now, now, f"Auto-recovered: {s['reason']}", s["id"]))
    db.commit()
    count = len(stuck)
    db.close()
    return count


def get_cost_today():
    """Get total cost for today's tasks."""
    db = get_db(readonly=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    row = db.execute("""
        SELECT COALESCE(SUM(cost_usd), 0) as total
        FROM tasks
        WHERE started_at LIKE ? || '%'
        AND status IN ('completed', 'merged', 'running')
    """, (today,)).fetchone()

    db.close()
    return row["total"] if row else 0.0


def get_task(task_id):
    """Get a single task by ID."""
    db = get_db(readonly=True)
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    db.close()
    return dict(task) if task else None


def list_tasks(status=None):
    """List tasks, optionally filtered by status."""
    db = get_db(readonly=True)
    if status:
        tasks = db.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY dispatched_at DESC",
            (status,),
        ).fetchall()
    else:
        tasks = db.execute(
            "SELECT * FROM tasks ORDER BY dispatched_at DESC LIMIT 50"
        ).fetchall()
    db.close()
    return [dict(t) for t in tasks]


def get_stats():
    """Get summary statistics."""
    db = get_db(readonly=True)
    counts = {}
    for row in db.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
    ).fetchall():
        counts[row["status"]] = row["cnt"]

    today_cost = get_cost_today()
    total_cost = db.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) as total FROM tasks"
    ).fetchone()["total"]

    stuck = find_stuck()

    db.close()
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "today_cost": today_cost,
        "total_cost": total_cost,
        "stuck_count": len(stuck),
    }


def count_by_status(status):
    """Count tasks with a given status."""
    db = get_db(readonly=True)
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE status = ?", (status,)
    ).fetchone()
    db.close()
    return row["cnt"] if row else 0


def claim_next_for_daemon(blocked_projects=None, max_parallel=3):
    """
    Claim the next task for the daemon, respecting:
    - Priority ordering (highest first)
    - One task per project
    - Dependency chains (depends_on must be completed)
    - Parallel limits
    Returns task dict or None.
    """
    if blocked_projects is None:
        blocked_projects = set()

    db = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        db.execute("BEGIN IMMEDIATE")

        # Get projects with running tasks
        running_projects = {
            row["project_name"]
            for row in db.execute(
                "SELECT DISTINCT project_name FROM tasks WHERE status = 'running'"
            ).fetchall()
        }

        # Check parallel limit
        running_count = len(running_projects)
        if running_count >= max_parallel:
            db.execute("COMMIT")
            db.close()
            return None

        all_blocked = running_projects | blocked_projects

        # Get all queued tasks ordered by priority DESC, then dispatched_at ASC
        if all_blocked:
            placeholders = ",".join("?" for _ in all_blocked)
            queued = db.execute(f"""
                SELECT * FROM tasks
                WHERE status = 'queued'
                AND project_name NOT IN ({placeholders})
                ORDER BY priority DESC, dispatched_at ASC
            """, list(all_blocked)).fetchall()
        else:
            queued = db.execute("""
                SELECT * FROM tasks
                WHERE status = 'queued'
                ORDER BY priority DESC, dispatched_at ASC
            """).fetchall()

        if not queued:
            db.execute("COMMIT")
            db.close()
            return None

        # Get completed task slugs/ids for dependency checking
        completed = set()
        for row in db.execute(
            "SELECT slug, id FROM tasks WHERE status IN ('completed', 'merged')"
        ).fetchall():
            completed.add(row["slug"])
            completed.add(row["id"])

        # Find first task with satisfied dependencies
        chosen = None
        for task in queued:
            depends = json.loads(task["depends_on"] or "[]")
            if depends:
                if not all(dep in completed for dep in depends):
                    continue  # Dependencies not met, skip
            chosen = task
            break

        if not chosen:
            db.execute("COMMIT")
            db.close()
            return None

        # Claim it atomically
        db.execute("""
            UPDATE tasks
            SET status = 'running', started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
        """, (now, now, chosen["id"]))

        db.execute("COMMIT")

        # Also write the .prompt file path for the daemon to read
        result = dict(chosen)

        # Ensure prompt is available (read from .prompt file if needed)
        if not result.get("prompt") and result.get("prompt_file"):
            pf = result["prompt_file"]
            prompt_path = Path(pf) if pf.startswith("/") else TASKS_DIR / pf
            if prompt_path.exists():
                result["prompt"] = prompt_path.read_text()

        db.close()
        return result

    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        db.close()
        raise e


def add_from_json(json_path):
    """Add a task from a JSON manifest file."""
    d = json.load(open(json_path))
    task_id = d.get("id", Path(json_path).stem)

    # Read prompt from .prompt file if referenced
    prompt = d.get("prompt", "")
    prompt_file = d.get("prompt_file", "")
    if not prompt and prompt_file:
        prompt_path = Path(prompt_file) if prompt_file.startswith("/") else TASKS_DIR / prompt_file
        if prompt_path.exists():
            prompt = prompt_path.read_text()

    db = get_db()
    db.execute("""
        INSERT OR REPLACE INTO tasks (
            id, slug, branch, project_name, project_path, subdir,
            status, prompt, prompt_file, budget_usd, max_turns,
            permission_mode, tmux_session, base_branch, priority,
            depends_on, group_name, retry_count, max_retries,
            dispatched_at, route
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_id,
        d.get("slug", ""),
        d.get("branch", ""),
        d.get("project_name", ""),
        d.get("project_path", ""),
        d.get("subdir", ""),
        d.get("status", "queued"),
        prompt,
        prompt_file,
        d.get("budget_usd", 5.0),
        d.get("max_turns", 200),
        d.get("permission_mode", "dangerously-skip-permissions"),
        d.get("tmux_session", ""),
        d.get("base_branch", "main"),
        d.get("priority", 0),
        json.dumps(d.get("depends_on", [])),
        d.get("group", ""),
        d.get("retry_count", 0),
        d.get("max_retries", 3),
        d.get("dispatched_at", ""),
        d.get("route", ""),
    ))
    db.commit()
    db.close()
    print(f"Added task: {task_id}", file=sys.stderr)


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    args = sys.argv[2:]

    if cmd == "init":
        init_db()

    elif cmd == "import-json":
        init_db()
        import_json()

    elif cmd == "claim":
        init_db()
        task = claim_next_for_daemon()
        if task:
            print(json.dumps(task, indent=2))
        else:
            sys.exit(1)

    elif cmd == "count" and args:
        init_db()
        print(count_by_status(args[0]))

    elif cmd == "status" and len(args) >= 2:
        task_id, status = args[0], args[1]
        extra = {}
        for a in args[2:]:
            if "=" in a:
                k, v = a.split("=", 1)
                extra[k] = v
        update_status(task_id, status, **extra)

    elif cmd == "get" and args:
        task = get_task(args[0])
        if task:
            print(json.dumps(task, indent=2))
        else:
            print(f"Task not found: {args[0]}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "list":
        status = args[0] if args else None
        tasks = list_tasks(status)
        for t in tasks:
            print(f"  [{t['status']:10s}] {t['project_name']:15s} {t['id']}")

    elif cmd == "add" and args:
        init_db()
        add_from_json(args[0])

    elif cmd == "heartbeat" and args:
        task_id = args[0]
        log_size = int(args[1]) if len(args) > 1 else 0
        pid_alive = args[2] != "0" if len(args) > 2 else True
        record_heartbeat(task_id, log_size, pid_alive)

    elif cmd == "stuck":
        minutes = 10
        for i, a in enumerate(args):
            if a == "--minutes" and i + 1 < len(args):
                minutes = int(args[i + 1])
        stuck = find_stuck(minutes)
        if stuck:
            for s in stuck:
                print(f"  STUCK: {s['slug']} ({s['project']}) — {s['reason']}")
        else:
            print("No stuck tasks.")

    elif cmd == "recover-stuck":
        minutes = 10
        for i, a in enumerate(args):
            if a == "--minutes" and i + 1 < len(args):
                minutes = int(args[i + 1])
        init_db()
        count = recover_stuck(minutes)
        print(f"Recovered {count} stuck tasks.")

    elif cmd == "cost-today":
        cost = get_cost_today()
        print(f"${cost:.2f}")

    elif cmd == "stats":
        stats = get_stats()
        print("TASK DATABASE STATS")
        for status, count in sorted(stats["counts"].items()):
            print(f"  {status:12s}: {count}")
        print(f"  {'total':12s}: {stats['total']}")
        print(f"  today cost  : ${stats['today_cost']:.2f}")
        print(f"  total cost  : ${stats['total_cost']:.2f}")
        if stats["stuck_count"]:
            print(f"  STUCK TASKS : {stats['stuck_count']}")

    else:
        print(__doc__)
        sys.exit(1)
