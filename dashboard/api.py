"""Fleet Dashboard API — Single-file FastAPI backend.

Primary data store is SQLite (fleet.db). JSON files are kept as
backup/sync format for the worker daemon and other scripts.
"""

import asyncio
import glob
import json
import os
import re
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psutil
import yaml
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import get_conn, run_migration, sync_from_json, get_all_tasks, \
    get_task, update_task, get_all_backlog, get_all_events, add_event, \
    get_daily_completions, get_project_breakdown, get_queue_depth_history, \
    get_auto_heal_log, log_auto_heal, get_task_timeline, get_daily_costs, \
    get_queue_by_project, get_task_stats, get_analytics, \
    get_cumulative_completions, get_recent_completions, get_daily_throughput


async def _periodic_sync():
    """Re-sync JSON → SQLite every 30s to catch daemon writes."""
    while True:
        await asyncio.sleep(30)
        try:
            sync_from_json()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run migration on startup, periodic sync in background."""
    results = run_migration()
    total = sum(results.values())
    if total > 0:
        print(f"[db] Migrated {total} records to SQLite: {results}")
    task = asyncio.create_task(_periodic_sync())
    yield
    task.cancel()


app = FastAPI(title="Fleet Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FLEET_DIR = Path.home() / ".claude-fleet"
TASKS_DIR = FLEET_DIR / "tasks"
REVIEW_DIR = FLEET_DIR / "review-queue"
LOGS_DIR = FLEET_DIR / "logs"
PROJECTS_FILE = FLEET_DIR / "projects.json"
EVENTS_FILE = FLEET_DIR / "events.json"
REPLY_ACTIONS_DIR = FLEET_DIR / "reply-actions"
SECRETS_DIR = FLEET_DIR / "secrets"
STATIC_DIR = Path(__file__).parent


# ── Helpers ──────────────────────────────────────────────


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    body = parts[2].strip()
    return meta, body


def count_lines(path: str) -> int:
    """Count source code lines in a project, excluding deps."""
    extensions = (
        "*.py", "*.ts", "*.tsx", "*.js", "*.jsx",
        "*.cpp", "*.h", "*.c", "*.rs", "*.go",
        "*.java", "*.swift", "*.md", "*.css", "*.html",
        "*.sh", "*.sql",
    )
    excludes = {"node_modules", ".venv", "venv", ".next", "dist", "build", "__pycache__", ".git"}
    total = 0
    p = Path(path)
    if not p.exists():
        return 0
    for ext in extensions:
        for f in p.rglob(ext):
            if any(ex in f.parts for ex in excludes):
                continue
            try:
                total += sum(1 for _ in open(f, "rb"))
            except (OSError, PermissionError):
                pass
    return total


def get_uptime() -> str:
    """Human-readable system uptime."""
    boot = psutil.boot_time()
    delta = time.time() - boot
    days = int(delta // 86400)
    hours = int((delta % 86400) // 3600)
    if days > 0:
        return f"{days}d {hours}h"
    minutes = int((delta % 3600) // 60)
    return f"{hours}h {minutes}m"


def infer_review_category(meta: dict, filename: str) -> str:
    """Infer review_category from type/priority/name when not set in frontmatter."""
    if "review_category" in meta:
        return meta["review_category"]

    item_type = meta.get("type", "")
    priority = meta.get("priority", "normal")
    task_id = meta.get("task_id", filename).lower()

    # blocked or failed → action_required
    if item_type in ("blocked", "failed"):
        return "action_required"

    # decision_needed with high priority → action_required
    if item_type == "decision_needed" and priority == "high":
        return "action_required"

    # completed with UI/UX/visual/frontend in name → action_required
    ui_keywords = ("ui", "ux", "visual", "frontend", "design", "css", "style")
    if item_type == "completed" and any(kw in task_id for kw in ui_keywords):
        return "action_required"

    # completed with docs/architecture/infra/bug/fix/maintenance/sync/cleanup → auto_mergeable
    auto_keywords = (
        "docs", "architecture", "infra", "doc", "readme",
        "bug", "fix", "maintenance", "sync", "cleanup",
    )
    if item_type == "completed" and any(kw in task_id for kw in auto_keywords):
        return "auto_mergeable"

    # decision_needed with normal priority → auto_mergeable
    if item_type == "decision_needed" and priority == "normal":
        return "auto_mergeable"

    # Default: completed tasks are auto_mergeable, others action_required
    if item_type == "completed":
        return "auto_mergeable"

    return "action_required"


def review_reason(meta: dict, category: str, filename: str) -> str:
    """Generate a human-readable reason for why an item needs review."""
    item_type = meta.get("type", "")
    task_id = meta.get("task_id", filename).lower()

    if item_type == "blocked":
        return "Worker is blocked and cannot continue"
    if item_type == "failed":
        return "Task failed — check logs"

    ui_keywords = ("ui", "ux", "visual", "frontend", "design", "css", "style")
    if any(kw in task_id for kw in ui_keywords):
        return "UI changes need visual verification"

    if item_type == "decision_needed":
        priority = meta.get("priority", "normal")
        if priority == "high":
            return "High-priority decision needs your input"
        return "Worker made a decision — confirm when convenient"

    if category == "auto_mergeable":
        return "Safe to merge without deep review"

    if category == "dismissed":
        resolution = meta.get("resolution", "")
        return resolution if resolution else "Transient issue — resolved"

    return "Completed task ready for review"


# ── API Routes ───────────────────────────────────────────


def _get_machine_identity() -> dict:
    """Get machine name, chip, OS version, role from system commands and config."""
    identity: dict[str, Any] = {}

    # Hostname
    try:
        result = subprocess.run(["hostname", "-s"], capture_output=True, text=True, timeout=3)
        identity["machine_name"] = result.stdout.strip() if result.returncode == 0 else "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        identity["machine_name"] = "unknown"

    # Chip model
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=3,
        )
        identity["chip"] = result.stdout.strip() if result.returncode == 0 else "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        identity["chip"] = "unknown"

    # OS version
    try:
        name_result = subprocess.run(
            ["sw_vers", "-productName"], capture_output=True, text=True, timeout=3,
        )
        ver_result = subprocess.run(
            ["sw_vers", "-productVersion"], capture_output=True, text=True, timeout=3,
        )
        os_name = name_result.stdout.strip() if name_result.returncode == 0 else "macOS"
        os_ver = ver_result.stdout.strip() if ver_result.returncode == 0 else ""
        identity["os_version"] = f"{os_name} {os_ver}".strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        identity["os_version"] = "unknown"

    # Core count
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.ncpu"], capture_output=True, text=True, timeout=3,
        )
        identity["core_count"] = int(result.stdout.strip()) if result.returncode == 0 else 0
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        identity["core_count"] = 0

    # Machine role from machine-role.conf
    role_file = FLEET_DIR / "machine-role.conf"
    identity["role"] = "unknown"
    if role_file.exists():
        try:
            for line in role_file.read_text().splitlines():
                if line.startswith("MACHINE_ROLE="):
                    identity["role"] = line.split("=", 1)[1].strip()
                    break
        except OSError:
            pass

    return identity


# Cache machine identity (doesn't change during runtime)
_machine_identity_cache: Optional[dict] = None


def get_machine_identity() -> dict:
    global _machine_identity_cache
    if _machine_identity_cache is None:
        _machine_identity_cache = _get_machine_identity()
    return _machine_identity_cache


def _get_commander_last_seen() -> Optional[str]:
    """Check when Commander was last active (most recent task dispatch or SSH)."""
    latest: float = 0

    # Check task manifests for recent dispatches
    if TASKS_DIR.exists():
        for f in TASKS_DIR.glob("*.json"):
            try:
                mtime = f.stat().st_mtime
                if mtime > latest:
                    latest = mtime
            except OSError:
                pass

    # Check review-queue for recent actions
    if REPLY_ACTIONS_DIR.exists():
        for f in REPLY_ACTIONS_DIR.glob("*.json"):
            try:
                mtime = f.stat().st_mtime
                if mtime > latest:
                    latest = mtime
            except OSError:
                pass

    if latest == 0:
        return None

    delta = time.time() - latest
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


@app.get("/api/system")
async def get_system():
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    identity = get_machine_identity()
    return {
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "ram_used_gb": round(mem.used / (1024**3), 1),
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "ram_percent": mem.percent,
        "disk_free_gb": round(disk.free / (1024**3)),
        "disk_total_gb": round(disk.total / (1024**3)),
        "disk_percent": disk.percent,
        "uptime": get_uptime(),
        "timestamp": datetime.now().isoformat(),
        "machine_name": identity["machine_name"],
        "chip": identity["chip"],
        "os_version": identity["os_version"],
        "role": identity["role"],
        "core_count": identity["core_count"],
        "commander_last_seen": _get_commander_last_seen(),
    }


@app.get("/api/tasks")
async def get_tasks_endpoint():
    """Get all tasks from SQLite (falls back to JSON glob)."""
    tasks = get_all_tasks()
    if tasks:
        return tasks
    # Fallback: read from JSON files directly
    result = []
    if not TASKS_DIR.exists():
        return result
    for f in sorted(TASKS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            result.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return result


@app.get("/api/review")
async def get_review(category: Optional[str] = Query(None)):
    """Get review queue items, optionally filtered by review_category."""
    items = []
    if not REVIEW_DIR.exists():
        return items

    now = datetime.now()
    archive_dir = REVIEW_DIR / "archived"

    for f in sorted(REVIEW_DIR.glob("*.md"), reverse=True):
        try:
            text = f.read_text()
            meta, body = parse_frontmatter(text)
            task_id = meta.get("task_id", "")

            # ── Cross-reference with task manifest ──
            task_data = None
            task_status = ""
            branch = ""
            pr_url = ""
            project_path = ""
            task_file = TASKS_DIR / f"{task_id}.json"
            if task_file.exists():
                try:
                    task_data = json.loads(task_file.read_text())
                    task_status = task_data.get("status", "")
                    branch = task_data.get("branch", "")
                    pr_url = task_data.get("pr_url", "")
                    project_path = task_data.get("project_path", "")
                except (json.JSONDecodeError, OSError):
                    pass

            # If task is already merged, auto-archive and skip
            if task_status == "merged":
                archive_dir.mkdir(exist_ok=True)
                try:
                    f.rename(archive_dir / f.name)
                except OSError:
                    pass
                continue

            # ── Auto-archive stale items (>24h, non-critical) ──
            created_at = meta.get("created_at", "")
            if created_at:
                try:
                    created_str = created_at.replace("Z", "+00:00")
                    created = datetime.fromisoformat(created_str)
                    # Strip timezone for comparison
                    created_naive = created.replace(tzinfo=None)
                    age_hours = (now - created_naive).total_seconds() / 3600
                    if age_hours > 24 and meta.get("type") not in ("blocked", "failed"):
                        archive_dir.mkdir(exist_ok=True)
                        try:
                            f.rename(archive_dir / f.name)
                        except OSError:
                            pass
                        continue
                except (ValueError, TypeError):
                    pass

            # ── Check actual PR status via gh (for completed items) ──
            pr_status = "unknown"
            if task_status == "completed" and branch:
                pr_status = "open"  # Default for completed tasks
                repo = _find_repo_for_project(project_path) if project_path else None
                if repo:
                    try:
                        result = subprocess.run(
                            ["gh", "pr", "list", "--repo", repo, "--head", branch,
                             "--state", "all", "--json", "state",
                             "--jq", ".[0].state"],
                            capture_output=True, text=True, timeout=5,
                        )
                        gh_state = result.stdout.strip().upper()
                        if gh_state == "MERGED":
                            pr_status = "merged"
                            # Update task manifest to reflect merged state
                            if task_file.exists() and task_data:
                                task_data["status"] = "merged"
                                task_data["merged_at"] = now.isoformat()
                                task_file.write_text(json.dumps(task_data, indent=2))
                            # Archive and skip
                            archive_dir.mkdir(exist_ok=True)
                            try:
                                f.rename(archive_dir / f.name)
                            except OSError:
                                pass
                            continue
                        elif gh_state == "CLOSED":
                            pr_status = "closed"
                        elif gh_state == "OPEN":
                            pr_status = "open"
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        pass
            elif task_status == "completed" and pr_url:
                pr_status = "open"

            # ── Compute review_category ──
            cat = infer_review_category(meta, f.name)
            if category and cat != category:
                continue

            # Try to load associated summary
            summary_text = ""
            summary_path = LOGS_DIR / f"{task_id}.summary.md"
            if summary_path.exists():
                summary_text = summary_path.read_text()

            items.append({
                "filename": f.name,
                "meta": meta,
                "body": body,
                "summary": summary_text,
                "review_category": cat,
                "reason": review_reason(meta, cat, f.name),
                "branch": branch,
                "pr_status": pr_status,
            })
        except OSError:
            pass
    return items


@app.get("/api/projects")
async def get_projects():
    if not PROJECTS_FILE.exists():
        return []
    try:
        data = json.loads(PROJECTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    projects = data.get("projects", [])
    result = []
    for proj in projects:
        path = proj.get("path", "")
        info = {
            "name": proj.get("name", ""),
            "path": path,
            "repo": proj.get("repo", ""),
            "primary": proj.get("primary", False),
            "notes": proj.get("notes", ""),
            "lines": 0,  # computed lazily via /api/projects/lines
        }
        # Check for github URL
        repo = proj.get("repo", "")
        if repo:
            # Convert SSH to HTTPS for link
            if repo.startswith("git@github.com:"):
                info["github_url"] = "https://github.com/" + repo.replace("git@github.com:", "").replace(".git", "")
            elif "github.com" in repo:
                info["github_url"] = repo.replace(".git", "")
        result.append(info)
    return result


@app.get("/api/projects/lines")
async def get_project_lines():
    """Separate endpoint for line counts (slow)."""
    if not PROJECTS_FILE.exists():
        return {}
    try:
        data = json.loads(PROJECTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    counts = {}
    for proj in data.get("projects", []):
        path = proj.get("path", "")
        name = proj.get("name", "")
        if path:
            counts[name] = count_lines(path)
    return counts


@app.get("/api/services")
async def get_services():
    """Check running services by port."""
    services = []
    checks = [
        {"name": "Demo", "port": 3001, "url": "http://localhost:3001"},
        {"name": "Preview", "port": 3002, "url": "http://localhost:3002"},
        {"name": "Dashboard", "port": 3003, "url": "http://localhost:3003"},
        {"name": "API", "port": 8000, "url": "http://localhost:8000"},
    ]
    for svc in checks:
        status = "down"
        code = None
        try:
            import urllib.request
            req = urllib.request.Request(svc["url"], method="HEAD")
            resp = urllib.request.urlopen(req, timeout=2)
            code = resp.getcode()
            status = "up"
        except Exception:
            # Check if port is listening via lsof (psutil.net_connections needs root)
            try:
                result = subprocess.run(
                    ["lsof", "-i", f":{svc['port']}", "-sTCP:LISTEN", "-t"],
                    capture_output=True, text=True, timeout=3,
                )
                if result.returncode == 0 and result.stdout.strip():
                    status = "up"
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        services.append({
            "name": svc["name"],
            "port": svc["port"],
            "status": status,
            "code": code,
        })

    # Check daemon
    daemon_running = False
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", "worker-daemon"],
            capture_output=True, timeout=3,
        )
        daemon_running = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Count queued tasks
    queued = 0
    if TASKS_DIR.exists():
        for f in TASKS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("status") == "queued":
                    queued += 1
            except (json.JSONDecodeError, OSError):
                pass

    services.append({
        "name": "Daemon",
        "port": None,
        "status": "up" if daemon_running else "down",
        "code": None,
        "queued_tasks": queued,
    })

    # Check health checker
    health_running = False
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", "demo-health"],
            capture_output=True, timeout=3,
        )
        health_running = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    services.append({
        "name": "Health",
        "port": None,
        "status": "up" if health_running else "down",
        "code": None,
    })

    return services


@app.get("/api/debug")
async def get_debug():
    """Parse DEBUG_DETECTOR.md from DPSpice project."""
    bugs = []
    # Find DEBUG_DETECTOR.md
    search_paths = [
        Path.home() / "Developer" / "dynamic-phasors" / "DPSpice-com" / "DEBUG_DETECTOR.md",
        Path.home() / "Developer" / "DPSpice-com" / "DEBUG_DETECTOR.md",
    ]
    debug_file = None
    for p in search_paths:
        if p.exists():
            debug_file = p
            break

    if debug_file:
        text = debug_file.read_text()
        # Parse bug entries — they start with ## or ### headings after the header
        current_bug: dict[str, Any] | None = None
        for line in text.split("\n"):
            if line.startswith("## ") and not line.startswith("## DEBUG_DETECTOR"):
                if current_bug:
                    bugs.append(current_bug)
                title = line.lstrip("#").strip()
                # Detect status from emoji
                status = "new"
                if "\U0001f534" in title or "NEW" in title:
                    status = "new"
                elif "\U0001f7e1" in title or "KNOWN" in title:
                    status = "known"
                elif "\u2705" in title or "FIXED" in title:
                    status = "fixed"
                elif "\U0001f504" in title or "ASSIGNED" in title:
                    status = "assigned"
                # Clean title
                for emoji in ("\U0001f534", "\U0001f7e1", "\u2705", "\U0001f504"):
                    title = title.replace(emoji, "").strip()
                current_bug = {
                    "title": title,
                    "status": status,
                    "body": "",
                }
            elif current_bug is not None:
                current_bug["body"] += line + "\n"
        if current_bug:
            bugs.append(current_bug)

    # Also pull bugs from review queue
    if REVIEW_DIR.exists():
        for f in REVIEW_DIR.glob("bug-*.md"):
            try:
                text = f.read_text()
                meta, body = parse_frontmatter(text)
                bugs.append({
                    "title": meta.get("task_id", f.stem),
                    "status": "new",
                    "body": body,
                    "source": "review-queue",
                    "filename": f.name,
                    "meta": meta,
                })
            except OSError:
                pass

    return bugs


@app.get("/api/logs/{task_id}")
async def get_log(task_id: str):
    """Get log content for a task."""
    log_file = LOGS_DIR / f"{task_id}.log"
    summary_file = LOGS_DIR / f"{task_id}.summary.md"
    result: dict[str, Any] = {"task_id": task_id}
    if summary_file.exists():
        result["summary"] = summary_file.read_text()
    if log_file.exists():
        # Read last 200 lines
        text = log_file.read_text()
        lines = text.split("\n")
        result["log_tail"] = "\n".join(lines[-200:])
        result["total_lines"] = len(lines)
    return result


@app.get("/api/logs")
async def get_logs_list():
    """List available logs."""
    logs = []
    if not LOGS_DIR.exists():
        return logs
    for f in sorted(LOGS_DIR.glob("*.summary.md"), reverse=True):
        task_id = f.stem.replace(".summary", "")
        log_exists = (LOGS_DIR / f"{task_id}.log").exists()
        logs.append({
            "task_id": task_id,
            "has_log": log_exists,
            "has_summary": True,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    # Add daemon log
    daemon_log = LOGS_DIR / "daemon.log"
    if daemon_log.exists():
        logs.insert(0, {
            "task_id": "daemon",
            "has_log": True,
            "has_summary": False,
            "modified": datetime.fromtimestamp(daemon_log.stat().st_mtime).isoformat(),
        })
    return logs


# ── Notification Endpoints ───────────────────────────────


@app.get("/api/notifications")
async def get_notifications():
    """Recent notification history from logs and task manifests."""
    notifications = []
    seen_subjects = set()

    # Read from notifications.log if it exists
    notif_log = LOGS_DIR / "notifications.log"
    if notif_log.exists():
        try:
            text = notif_log.read_text()
            for line in text.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    notifications.append(entry)
                    seen_subjects.add(entry.get("subject", ""))
                except json.JSONDecodeError:
                    match = re.match(
                        r"\[([^\]]+)\]\s+(.+?)(?:\s*\|\s*(.+))?$", line
                    )
                    if match:
                        notifications.append({
                            "timestamp": match.group(1),
                            "subject": match.group(2).strip(),
                            "task_id": (match.group(3) or "").strip(),
                            "reply_received": False,
                        })
                        seen_subjects.add(match.group(2).strip())
        except OSError:
            pass

    # Scan daemon log for [notify] entries (fleet-notify.sh prints these)
    daemon_log = LOGS_DIR / "daemon.log"
    if daemon_log.exists():
        try:
            text = daemon_log.read_text()
            lines = text.split("\n")
            # Read last 500 lines to keep it fast
            for line in lines[-500:]:
                match = re.match(
                    r".*\[notify\]\s+(Email sent|FAILED):\s+(.+)$", line
                )
                if match:
                    status = match.group(1)
                    subject = match.group(2).strip()
                    if subject in seen_subjects:
                        continue
                    seen_subjects.add(subject)
                    # Extract task_id from subject if possible
                    tid_match = re.search(r"(\d{8}-\d{6}-[\w-]+)", subject)
                    notifications.append({
                        "timestamp": "",  # daemon log doesn't have iso timestamps inline
                        "subject": subject,
                        "task_id": tid_match.group(1) if tid_match else "",
                        "reply_received": False,
                        "send_status": "sent" if status == "Email sent" else "failed",
                    })
        except OSError:
            pass

    # Scan task manifests for notified_at
    if TASKS_DIR.exists():
        for f in sorted(TASKS_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                notified_at = data.get("notified_at")
                if notified_at:
                    task_id = data.get("id", f.stem)
                    if not any(n.get("task_id") == task_id for n in notifications):
                        notifications.append({
                            "timestamp": notified_at,
                            "subject": f"Task {data.get('status', 'update')}: {data.get('slug', task_id)}",
                            "task_id": task_id,
                            "reply_received": False,
                        })
            except (json.JSONDecodeError, OSError):
                pass

    # Check reply-actions for received replies
    if REPLY_ACTIONS_DIR.exists():
        reply_task_ids = set()
        for f in REPLY_ACTIONS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                slug = data.get("task_slug", "")
                if slug:
                    reply_task_ids.add(slug)
            except (json.JSONDecodeError, OSError):
                pass
        for n in notifications:
            tid = n.get("task_id", "")
            if tid and any(slug in tid for slug in reply_task_ids):
                n["reply_received"] = True

    # Sort by timestamp descending (entries without timestamp go to end)
    notifications.sort(key=lambda x: x.get("timestamp", "") or "0", reverse=True)
    return notifications


@app.get("/api/notifications/status")
async def get_notifications_status():
    """Email service health status."""
    gmail_conf = SECRETS_DIR / "gmail.conf"
    gmail_configured = gmail_conf.exists()

    # Find last notification timestamp
    last_sent = None
    notif_log = LOGS_DIR / "notifications.log"
    if notif_log.exists():
        try:
            text = notif_log.read_text()
            lines = [l for l in text.strip().split("\n") if l.strip()]
            if lines:
                last_line = lines[-1]
                try:
                    entry = json.loads(last_line)
                    last_sent = entry.get("timestamp")
                except json.JSONDecodeError:
                    match = re.match(r"\[([^\]]+)\]", last_line)
                    if match:
                        last_sent = match.group(1)
        except OSError:
            pass

    # Check if fleet-notify.sh exists
    notify_script = FLEET_DIR.parent / "Developer" / "claude-handler" / "fleet-notify.sh"
    if not notify_script.exists():
        notify_script = Path(__file__).parent.parent / "fleet-notify.sh"

    # Check reply-to-action status
    reply_enabled = REPLY_ACTIONS_DIR.exists()

    # Read notification preferences if they exist
    prefs_file = FLEET_DIR / "notification-prefs.json"
    preferences = {
        "task_completed": True,
        "task_failed": True,
        "task_blocked": True,
        "service_down": True,
    }
    if prefs_file.exists():
        try:
            preferences = json.loads(prefs_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "gmail_configured": gmail_configured,
        "last_sent": last_sent,
        "reply_to_action": reply_enabled,
        "notify_script_exists": notify_script.exists(),
        "preferences": preferences,
    }


@app.post("/api/notifications/test")
async def send_test_notification():
    """Send a test email notification."""
    notify_script = Path(__file__).parent.parent / "fleet-notify.sh"
    if not notify_script.exists():
        return {"status": "error", "message": "fleet-notify.sh not found"}

    gmail_conf = SECRETS_DIR / "gmail.conf"
    if not gmail_conf.exists():
        return {"status": "error", "message": "Gmail not configured (missing secrets/gmail.conf)"}

    try:
        result = subprocess.run(
            [str(notify_script), "test"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "FLEET_DIR": str(FLEET_DIR)},
        )
        if result.returncode == 0:
            return {"status": "ok", "message": "Test email sent"}
        return {"status": "error", "message": result.stderr or "Send failed"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Timeout sending email"}
    except FileNotFoundError:
        return {"status": "error", "message": "Cannot execute fleet-notify.sh"}


@app.post("/api/notifications/preferences")
async def update_notification_preferences(prefs: dict):
    """Update notification preferences."""
    prefs_file = FLEET_DIR / "notification-prefs.json"
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    prefs_file.write_text(json.dumps(prefs, indent=2))
    return {"status": "ok"}


# ── Action Endpoints ─────────────────────────────────────


class ActionRequest(BaseModel):
    type: str  # merge, skip, fix, queue
    task_slug: str = ""
    description: str = ""


def _find_task_manifest(task_slug: str) -> tuple[Optional[Path], Optional[dict]]:
    """Find task manifest by slug (exact or partial match)."""
    if not TASKS_DIR.exists():
        return None, None
    # Exact match first
    exact = TASKS_DIR / f"{task_slug}.json"
    if exact.exists():
        try:
            return exact, json.loads(exact.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    # Partial match
    for f in TASKS_DIR.glob("*.json"):
        if task_slug in f.stem:
            try:
                return f, json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return None, None


def _archive_review_item(task_slug: str) -> Optional[str]:
    """Move review queue item to archived/. Returns archived filename."""
    if not REVIEW_DIR.exists():
        return None
    archive_dir = REVIEW_DIR / "archived"
    archive_dir.mkdir(exist_ok=True)
    for f in REVIEW_DIR.glob("*.md"):
        if task_slug in f.name:
            f.rename(archive_dir / f.name)
            return f.name
    return None


def _find_repo_for_project(project_path: str) -> Optional[str]:
    """Find GitHub repo (owner/name) for a project path."""
    if not PROJECTS_FILE.exists():
        return None
    try:
        data = json.loads(PROJECTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    for proj in data.get("projects", []):
        if proj.get("path") == project_path:
            repo = proj.get("repo", "")
            # git@github.com:owner/name.git -> owner/name
            if repo.startswith("git@github.com:"):
                return repo.replace("git@github.com:", "").replace(".git", "")
            if "github.com/" in repo:
                parts = repo.rstrip("/").replace(".git", "").split("github.com/")
                return parts[-1] if len(parts) > 1 else None
    return None


@app.post("/api/action")
async def submit_action(action: ActionRequest):
    """Submit an action (merge, skip, fix, queue)."""
    REPLY_ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    if action.type == "merge":
        # Actually merge the PR via gh CLI
        task_file, task_data = _find_task_manifest(action.task_slug)
        if not task_data:
            return {"status": "error", "message": f"Task manifest not found for '{action.task_slug}'"}

        branch = task_data.get("branch", "")
        project_path = task_data.get("project_path", "")
        pr_url = task_data.get("pr_url", "")

        if not branch:
            return {"status": "error", "message": "No branch found in task manifest"}

        # Find the repo
        repo = _find_repo_for_project(project_path)
        if not repo:
            return {"status": "error", "message": f"Could not find GitHub repo for project at {project_path}"}

        # Find PR number from branch
        try:
            result = subprocess.run(
                ["gh", "pr", "list", "--repo", repo, "--head", branch,
                 "--json", "number", "--jq", ".[0].number"],
                capture_output=True, text=True, timeout=15,
            )
            pr_number = result.stdout.strip()
            if not pr_number:
                return {"status": "error", "message": f"No open PR found for branch '{branch}' in {repo}"}
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return {"status": "error", "message": f"Failed to find PR: {e}"}

        # Merge the PR
        try:
            result = subprocess.run(
                ["gh", "pr", "merge", pr_number, "--repo", repo,
                 "--squash", "--delete-branch"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                return {"status": "error", "message": f"Merge failed: {err}"}
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return {"status": "error", "message": f"Merge command failed: {e}"}

        # Update task manifest status
        if task_file and task_data:
            task_data["status"] = "merged"
            task_data["merged_at"] = datetime.now().isoformat()
            task_file.write_text(json.dumps(task_data, indent=2))

        # Archive the review item
        archived = _archive_review_item(action.task_slug)

        # Log the action
        action_file = REPLY_ACTIONS_DIR / f"{ts}-merge-{action.task_slug}.json"
        action_file.write_text(json.dumps({
            "type": "merge",
            "task_slug": action.task_slug,
            "pr_number": pr_number,
            "repo": repo,
            "archived": archived,
            "created_at": datetime.now().isoformat(),
        }, indent=2))

        return {"status": "ok", "message": f"PR #{pr_number} merged in {repo}", "pr_number": pr_number}

    elif action.type == "skip":
        # Archive the review queue item
        archived = _archive_review_item(action.task_slug)
        if not archived:
            return {"status": "ok", "message": "No review item found (may already be archived)"}

        action_file = REPLY_ACTIONS_DIR / f"{ts}-skip-{action.task_slug}.json"
        action_file.write_text(json.dumps({
            "type": "skip",
            "task_slug": action.task_slug,
            "archived": archived,
            "created_at": datetime.now().isoformat(),
        }, indent=2))
        return {"status": "ok", "message": f"Dismissed: {archived}"}

    elif action.type == "fix":
        # Dispatch a fix task (creates a reply-action for the daemon)
        action_file = REPLY_ACTIONS_DIR / f"{ts}-fix-{action.task_slug}.json"
        action_file.write_text(json.dumps({
            "type": "fix",
            "task_slug": action.task_slug,
            "description": action.description,
            "created_at": datetime.now().isoformat(),
        }, indent=2))
        return {"status": "ok", "message": f"Fix task queued for {action.task_slug}"}

    elif action.type == "queue":
        action_file = REPLY_ACTIONS_DIR / f"{ts}-queue-{action.task_slug}.json"
        action_file.write_text(json.dumps({
            "type": "queue",
            "task_slug": action.task_slug,
            "description": action.description,
            "created_at": datetime.now().isoformat(),
        }, indent=2))
        return {"status": "ok", "message": f"Task queued: {action.task_slug}"}

    return {"status": "error", "message": f"Unknown action type: {action.type}"}


@app.post("/api/tasks/{task_id}/redispatch")
async def redispatch_task(task_id: str):
    """Re-dispatch a failed/blocked task by creating a new queued copy."""
    task_file, task_data = _find_task_manifest(task_id)
    if not task_data:
        return {"status": "error", "message": f"Task not found: {task_id}"}
    if task_data.get("status") not in ("failed", "blocked"):
        return {"status": "error", "message": "Can only re-dispatch failed/blocked tasks"}

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    orig_id = task_data.get("id", task_id)
    m = re.match(r"^\d{8}-\d{6}-(.+)$", orig_id)
    short_slug = m.group(1) if m else orig_id
    new_id = f"{ts}-{short_slug}"

    new_task = {
        "id": new_id,
        "slug": new_id,
        "status": "queued",
        "project_name": task_data.get("project_name", ""),
        "project_path": task_data.get("project_path", ""),
        "prompt": task_data.get("prompt", ""),
        "dispatched_at": datetime.now().isoformat(),
        "branch": f"worker/{short_slug}-{ts[:8]}",
        "budget_usd": task_data.get("budget_usd", 10),
        "original_task_id": orig_id,
    }

    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    (TASKS_DIR / f"{new_id}.json").write_text(json.dumps(new_task, indent=2))
    try:
        sync_from_json()
    except Exception:
        pass

    return {"status": "ok", "message": f"Re-dispatched as {new_id}", "new_task_id": new_id}


@app.get("/api/tasks/{task_id}/progress")
async def get_task_progress(task_id: str):
    """Get tmux output for a running task."""
    task_file, task_data = _find_task_manifest(task_id)
    if not task_data or task_data.get("status") != "running":
        return {"task_id": task_id, "progress_lines": []}

    lines: list[str] = []
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", "worker-daemon", "-p", "-l", "5"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()][-3:]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return {"task_id": task_id, "progress_lines": lines}


# ── Backlog Endpoint ────────────────────────────────────


BACKLOG_FILE = FLEET_DIR / "backlog.json"


@app.get("/api/backlog")
async def get_backlog():
    """Get backlog tasks from SQLite."""
    tasks = get_all_backlog()
    if tasks:
        return tasks
    # Fallback
    if not BACKLOG_FILE.exists():
        return []
    try:
        data = json.loads(BACKLOG_FILE.read_text())
        return data.get("tasks", [])
    except (json.JSONDecodeError, OSError):
        return []


# ── Events Endpoints ───────────────────────────────────


def _compute_event_status(event: dict) -> str:
    """Compute status for an event: past, active, imminent, upcoming."""
    now = datetime.utcnow()
    try:
        start = datetime.fromisoformat(event["start"].replace("Z", "+00:00")).replace(tzinfo=None)
        end = datetime.fromisoformat(event["end"].replace("Z", "+00:00")).replace(tzinfo=None)
    except (KeyError, ValueError):
        return "upcoming"

    if now >= end:
        return "past"
    if now >= start:
        return "active"
    # Within 1 hour of start
    delta = (start - now).total_seconds()
    if delta <= 3600:
        return "imminent"
    return "upcoming"


@app.get("/api/events")
async def get_events():
    """Get events with computed status field."""
    if not EVENTS_FILE.exists():
        return []
    try:
        events = json.loads(EVENTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    for event in events:
        event["status"] = _compute_event_status(event)
    return events


class EventCreate(BaseModel):
    title: str
    start: str
    end: str
    freeze_projects: list[str] = []
    freeze_from: str = ""
    freeze_until: str = ""
    notes: str = ""


@app.post("/api/events")
async def create_event(event: EventCreate):
    """Add a new event to events.json."""
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    events = []
    if EVENTS_FILE.exists():
        try:
            events = json.loads(EVENTS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            events = []
    new_event = event.model_dump()
    # Remove empty optional fields
    if not new_event.get("freeze_from"):
        new_event.pop("freeze_from", None)
    if not new_event.get("freeze_until"):
        new_event.pop("freeze_until", None)
    if not new_event.get("notes"):
        new_event.pop("notes", None)
    if not new_event.get("freeze_projects"):
        new_event.pop("freeze_projects", None)
    events.append(new_event)
    EVENTS_FILE.write_text(json.dumps(events, indent=2) + "\n")
    return {"status": "ok", "message": f"Event '{event.title}' added"}


# ── New Dashboard Endpoints ──────────────────────────────


@app.get("/api/queue")
async def get_queue():
    """Tasks grouped by project with running/queued separation for Kanban view."""
    tasks = get_queue_by_project()
    # Group by project
    projects: dict[str, dict] = {}
    for t in tasks:
        proj = t.get("project_name") or "unknown"
        if proj not in projects:
            projects[proj] = {"project": proj, "running": None, "queued": []}
        if t["status"] == "running":
            # Calculate duration
            if t.get("started_at"):
                try:
                    start = datetime.fromisoformat(t["started_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                    elapsed = (datetime.utcnow() - start).total_seconds()
                    t["elapsed_seconds"] = int(elapsed)
                    t["elapsed_display"] = f"{int(elapsed // 60)}m" if elapsed >= 60 else f"{int(elapsed)}s"
                except (ValueError, TypeError):
                    t["elapsed_seconds"] = 0
                    t["elapsed_display"] = "--"
            projects[proj]["running"] = t
        else:
            projects[proj]["queued"].append(t)

    # Also include projects from registry that have no tasks (idle)
    if PROJECTS_FILE.exists():
        try:
            data = json.loads(PROJECTS_FILE.read_text())
            for proj in data.get("projects", []):
                name = proj.get("name", "")
                if name and name not in projects:
                    projects[name] = {"project": name, "running": None, "queued": []}
        except (json.JSONDecodeError, OSError):
            pass

    return list(projects.values())


@app.get("/api/timeline")
async def get_timeline(hours: int = Query(24)):
    """Task start/end times for the timeline chart."""
    return get_task_timeline(hours)


@app.get("/api/costs")
async def get_costs(days: int = Query(7)):
    """Daily cost breakdown by project."""
    return get_daily_costs(days)


# ── Stats Endpoints (for charts) ─────────────────────────


@app.get("/api/stats/daily")
async def get_stats_daily(days: int = Query(7)):
    """Tasks completed per day for the last N days."""
    return get_daily_completions(days)


@app.get("/api/stats/projects")
async def get_stats_projects():
    """Task count breakdown by project."""
    return get_project_breakdown()


@app.get("/api/stats/queue-depth")
async def get_stats_queue_depth(hours: int = Query(24)):
    """Queue depth over time (hourly snapshots)."""
    return get_queue_depth_history(hours)


@app.get("/api/stats/auto-heal")
async def get_stats_auto_heal(limit: int = Query(50)):
    """Recent auto-heal log entries."""
    return get_auto_heal_log(limit)


@app.get("/api/stats/task-history")
async def get_stats_task_history():
    """Accumulated task counts: today, this week, this month, by project."""
    return get_task_stats()


@app.get("/api/stats/analytics")
async def get_stats_analytics():
    """Focused analytics: avg duration, success rate, queue depth."""
    return get_analytics()


@app.get("/api/stats/cumulative")
async def get_stats_cumulative(days: int = Query(14)):
    """Cumulative task completions per day per project (for area chart)."""
    return get_cumulative_completions(days)


@app.get("/api/stats/recent-completions")
async def get_stats_recent_completions(limit: int = Query(10)):
    """Last N completed tasks with duration and time ago."""
    return get_recent_completions(limit)


@app.get("/api/stats/throughput")
async def get_stats_throughput(days: int = Query(7)):
    """Tasks completed per day (for sparkline bar chart)."""
    return get_daily_throughput(days)


# ── Git Status Endpoints ─────────────────────────────────


@app.get("/api/git-status/{project_name}")
async def get_git_status(project_name: str):
    """Get git status for a project (last commit, uncommitted changes, etc.)."""
    # Find project path
    project_path = None
    if PROJECTS_FILE.exists():
        try:
            data = json.loads(PROJECTS_FILE.read_text())
            for proj in data.get("projects", []):
                if proj.get("name", "").lower() == project_name.lower():
                    project_path = proj.get("path", "")
                    break
        except (json.JSONDecodeError, OSError):
            pass

    if not project_path:
        # Try common paths
        common = Path.home() / "Developer" / project_name
        if common.exists():
            project_path = str(common)

    if not project_path or not Path(project_path).exists():
        return {"error": f"Project '{project_name}' not found"}

    result = {"project": project_name, "path": project_path}

    # Last commit
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%H|%s|%ai|%an"],
            capture_output=True, text=True, timeout=5, cwd=project_path,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split("|", 3)
            result["last_commit"] = {
                "hash": parts[0][:8] if len(parts) > 0 else "",
                "message": parts[1] if len(parts) > 1 else "",
                "date": parts[2] if len(parts) > 2 else "",
                "author": parts[3] if len(parts) > 3 else "",
            }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Current branch
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=3, cwd=project_path,
        )
        result["branch"] = r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Uncommitted changes
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, cwd=project_path,
        )
        if r.returncode == 0:
            lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
            result["uncommitted_count"] = len(lines)
            result["has_changes"] = len(lines) > 0
        else:
            result["uncommitted_count"] = 0
            result["has_changes"] = False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        result["uncommitted_count"] = 0
        result["has_changes"] = False

    # Check if pushed (compare local HEAD to remote tracking branch)
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=3, cwd=project_path,
        )
        local_head = r.stdout.strip() if r.returncode == 0 else ""

        r = subprocess.run(
            ["git", "rev-parse", "@{u}"],
            capture_output=True, text=True, timeout=3, cwd=project_path,
        )
        remote_head = r.stdout.strip() if r.returncode == 0 else ""

        if local_head and remote_head:
            result["synced"] = local_head == remote_head
            if not result["synced"]:
                # Count commits ahead/behind
                r = subprocess.run(
                    ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
                    capture_output=True, text=True, timeout=3, cwd=project_path,
                )
                if r.returncode == 0:
                    parts = r.stdout.strip().split()
                    result["ahead"] = int(parts[0]) if len(parts) > 0 else 0
                    result["behind"] = int(parts[1]) if len(parts) > 1 else 0
        else:
            result["synced"] = None  # No upstream configured
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        result["synced"] = None

    return result


# ── Database Admin ───────────────────────────────────────


@app.post("/api/db/sync")
async def trigger_db_sync():
    """Force re-sync from JSON files to SQLite."""
    results = sync_from_json()
    return {"status": "ok", "synced": results}


@app.post("/api/db/migrate")
async def trigger_migration():
    """Force full migration from all file sources to SQLite."""
    results = run_migration()
    return {"status": "ok", "migrated": results}


# ── Static file serving ─────────────────────────────────


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/{filename:path}")
async def serve_static(filename: str):
    filepath = STATIC_DIR / filename
    if filepath.exists() and filepath.is_file():
        return FileResponse(filepath)
    return FileResponse(STATIC_DIR / "index.html")
