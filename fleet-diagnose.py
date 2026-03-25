#!/usr/bin/env python3
"""
Fleet Diagnostic API — automated health checks for the worker daemon.

Detects misconfigurations, stuck tasks, process failures, sync issues,
and returns structured results with error codes for automated repair.

Usage:
  python3 fleet-diagnose.py                  # Run all checks
  python3 fleet-diagnose.py --check <name>   # Run one check
  python3 fleet-diagnose.py --json           # JSON output for automation
  python3 fleet-diagnose.py --fix            # Auto-fix what's fixable

Error Code Reference:
  FD-100  Daemon not running
  FD-101  Daemon heartbeat stale (>2 min old)
  FD-102  Daemon in crash loop
  FD-103  Daemon health degraded
  FD-110  SQLite DB missing or corrupt
  FD-111  JSON-SQLite status desync
  FD-112  Orphaned "running" tasks (no backing process)
  FD-113  Stuck tasks (no heartbeat / log frozen)
  FD-114  Queue deadlocked (all queued tasks blocked by running)
  FD-120  Claude CLI not found
  FD-121  setsid binary missing (expected on macOS)
  FD-122  stdbuf binary missing
  FD-123  gh CLI not found or not authenticated
  FD-130  PID file stale (process dead)
  FD-131  Orphaned Claude processes (no parent daemon)
  FD-132  Zombie child processes
  FD-140  Disk space low (<1GB free)
  FD-141  Log directory growing large (>1GB)
  FD-142  Too many task JSON files (>500)
  FD-150  Prompt file path has double prefix
  FD-151  Task JSON missing required fields
  FD-152  Task JSON parse error
  FD-160  Review queue has unprocessed items
  FD-161  Review queue stale (>24h old items)
  FD-170  Git repo on wrong branch (not main)
  FD-171  Git repo has unpushed commits
  FD-172  Git repo has uncommitted changes
  FD-180  tmux session missing
  FD-181  Fleet directory structure incomplete
"""

import json
import os
import subprocess
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

FLEET_DIR = Path.home() / ".claude-fleet"
DB_PATH = FLEET_DIR / "tasks.db"
TASKS_DIR = FLEET_DIR / "tasks"
LOGS_DIR = FLEET_DIR / "logs"
REVIEW_DIR = FLEET_DIR / "review-queue"
HEARTBEAT_FILE = FLEET_DIR / "daemon-heartbeat"
HEALTH_FILE = FLEET_DIR / "daemon-health.json"
CRASH_FILE = FLEET_DIR / "daemon-crashes"
ERROR_LOG = FLEET_DIR / "daemon-errors.log"
RUNNING_DIR = Path("/tmp/fleet-running")
PROJECTS_FILE = FLEET_DIR / "projects.json"

# ── Result types ─────────────────────────────────────────────

class CheckResult:
    def __init__(self, code, severity, message, details=None, fix=None):
        self.code = code
        self.severity = severity  # "critical", "warning", "info", "ok"
        self.message = message
        self.details = details or {}
        self.fix = fix  # shell command or python callable to auto-fix

    def to_dict(self):
        d = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.details:
            d["details"] = self.details
        if self.fix:
            d["fix"] = self.fix if isinstance(self.fix, str) else "auto-fixable"
        return d

    def __repr__(self):
        icon = {"critical": "XX", "warning": "!!", "info": "--", "ok": "OK"}[self.severity]
        return f"[{icon}] {self.code}: {self.message}"


