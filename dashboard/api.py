"""Fleet Dashboard API — Single-file FastAPI backend."""

import glob
import json
import os
import re
import subprocess
import time
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

app = FastAPI(title="Fleet Dashboard API")

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

    # completed with docs/architecture/infra → auto_mergeable
    auto_keywords = ("docs", "architecture", "infra", "doc", "readme")
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


@app.get("/api/system")
async def get_system():
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count()
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "ram_used_gb": round(mem.used / (1024**3), 1),
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "ram_percent": mem.percent,
        "uptime": get_uptime(),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/tasks")
async def get_tasks():
    tasks = []
    if not TASKS_DIR.exists():
        return tasks
    for f in sorted(TASKS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            tasks.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return tasks


@app.get("/api/review")
async def get_review(category: Optional[str] = Query(None)):
    """Get review queue items, optionally filtered by review_category."""
    items = []
    if not REVIEW_DIR.exists():
        return items
    for f in sorted(REVIEW_DIR.glob("*.md"), reverse=True):
        try:
            text = f.read_text()
            meta, body = parse_frontmatter(text)
            # Compute review_category
            cat = infer_review_category(meta, f.name)
            # Filter by category if requested
            if category and cat != category:
                continue
            # Try to load associated summary
            summary_text = ""
            task_id = meta.get("task_id", "")
            summary_path = LOGS_DIR / f"{task_id}.summary.md"
            if summary_path.exists():
                summary_text = summary_path.read_text()
            # Get branch from task manifest
            branch = ""
            task_file = TASKS_DIR / f"{task_id}.json"
            if task_file.exists():
                try:
                    task_data = json.loads(task_file.read_text())
                    branch = task_data.get("branch", "")
                except (json.JSONDecodeError, OSError):
                    pass
            items.append({
                "filename": f.name,
                "meta": meta,
                "body": body,
                "summary": summary_text,
                "review_category": cat,
                "reason": review_reason(meta, cat, f.name),
                "branch": branch,
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
            # Check if port is listening
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr.port == svc["port"] and conn.status == "LISTEN":
                    status = "up"
                    break
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
            ["tmux", "has-session", "-t", "health-checker"],
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
    # Read from notifications.log if it exists
    notif_log = LOGS_DIR / "notifications.log"
    if notif_log.exists():
        try:
            text = notif_log.read_text()
            for line in text.strip().split("\n"):
                if not line.strip():
                    continue
                # Try to parse JSON log entries
                try:
                    entry = json.loads(line)
                    notifications.append(entry)
                except json.JSONDecodeError:
                    # Parse plain text log lines: [timestamp] subject | task_id
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
        except OSError:
            pass

    # Also scan task manifests for notified_at
    if TASKS_DIR.exists():
        for f in sorted(TASKS_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                notified_at = data.get("notified_at")
                if notified_at:
                    # Avoid duplicate if already in log
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

    # Sort by timestamp descending
    notifications.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
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


@app.post("/api/action")
async def submit_action(action: ActionRequest):
    """Submit an action (merge, skip, fix, queue)."""
    REPLY_ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    action_file = REPLY_ACTIONS_DIR / f"{ts}-{action.type}-{action.task_slug}.json"
    action_data = {
        "type": action.type,
        "task_slug": action.task_slug,
        "description": action.description,
        "created_at": datetime.now().isoformat(),
    }

    if action.type == "skip":
        # Archive the review queue item
        for f in REVIEW_DIR.glob(f"*{action.task_slug}*"):
            archive_dir = REVIEW_DIR / "archived"
            archive_dir.mkdir(exist_ok=True)
            f.rename(archive_dir / f.name)
            action_data["archived"] = f.name

    action_file.write_text(json.dumps(action_data, indent=2))
    return {"status": "ok", "file": str(action_file)}


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
