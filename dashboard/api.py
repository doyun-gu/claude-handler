"""Fleet Dashboard API — single-file FastAPI backend serving JSON + static files."""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Fleet Dashboard API")

FLEET_DIR = Path.home() / ".claude-fleet"
TASKS_DIR = FLEET_DIR / "tasks"
REVIEW_DIR = FLEET_DIR / "review-queue"
PROJECTS_FILE = FLEET_DIR / "projects.json"
REPLY_ACTIONS_DIR = FLEET_DIR / "reply-actions"
LOGS_DIR = FLEET_DIR / "logs"
STATIC_DIR = Path(__file__).parent


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_json(path: Path) -> Optional[Union[dict, list]]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-ish frontmatter from markdown. Returns (meta, body)."""
    meta = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = parts[2].strip()
    return meta, body


def _run(cmd: list[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _count_lines(path: str) -> dict:
    """Count lines of code by language, excluding node_modules/.venv/build."""
    exts = {
        ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
        ".js": "JavaScript", ".jsx": "JavaScript",
        ".cpp": "C++", ".c": "C", ".h": "C/C++ Header",
        ".css": "CSS", ".html": "HTML", ".sh": "Shell",
        ".md": "Markdown", ".rs": "Rust", ".go": "Go",
    }
    skip = {"node_modules", ".venv", "build", "dist", ".next", "__pycache__", ".git"}
    counts = {}
    total = 0
    p = Path(path)
    if not p.exists():
        return {"total": 0, "by_language": {}}
    for f in p.rglob("*"):
        if any(s in f.parts for s in skip):
            continue
        if f.suffix in exts and f.is_file():
            try:
                n = len(f.read_text(errors="ignore").splitlines())
                lang = exts[f.suffix]
                counts[lang] = counts.get(lang, 0) + n
                total += n
            except Exception:
                pass
    return {"total": total, "by_language": counts}


# ── System Metrics ───────────────────────────────────────────────────────────


@app.get("/api/system")
async def system_metrics():
    # CPU usage
    cpu = _run(["sysctl", "-n", "hw.ncpu"])
    cpu_pct_raw = _run(["bash", "-c", "ps -A -o %cpu | awk '{s+=$1} END {printf \"%.1f\", s}'"])
    # Normalize: ps reports per-core percentages summed, divide by core count
    n_cores = int(cpu) if cpu else 1
    cpu_pct = str(round(float(cpu_pct_raw) / n_cores, 1)) if cpu_pct_raw else "0"

    # Memory
    mem_total = _run(["sysctl", "-n", "hw.memsize"])
    vm_stat = _run(["vm_stat"])
    pages_free = pages_active = pages_inactive = pages_wired = pages_speculative = 0
    for line in vm_stat.splitlines():
        if "Pages free" in line:
            pages_free = int(re.search(r"(\d+)", line.split(":")[1]).group())
        elif "Pages active" in line:
            pages_active = int(re.search(r"(\d+)", line.split(":")[1]).group())
        elif "Pages inactive" in line:
            pages_inactive = int(re.search(r"(\d+)", line.split(":")[1]).group())
        elif "Pages wired" in line:
            pages_wired = int(re.search(r"(\d+)", line.split(":")[1]).group())
        elif "Pages speculative" in line:
            pages_speculative = int(re.search(r"(\d+)", line.split(":")[1]).group())

    page_size = 16384  # Apple Silicon default
    total_bytes = int(mem_total) if mem_total else 0
    total_gb = total_bytes / (1024 ** 3)
    used_pages = pages_active + pages_wired + pages_speculative
    used_gb = (used_pages * page_size) / (1024 ** 3)
    mem_pct = (used_gb / total_gb * 100) if total_gb else 0

    # Uptime
    boot_raw = _run(["sysctl", "-n", "kern.boottime"])
    boot_ts = 0
    m = re.search(r"sec = (\d+)", boot_raw)
    if m:
        boot_ts = int(m.group(1))
    uptime_secs = int(time.time()) - boot_ts if boot_ts else 0
    days = uptime_secs // 86400
    hours = (uptime_secs % 86400) // 3600
    uptime_str = f"{days}d {hours}h" if days else f"{hours}h {(uptime_secs % 3600) // 60}m"

    return {
        "cpu_cores": int(cpu) if cpu else 0,
        "cpu_percent": float(cpu_pct) if cpu_pct else 0,
        "ram_total_gb": round(total_gb, 1),
        "ram_used_gb": round(used_gb, 1),
        "ram_percent": round(mem_pct, 1),
        "uptime": uptime_str,
        "uptime_seconds": uptime_secs,
    }


# ── Tasks ────────────────────────────────────────────────────────────────────


@app.get("/api/tasks")
async def list_tasks():
    tasks = []
    if TASKS_DIR.exists():
        for f in sorted(TASKS_DIR.glob("*.json"), reverse=True):
            data = _read_json(f)
            if data:
                # Calculate duration
                started = data.get("started_at", "")
                finished = data.get("finished_at", "")
                if started and finished and data.get("status") in ("completed", "failed"):
                    try:
                        t1 = datetime.fromisoformat(started.replace("Z", "+00:00"))
                        t2 = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                        mins = int((t2 - t1).total_seconds() / 60)
                        data["duration_min"] = max(mins, 1)
                    except Exception:
                        pass
                elif started and data.get("status") == "running":
                    try:
                        t1 = datetime.fromisoformat(started.replace("Z", "+00:00"))
                        mins = int((datetime.now(timezone.utc) - t1).total_seconds() / 60)
                        data["duration_min"] = max(mins, 0)
                    except Exception:
                        pass
                tasks.append(data)
    return tasks


# ── Review Queue ─────────────────────────────────────────────────────────────


@app.get("/api/review")
async def review_queue():
    items = []
    if REVIEW_DIR.exists():
        for f in sorted(REVIEW_DIR.glob("*.md")):
            if f.name == "archived":
                continue
            text = f.read_text()
            meta, body = _parse_frontmatter(text)
            items.append({
                "filename": f.name,
                "task_id": meta.get("task_id", f.stem),
                "project": meta.get("project", ""),
                "type": meta.get("type", "unknown"),
                "priority": meta.get("priority", "normal"),
                "created_at": meta.get("created_at", ""),
                "body": body,
            })
    # Also check archived
    archived_dir = REVIEW_DIR / "archived"
    if archived_dir.exists():
        for f in sorted(archived_dir.glob("*.md"), reverse=True)[:10]:
            text = f.read_text()
            meta, body = _parse_frontmatter(text)
            items.append({
                "filename": f"archived/{f.name}",
                "task_id": meta.get("task_id", f.stem),
                "project": meta.get("project", ""),
                "type": meta.get("type", "unknown"),
                "priority": meta.get("priority", "normal"),
                "created_at": meta.get("created_at", ""),
                "body": body,
                "archived": True,
            })
    return items


# ── Projects ─────────────────────────────────────────────────────────────────


@app.get("/api/projects")
async def list_projects():
    data = _read_json(PROJECTS_FILE)
    if not data or "projects" not in data:
        return []
    projects = data["projects"]
    for p in projects:
        path = p.get("path", "")
        if path and Path(path).exists():
            metrics = _count_lines(path)
            p["lines"] = metrics["total"]
            p["languages"] = metrics["by_language"]
            # Git commits this week
            commits = _run([
                "git", "-C", path, "log", "--oneline",
                "--since=7 days ago", "--format=%h"
            ])
            p["commits_week"] = len(commits.splitlines()) if commits else 0
            # Current branch
            branch = _run(["git", "-C", path, "branch", "--show-current"])
            p["branch"] = branch
        else:
            p["lines"] = 0
            p["languages"] = {}
            p["commits_week"] = 0
            p["branch"] = ""
    return projects


# ── Services ─────────────────────────────────────────────────────────────────


@app.get("/api/services")
async def check_services():
    services = [
        {"name": "Demo", "port": 3001, "url": "http://localhost:3001"},
        {"name": "Preview", "port": 3002, "url": "http://localhost:3002"},
        {"name": "Dashboard", "port": 3003, "url": "http://localhost:3003"},
        {"name": "API", "port": 8000, "url": "http://localhost:8000"},
    ]
    import urllib.request
    for svc in services:
        try:
            req = urllib.request.urlopen(svc["url"], timeout=2)
            svc["status"] = req.getcode()
            svc["healthy"] = svc["status"] == 200
        except Exception:
            svc["status"] = None
            svc["healthy"] = False

    # Check daemon
    daemon_running = bool(_run(["pgrep", "-f", "worker-daemon"]))
    queued = 0
    running = 0
    if TASKS_DIR.exists():
        for f in TASKS_DIR.glob("*.json"):
            d = _read_json(f)
            if d:
                if d.get("status") == "queued":
                    queued += 1
                elif d.get("status") == "running":
                    running += 1
    services.append({
        "name": "Daemon",
        "port": None,
        "url": None,
        "status": "running" if daemon_running else "stopped",
        "healthy": daemon_running,
        "queued": queued,
        "running": running,
    })

    return services


# ── Debug / Bug Detection ────────────────────────────────────────────────────


@app.get("/api/debug")
async def debug_bugs():
    """Parse DEBUG_DETECTOR.md files from projects for bug entries."""
    bugs = []
    data = _read_json(PROJECTS_FILE)
    if not data:
        return bugs
    for proj in data.get("projects", []):
        path = Path(proj.get("path", ""))
        debug_file = path / "DEBUG_DETECTOR.md"
        if not debug_file.exists():
            # Also check .context/
            debug_file = path / ".context" / "DEBUG_DETECTOR.md"
        if not debug_file.exists():
            continue
        text = debug_file.read_text()
        # Parse bug entries — format: ## Bug Title\n...details...\nStatus: X
        sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
        for section in sections:
            if not section.strip() or not section.startswith("## "):
                continue
            title_line = section.split("\n")[0].replace("## ", "").strip()
            body = "\n".join(section.split("\n")[1:]).strip()

            # Extract status
            status = "NEW"
            status_match = re.search(r"Status:\s*(\w+)", body, re.IGNORECASE)
            if status_match:
                s = status_match.group(1).upper()
                if s in ("FIXED", "RESOLVED"):
                    status = "FIXED"
                elif s in ("KNOWN", "ACKNOWLEDGED", "WIP"):
                    status = "KNOWN"

            # Extract occurrences
            occ_match = re.search(r"Occurrences?:\s*(\d+)", body, re.IGNORECASE)
            occurrences = int(occ_match.group(1)) if occ_match else 1

            bugs.append({
                "project": proj["name"],
                "title": title_line,
                "body": body,
                "status": status,
                "occurrences": occurrences,
            })
    return bugs


# ── Logs ─────────────────────────────────────────────────────────────────────


@app.get("/api/logs")
async def get_logs(task_id: Optional[str] = None, lines: int = 100):
    """Return recent log entries. Optionally filter by task_id."""
    logs = []
    if LOGS_DIR.exists():
        # Get summary files
        pattern = f"{task_id}*" if task_id else "*.summary.md"
        for f in sorted(LOGS_DIR.glob(pattern), reverse=True)[:20]:
            try:
                content = f.read_text()
                logs.append({
                    "filename": f.name,
                    "task_id": f.stem.replace(".summary", ""),
                    "type": "summary" if "summary" in f.name else "log",
                    "content": content[:5000],  # Cap at 5k chars
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
            except Exception:
                pass
    return logs


# ── Roles / Agents ───────────────────────────────────────────────────────────


@app.get("/api/roles")
async def active_roles():
    roles = []
    # Worker daemon
    daemon_pid = _run(["pgrep", "-f", "worker-daemon"])
    roles.append({
        "name": "Worker Daemon",
        "icon": "hammer",
        "status": "running" if daemon_pid else "stopped",
        "detail": "",
    })
    # Find running task
    if TASKS_DIR.exists():
        for f in TASKS_DIR.glob("*.json"):
            d = _read_json(f)
            if d and d.get("status") == "running":
                roles[0]["detail"] = f"building {d.get('slug', '?')}"
                break

    # Health checker
    health_pid = _run(["pgrep", "-f", "demo-healthcheck"])
    roles.append({
        "name": "Health Checker",
        "icon": "heart",
        "status": "running" if health_pid else "stopped",
        "detail": "monitoring" if health_pid else "",
    })

    # Dashboard (self)
    roles.append({
        "name": "Dashboard",
        "icon": "chart",
        "status": "running",
        "detail": "serving :3003",
    })

    return roles


# ── Actions ──────────────────────────────────────────────────────────────────


@app.post("/api/action")
async def submit_action(request: Request):
    body = await request.json()
    action_type = body.get("type", "")
    task_slug = body.get("task_slug", "")
    description = body.get("description", "")

    REPLY_ACTIONS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    action_file = REPLY_ACTIONS_DIR / f"{ts}-{action_type}-{task_slug}.json"
    action_file.write_text(json.dumps({
        "type": action_type,
        "task_slug": task_slug,
        "description": description,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "dashboard",
    }, indent=2))

    # If action is "skip" or "archive", move the review item
    if action_type == "skip":
        # Move review queue item to archived
        archived_dir = REVIEW_DIR / "archived"
        archived_dir.mkdir(exist_ok=True)
        for f in REVIEW_DIR.glob("*.md"):
            if task_slug in f.name:
                f.rename(archived_dir / f.name)
                break

    return {"ok": True, "action_file": str(action_file)}


# ── Knowledge / Conversations ───────────────────────────────────────────────


@app.get("/api/knowledge")
async def knowledge(project: Optional[str] = None, tag: Optional[str] = None):
    """Parse tagged items from .context/conversations/ across projects."""
    items = []
    data = _read_json(PROJECTS_FILE)
    if not data:
        return items
    for proj in data.get("projects", []):
        if project and proj["name"] != project:
            continue
        ctx_dir = Path(proj.get("path", "")) / ".context" / "conversations"
        if not ctx_dir.exists():
            continue
        for f in sorted(ctx_dir.glob("*.md"), reverse=True):
            try:
                text = f.read_text()
            except Exception:
                continue
            # Parse lines with [TAG] markers
            for line in text.splitlines():
                m = re.match(r".*\[(DECISION|TASK|INSIGHT|QUESTION|BUG)]\s*(.*)", line)
                if m:
                    t = m.group(1)
                    if tag and t != tag.upper():
                        continue
                    items.append({
                        "project": proj["name"],
                        "tag": t,
                        "text": m.group(2).strip(),
                        "source": f.stem,
                        "file": str(f),
                    })
    return items


# ── Static file serving ─────────────────────────────────────────────────────

# Serve index.html at root
@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files (css, js)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3003)