def run(cmd, timeout=10):
    """Run a shell command, return (stdout, returncode)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", -1
    except Exception as e:
        return str(e), -1


# ── Individual checks ────────────────────────────────────────

def check_daemon_running():
    """FD-100: Is the daemon process alive?"""
    out, rc = run("pgrep -f 'worker-daemon.sh' | head -5")
    if rc != 0 or not out:
        return CheckResult(
            "FD-100", "critical", "Daemon not running",
            fix="tmux new-session -d -s worker-daemon 'cd ~/Developer/claude-handler && bash ./worker-daemon.sh 2>&1 | tee -a ~/.claude-fleet/logs/worker-daemon.log'"
        )
    pids = out.strip().split("\n")
    return CheckResult("FD-100", "ok", f"Daemon running ({len(pids)} processes)",
                        details={"pids": pids})


def check_daemon_heartbeat():
    """FD-101: Is the heartbeat fresh?"""
    if not HEARTBEAT_FILE.exists():
        return CheckResult("FD-101", "warning", "No heartbeat file found")

    content = HEARTBEAT_FILE.read_text()
    ts = 0
    for part in content.split():
        if part.startswith("timestamp="):
            ts = int(part.split("=")[1])
    if ts == 0:
        return CheckResult("FD-101", "warning", "Heartbeat file unreadable",
                            details={"content": content[:200]})

    age = int(time.time()) - ts
    if age > 120:
        return CheckResult("FD-101", "critical",
                            f"Heartbeat stale ({age}s old, >2min)",
                            details={"age_seconds": age, "content": content[:200]})
    return CheckResult("FD-101", "ok", f"Heartbeat fresh ({age}s ago)",
                        details={"age_seconds": age})


def check_crash_loop():
    """FD-102: Is the daemon in a crash loop?"""
    if not CRASH_FILE.exists():
        return CheckResult("FD-102", "ok", "No crash counter")

    content = CRASH_FILE.read_text()
    count = 0
    for part in content.split():
        if part.startswith("count="):
            count = int(part.split("=")[1])
    if count >= 3:
        return CheckResult("FD-102", "critical",
                            f"Crash loop detected ({count} restarts)",
                            details={"content": content},
                            fix=f"rm -f {CRASH_FILE}")
    return CheckResult("FD-102", "ok", f"Crash counter: {count}")


def check_daemon_health():
    """FD-103: Daemon self-reported health."""
    if not HEALTH_FILE.exists():
        return CheckResult("FD-103", "warning", "No health file")
    try:
        h = json.loads(HEALTH_FILE.read_text())
        if h.get("status") == "degraded":
            return CheckResult("FD-103", "warning", "Daemon reports degraded",
                                details=h)
        return CheckResult("FD-103", "ok", f"Daemon healthy (cycle {h.get('cycle', '?')})",
                            details=h)
    except Exception as e:
        return CheckResult("FD-103", "warning", f"Health file parse error: {e}")


def check_sqlite_db():
    """FD-110: Is the SQLite DB accessible and intact?"""
    if not DB_PATH.exists():
        return CheckResult("FD-110", "critical", "tasks.db not found",
                            fix="python3 ~/Developer/claude-handler/task-db.py init")
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.execute("SELECT COUNT(*) FROM tasks")
        count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        db.close()
        if integrity != "ok":
            return CheckResult("FD-110", "critical",
                                f"DB integrity check failed: {integrity}")
        return CheckResult("FD-110", "ok", f"DB ok ({count} tasks)",
                            details={"task_count": count})
    except Exception as e:
        return CheckResult("FD-110", "critical", f"DB error: {e}")


def check_json_sqlite_sync():
    """FD-111: Are JSON task files in sync with SQLite?"""
    if not DB_PATH.exists() or not TASKS_DIR.exists():
        return CheckResult("FD-111", "info", "Skipped (no DB or tasks dir)")

    mismatches = []
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.row_factory = sqlite3.Row

        for f in sorted(TASKS_DIR.glob("*.json"))[-30:]:  # check recent 30
            try:
                d = json.load(open(f))
                task_id = d.get("id", f.stem)
                json_status = d.get("status", "unknown")

                row = db.execute("SELECT status FROM tasks WHERE id = ?",
                                  (task_id,)).fetchone()
                if row:
                    db_status = row["status"]
                    if json_status != db_status:
                        mismatches.append({
                            "id": task_id,
                            "json": json_status,
                            "db": db_status,
                        })
            except Exception:
                continue
        db.close()
    except Exception as e:
        return CheckResult("FD-111", "warning", f"Sync check failed: {e}")

    if mismatches:
        return CheckResult("FD-111", "warning",
                            f"{len(mismatches)} JSON/SQLite mismatches",
                            details={"mismatches": mismatches},
                            fix="python3 ~/Developer/claude-handler/task-db.py import-json")
    return CheckResult("FD-111", "ok", "JSON and SQLite in sync")


def check_orphaned_running():
    """FD-112: Tasks marked 'running' with no backing process."""
    if not DB_PATH.exists():
        return CheckResult("FD-112", "info", "Skipped (no DB)")

    orphaned = []
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.row_factory = sqlite3.Row
        running = db.execute("SELECT id, slug, project_name FROM tasks WHERE status = 'running'").fetchall()
        db.close()

        for task in running:
            project = task["project_name"]
            pidfile = RUNNING_DIR / f"{project}.pid"
            if pidfile.exists():
                pid = pidfile.read_text().strip()
                try:
                    os.kill(int(pid), 0)
                    continue  # process alive
                except (ProcessLookupError, ValueError):
                    pass
            orphaned.append({
                "id": task["id"],
                "slug": task["slug"],
                "project": project,
            })
    except Exception as e:
        return CheckResult("FD-112", "warning", f"Check failed: {e}")

    if orphaned:
        return CheckResult("FD-112", "critical",
                            f"{len(orphaned)} orphaned running tasks",
                            details={"orphaned": orphaned},
                            fix="python3 ~/Developer/claude-handler/task-db.py recover-stuck --minutes 0")
    return CheckResult("FD-112", "ok", "No orphaned running tasks")


def check_stuck_tasks():
    """FD-113: Tasks stuck (no heartbeat or log frozen)."""
    out, rc = run("python3 ~/Developer/claude-handler/task-db.py stuck --minutes 10")
    if "No stuck tasks" in out or not out:
        return CheckResult("FD-113", "ok", "No stuck tasks")
    lines = [l.strip() for l in out.strip().split("\n") if l.strip()]
    return CheckResult("FD-113", "warning",
                        f"{len(lines)} stuck tasks detected",
                        details={"stuck": lines},
                        fix="python3 ~/Developer/claude-handler/task-db.py recover-stuck --minutes 10")


def check_queue_deadlock():
    """FD-114: All queued tasks blocked by running tasks for same project."""
    if not DB_PATH.exists():
        return CheckResult("FD-114", "info", "Skipped (no DB)")

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.row_factory = sqlite3.Row
        running_projects = {
            r["project_name"]
            for r in db.execute("SELECT DISTINCT project_name FROM tasks WHERE status = 'running'").fetchall()
        }
        queued = db.execute("SELECT id, project_name FROM tasks WHERE status = 'queued'").fetchall()
        db.close()

        if not queued:
            return CheckResult("FD-114", "ok", "No queued tasks")

        blocked = [q for q in queued if q["project_name"] in running_projects]
        if len(blocked) == len(queued) and len(queued) > 0:
            # Check if the blocking tasks are actually alive (not stuck)
            any_stuck = False
            for proj in running_projects:
                pidfile = RUNNING_DIR / f"{proj}.pid"
                if pidfile.exists():
                    try:
                        pid = int(pidfile.read_text().strip())
                        os.kill(pid, 0)  # process alive
                        continue
                    except (ProcessLookupError, ValueError):
                        any_stuck = True
                else:
                    any_stuck = True

            if any_stuck:
                return CheckResult("FD-114", "critical",
                                    f"Queue deadlocked: all {len(queued)} queued tasks blocked by dead running tasks",
                                    details={
                                        "running_projects": list(running_projects),
                                        "blocked_count": len(blocked),
                                        "total_queued": len(queued),
                                    },
                                    fix="python3 ~/Developer/claude-handler/task-db.py recover-stuck --minutes 10")
            else:
                return CheckResult("FD-114", "info",
                                    f"{len(queued)} queued tasks waiting for active tasks in {list(running_projects)}",
                                    details={
                                        "running_projects": list(running_projects),
                                        "blocked_count": len(blocked),
                                    })
        return CheckResult("FD-114", "ok",
                            f"{len(queued)} queued, {len(blocked)} blocked")
    except Exception as e:
        return CheckResult("FD-114", "warning", f"Check failed: {e}")


def check_claude_cli():
    """FD-120: Is Claude CLI available?"""
    claude_path = Path.home() / ".local" / "bin" / "claude"
    if not claude_path.exists():
        return CheckResult("FD-120", "critical", "Claude CLI not found",
                            details={"expected": str(claude_path)})
    out, rc = run(f"{claude_path} --version")
    if rc != 0:
        return CheckResult("FD-120", "critical", f"Claude CLI not executable: {out}")
    return CheckResult("FD-120", "ok", f"Claude CLI: {out}")


def check_dependencies():
    """FD-121/122/123: Required binaries."""
    results = []
    for name, code, severity in [
        ("setsid", "FD-121", "info"),  # expected missing on macOS
        ("stdbuf", "FD-122", "warning"),
        ("gh", "FD-123", "warning"),
    ]:
        out, rc = run(f"command -v {name}")
        if rc != 0:
            msg = f"{name} not found"
            if name == "setsid":
                msg += " (expected on macOS — daemon uses tee instead)"
            results.append(CheckResult(code, severity, msg))
        else:
            results.append(CheckResult(code, "ok", f"{name}: {out}"))

    # Check gh auth
    out, rc = run("gh auth status 2>&1")
    if rc != 0:
        results.append(CheckResult("FD-123", "warning", "gh not authenticated",
                                    details={"output": out[:200]}))

    return results


def check_pid_files():
    """FD-130: Stale PID files."""
    if not RUNNING_DIR.exists():
        return CheckResult("FD-130", "ok", "No PID directory")

    stale = []
    for pidfile in RUNNING_DIR.glob("*.pid"):
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
        except (ProcessLookupError, ValueError):
            stale.append({"file": pidfile.name, "pid": pidfile.read_text().strip()})
        except PermissionError:
            pass  # process exists but owned by another user

    if stale:
        return CheckResult("FD-130", "warning",
                            f"{len(stale)} stale PID files",
                            details={"stale": stale},
                            fix=f"rm -f {RUNNING_DIR}/*.pid")
    return CheckResult("FD-130", "ok", "All PID files valid")


def check_orphaned_claude():
    """FD-131: Claude processes without a daemon parent."""
    out, rc = run("pgrep -la claude 2>/dev/null")
    if rc != 0 or not out:
        return CheckResult("FD-131", "ok", "No Claude processes")

    daemon_pids_out, _ = run("pgrep -f 'worker-daemon.sh'")
    daemon_pids = set(daemon_pids_out.split()) if daemon_pids_out else set()

    orphaned = []
    for line in out.strip().split("\n"):
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        pid = parts[0]
        # Check if parent is a daemon process
        ppid_out, _ = run(f"ps -o ppid= -p {pid}")
        ppid = ppid_out.strip()
        # Walk up the tree
        is_daemon_child = False
        visited = set()
        current = ppid
        while current and current not in visited and current != "0" and current != "1":
            visited.add(current)
            if current in daemon_pids:
                is_daemon_child = True
                break
            parent_out, _ = run(f"ps -o ppid= -p {current}")
            current = parent_out.strip()
        if not is_daemon_child:
            orphaned.append({"pid": pid, "command": parts[1][:100]})

    if orphaned:
        return CheckResult("FD-131", "warning",
                            f"{len(orphaned)} orphaned Claude processes",
                            details={"orphaned": orphaned})
    return CheckResult("FD-131", "ok", "All Claude processes have daemon parent")


def check_disk_space():
    """FD-140: Disk space check."""
    import shutil
    total, used, free = shutil.disk_usage(str(Path.home()))
    free_gb = free / (1024 ** 3)
    if free_gb < 1:
        return CheckResult("FD-140", "critical",
                            f"Disk space critically low: {free_gb:.1f}GB free")
    if free_gb < 5:
        return CheckResult("FD-140", "warning",
                            f"Disk space low: {free_gb:.1f}GB free")
    return CheckResult("FD-140", "ok", f"Disk: {free_gb:.1f}GB free")


def check_log_size():
    """FD-141: Log directory size."""
    if not LOGS_DIR.exists():
        return CheckResult("FD-141", "ok", "No logs directory")
    total = sum(f.stat().st_size for f in LOGS_DIR.rglob("*") if f.is_file())
    total_mb = total / (1024 * 1024)
    if total_mb > 1024:
        return CheckResult("FD-141", "warning",
                            f"Logs directory large: {total_mb:.0f}MB",
                            fix=f"find {LOGS_DIR} -name '*.log' -mtime +7 -delete")
    return CheckResult("FD-141", "ok", f"Logs: {total_mb:.0f}MB")


def check_task_file_count():
    """FD-142: Too many task JSON files."""
    if not TASKS_DIR.exists():
        return CheckResult("FD-142", "ok", "No tasks directory")
    count = sum(1 for _ in TASKS_DIR.glob("*.json"))
    if count > 500:
        return CheckResult("FD-142", "warning",
                            f"{count} task JSON files (consider archiving old ones)")
    return CheckResult("FD-142", "ok", f"{count} task files")


def check_prompt_paths():
    """FD-150: Prompt files with double-prefix paths."""
    if not TASKS_DIR.exists():
        return CheckResult("FD-150", "info", "Skipped")

    bad = []
    for f in TASKS_DIR.glob("*.json"):
        try:
            d = json.load(open(f))
            pf = d.get("prompt_file", "")
            if pf and pf.startswith("/") and not Path(pf).exists():
                bad.append({"id": d.get("id", f.stem), "prompt_file": pf})
        except Exception:
            continue

    if bad:
        return CheckResult("FD-150", "warning",
                            f"{len(bad)} tasks with bad prompt_file paths",
                            details={"bad_paths": bad[:10]})
    return CheckResult("FD-150", "ok", "All prompt paths valid")


def check_task_manifests():
    """FD-151/152: Task JSON integrity."""
    if not TASKS_DIR.exists():
        return CheckResult("FD-151", "info", "Skipped")

    required = {"id", "project_path", "branch"}
    missing_fields = []
    parse_errors = []

    for f in list(TASKS_DIR.glob("*.json"))[-50:]:  # check recent 50
        try:
            d = json.load(open(f))
            missing = required - set(d.keys())
            if missing:
                missing_fields.append({"file": f.name, "missing": list(missing)})
        except json.JSONDecodeError as e:
            parse_errors.append({"file": f.name, "error": str(e)[:100]})

    results = []
    if parse_errors:
        results.append(CheckResult("FD-152", "warning",
                                    f"{len(parse_errors)} JSON parse errors",
                                    details={"errors": parse_errors[:5]}))
    if missing_fields:
        results.append(CheckResult("FD-151", "warning",
                                    f"{len(missing_fields)} tasks missing required fields",
                                    details={"tasks": missing_fields[:5]}))
    if not results:
        results.append(CheckResult("FD-151", "ok", "Task manifests valid"))
    return results


def check_review_queue():
    """FD-160/161: Review queue status."""
    if not REVIEW_DIR.exists():
        return [CheckResult("FD-160", "ok", "No review queue")]

    items = list(REVIEW_DIR.glob("*.md"))
    if not items:
        return [CheckResult("FD-160", "ok", "Review queue empty")]

    results = []
    results.append(CheckResult("FD-160", "info",
                                f"{len(items)} unprocessed review items",
                                details={"items": [i.name for i in items[:10]]}))

    now = time.time()
    stale = [i for i in items if (now - i.stat().st_mtime) > 86400]
    if stale:
        results.append(CheckResult("FD-161", "warning",
                                    f"{len(stale)} review items >24h old",
                                    details={"stale": [s.name for s in stale[:10]]}))
    return results


def check_git_repos():
    """FD-170/171/172: Git repo state for registered projects."""
    if not PROJECTS_FILE.exists():
        return [CheckResult("FD-170", "info", "No projects.json")]

    try:
        projects = json.load(open(PROJECTS_FILE)).get("projects", [])
    except Exception:
        return [CheckResult("FD-170", "warning", "projects.json parse error")]

    results = []
    for p in projects:
        path = p.get("path", "")
        name = p.get("name", "unknown")
        if not path or not Path(path).exists():
            continue

        # Check branch
        branch_out, _ = run(f"git -C {path} branch --show-current")
        if branch_out and branch_out != "main" and not branch_out.startswith("worker/"):
            results.append(CheckResult("FD-170", "info",
                                        f"{name}: on branch '{branch_out}' (not main)",
                                        details={"project": name, "branch": branch_out}))

        # Check unpushed
        ahead_out, _ = run(f"git -C {path} rev-list --count HEAD...origin/main 2>/dev/null")
        if ahead_out:
            parts = ahead_out.split()
            if parts and int(parts[0] if parts[0].isdigit() else 0) > 0:
                results.append(CheckResult("FD-171", "warning",
                                            f"{name}: unpushed commits",
                                            details={"project": name}))

    if not results:
        results.append(CheckResult("FD-170", "ok", "All repos on main, synced"))
    return results


def check_tmux():
    """FD-180: Required tmux sessions."""
    out, rc = run("tmux list-sessions 2>/dev/null")
    if rc != 0:
        return CheckResult("FD-180", "critical", "tmux not running or no sessions")

    sessions = {line.split(":")[0] for line in out.strip().split("\n") if line}
    expected = {"worker-daemon"}
    missing = expected - sessions

    if missing:
        return CheckResult("FD-180", "warning",
                            f"Missing tmux sessions: {missing}",
                            details={"running": list(sessions), "missing": list(missing)})
    return CheckResult("FD-180", "ok", f"tmux sessions: {', '.join(sorted(sessions))}")


def check_fleet_dirs():
    """FD-181: Fleet directory structure."""
    required = [FLEET_DIR, TASKS_DIR, LOGS_DIR, REVIEW_DIR]
    missing = [str(d) for d in required if not d.exists()]
    if missing:
        return CheckResult("FD-181", "warning",
                            f"Missing directories: {missing}",
                            fix=f"mkdir -p {' '.join(missing)}")
    return CheckResult("FD-181", "ok", "Fleet directory structure complete")


# ── Run all checks ───────────────────────────────────────────

ALL_CHECKS = [
    ("daemon", [check_daemon_running, check_daemon_heartbeat, check_crash_loop, check_daemon_health]),
    ("database", [check_sqlite_db, check_json_sqlite_sync, check_orphaned_running, check_stuck_tasks, check_queue_deadlock]),
    ("dependencies", [check_claude_cli, check_dependencies]),
    ("processes", [check_pid_files, check_orphaned_claude]),
    ("resources", [check_disk_space, check_log_size, check_task_file_count]),
    ("tasks", [check_prompt_paths, check_task_manifests]),
    ("review", [check_review_queue]),
    ("git", [check_git_repos]),
    ("infra", [check_tmux, check_fleet_dirs]),
]


def run_all_checks(check_filter=None):
    """Run all diagnostic checks. Returns list of CheckResult."""
    results = []
    for group_name, checks in ALL_CHECKS:
        if check_filter and group_name != check_filter:
            continue
        for check_fn in checks:
            try:
                result = check_fn()
                if isinstance(result, list):
                    results.extend(result)
                else:
                    results.append(result)
            except Exception as e:
                results.append(CheckResult(
                    "FD-999", "warning",
                    f"Check {check_fn.__name__} crashed: {e}"
                ))
    return results


def auto_fix(results):
    """Run auto-fixes for fixable issues."""
    fixed = 0
    for r in results:
        if r.fix and r.severity in ("critical", "warning"):
            if isinstance(r.fix, str):
                print(f"  Fixing {r.code}: {r.fix}")
                out, rc = run(r.fix)
                if rc == 0:
                    print(f"    Fixed.")
                    fixed += 1
                else:
                    print(f"    Failed: {out[:200]}")
    return fixed


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    output_json = "--json" in args
    do_fix = "--fix" in args
    check_filter = None

    for i, a in enumerate(args):
        if a == "--check" and i + 1 < len(args):
            check_filter = args[i + 1]

    results = run_all_checks(check_filter)

    if output_json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print()
        print("=" * 60)
        print("  FLEET DIAGNOSTIC REPORT")
        print("=" * 60)

        critical = [r for r in results if r.severity == "critical"]
        warnings = [r for r in results if r.severity == "warning"]
        infos = [r for r in results if r.severity == "info"]
        oks = [r for r in results if r.severity == "ok"]

        if critical:
            print(f"\n  CRITICAL ({len(critical)})")
            for r in critical:
                print(f"    [XX] {r.code}: {r.message}")
                if r.fix:
                    print(f"         Fix: {r.fix}")

        if warnings:
            print(f"\n  WARNINGS ({len(warnings)})")
            for r in warnings:
                print(f"    [!!] {r.code}: {r.message}")
                if r.fix:
                    print(f"         Fix: {r.fix}")

        if infos:
            print(f"\n  INFO ({len(infos)})")
            for r in infos:
                print(f"    [--] {r.code}: {r.message}")

        print(f"\n  PASSED ({len(oks)})")
        for r in oks:
            print(f"    [OK] {r.code}: {r.message}")

        print()
        print(f"  Summary: {len(critical)} critical, {len(warnings)} warnings, "
              f"{len(oks)} passed")
        print("=" * 60)

        if do_fix and (critical or warnings):
            print("\n  Running auto-fixes...")
            fixed = auto_fix(results)
            print(f"\n  Fixed {fixed} issues.")

    sys.exit(1 if critical else 0)
