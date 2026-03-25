#!/usr/bin/env python3
"""
File Lock Registry — Conflict prevention for fleet parallel tasks.

Tracks which file paths are claimed by active tasks so the daemon can
detect overlapping work before launching. Stale locks auto-expire after
2 hours.

Usage (standalone CLI — called by worker-daemon.sh via subprocess):
  file-lock.py estimate   <project_path> <prompt>           # guess paths
  file-lock.py check      <project> <path1> [path2 ...]     # check conflicts
  file-lock.py acquire    <task_id> <project> <path1> ...    # lock paths
  file-lock.py release    <task_id>                          # unlock paths
  file-lock.py list                                          # show all locks
  file-lock.py list-json                                     # show all locks as JSON
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fnmatch import fnmatch

FLEET_DIR = Path.home() / ".claude-fleet"
LOCK_FILE = FLEET_DIR / "file-locks.json"
STALE_HOURS = 2  # auto-expire locks older than this


# ── Path estimation heuristics ────────────────────────────────

# Map keywords in prompts to likely file path patterns.
# Patterns use fnmatch-style wildcards.

PATH_HEURISTICS = [
    # Engine / solver
    (["powerflow", "power flow", "power-flow", "pf solver"],
     ["**/engine/powerflow*", "**/engine/solver*", "**/engine/__init__*"]),
    (["kron", "kron reduction"],
     ["**/engine/kron*", "**/engine/powerflow*"]),
    (["newton", "newton-raphson", "nr solver"],
     ["**/engine/newton*", "**/engine/solver*", "**/engine/powerflow*"]),
    (["mna", "modified nodal"],
     ["**/engine/mna*", "**/engine/stamp*"]),
    (["topology", "network topology", "graph"],
     ["**/engine/topology*", "**/engine/network*", "**/components/topology/*"]),
    (["bus", "ieee bus", "ieee-bus"],
     ["**/engine/bus*", "**/engine/ieee*", "**/data/ieee*"]),
    (["branch", "transmission line", "line model"],
     ["**/engine/branch*", "**/engine/line*"]),
    (["transformer"],
     ["**/engine/transformer*", "**/engine/branch*"]),
    (["simulation", "simulator", "time domain"],
     ["**/engine/simulation*", "**/engine/solver*"]),

    # API
    (["api", "endpoint", "route", "fastapi", "backend"],
     ["**/api/*", "**/api/main*", "**/routes/*", "**/server/*"]),
    (["websocket", "ws ", "sse", "server-sent"],
     ["**/api/ws*", "**/api/sse*", "**/api/stream*"]),

    # Frontend / UI
    (["component", "react", "ui ", "frontend", "tsx"],
     ["**/src/components/**/*", "**/web/src/**/*"]),
    (["page", "view", "screen"],
     ["**/src/pages/**/*", "**/src/views/**/*"]),
    (["css", "style", "tailwind", "theme"],
     ["**/src/**/*.css", "**/src/**/*.scss", "**/tailwind*"]),
    (["layout", "sidebar", "navbar", "header", "footer"],
     ["**/src/components/layout/*", "**/src/components/nav*"]),
    (["chart", "plot", "graph", "visualization", "d3"],
     ["**/src/components/chart*", "**/src/components/plot*", "**/src/components/vis*"]),

    # Config / infra
    (["docker", "container", "dockerfile"],
     ["**/Dockerfile*", "**/docker-compose*"]),
    (["ci", "github action", "workflow"],
     ["**/.github/**/*"]),
    (["config", "configuration", "settings", "env"],
     ["**/*.config.*", "**/config/*", "**/.env*"]),
    (["package.json", "dependency", "dependencies"],
     ["**/package.json", "**/package-lock.json"]),
    (["pyproject", "requirements"],
     ["**/pyproject.toml", "**/requirements*.txt", "**/setup.cfg"]),

    # Testing
    (["test", "spec", "pytest", "jest"],
     ["**/tests/**/*", "**/test/**/*", "**/__tests__/**/*", "**/*.test.*", "**/*.spec.*"]),

    # Docs
    (["readme", "documentation", "docs"],
     ["**/README*", "**/docs/**/*", "**/.context/**/*"]),
    (["claude.md", "context"],
     ["**/CLAUDE.md", "**/.context/**/*"]),
    (["changelog", "change log"],
     ["**/CHANGELOG*"]),
    (["architecture"],
     ["**/ARCHITECTURE*", "**/.context/architecture*"]),
]


def estimate_paths(project_path: str, prompt: str) -> list:
    """
    Estimate which file paths a task will touch based on keywords in the prompt.

    Returns a list of concrete file paths (resolved from glob patterns)
    plus the raw glob patterns as fallback.
    """
    prompt_lower = prompt.lower()
    matched_patterns = set()

    for keywords, patterns in PATH_HEURISTICS:
        if any(kw in prompt_lower for kw in keywords):
            matched_patterns.update(patterns)

    if not matched_patterns:
        return []

    # Resolve patterns against actual project files
    resolved = set()
    project = Path(project_path)

    for pattern in matched_patterns:
        # Strip leading **/ for Path.glob compatibility
        clean = pattern.lstrip("*").lstrip("/")
        try:
            for match in project.glob(clean):
                if match.is_file():
                    # Store relative path
                    resolved.add(str(match.relative_to(project)))
        except (OSError, ValueError):
            pass

    # Also include the raw patterns (for conflict checking against other patterns)
    # Prefix with ~ to distinguish from concrete paths
    for pat in matched_patterns:
        resolved.add(f"~{pat}")

    return sorted(resolved)


def paths_overlap(paths_a: list, paths_b: list) -> list:
    """
    Check if two path sets overlap.
    Handles both concrete paths and glob patterns (prefixed with ~).

    Returns list of overlapping paths/patterns.
    """
    overlaps = []

    concrete_a = {p for p in paths_a if not p.startswith("~")}
    concrete_b = {p for p in paths_b if not p.startswith("~")}
    patterns_a = {p[1:] for p in paths_a if p.startswith("~")}
    patterns_b = {p[1:] for p in paths_b if p.startswith("~")}

    # Direct concrete path overlap
    direct = concrete_a & concrete_b
    overlaps.extend(sorted(direct))

    # Concrete path vs pattern
    for path in concrete_a:
        for pat in patterns_b:
            if fnmatch(path, pat):
                overlaps.append(path)
                break
    for path in concrete_b:
        for pat in patterns_a:
            if fnmatch(path, pat):
                overlaps.append(path)
                break

    # Pattern vs pattern — check if they share common structure
    # (e.g., **/engine/* vs **/engine/powerflow*)
    for pat_a in patterns_a:
        for pat_b in patterns_b:
            # Crude overlap: check if one pattern is a prefix/subset of another
            base_a = pat_a.replace("**", "").replace("*", "").strip("/")
            base_b = pat_b.replace("**", "").replace("*", "").strip("/")
            if base_a and base_b:
                if base_a in base_b or base_b in base_a:
                    overlaps.append(f"~{pat_a} <> ~{pat_b}")

    return list(dict.fromkeys(overlaps))  # deduplicate preserving order


# ── Lock file I/O ────────────────────────────────────────────

def load_locks() -> dict:
    """Load the lock registry, returning empty if missing or corrupt."""
    if not LOCK_FILE.exists():
        return {"locks": []}
    try:
        data = json.loads(LOCK_FILE.read_text())
        if "locks" not in data:
            data["locks"] = []
        return data
    except (json.JSONDecodeError, OSError):
        return {"locks": []}


def save_locks(data: dict):
    """Write the lock registry atomically."""
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LOCK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(LOCK_FILE)


def prune_stale(data: dict) -> dict:
    """Remove locks older than STALE_HOURS."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=STALE_HOURS)
    alive = []
    for lock in data["locks"]:
        try:
            locked_at = datetime.fromisoformat(
                lock["locked_at"].replace("Z", "+00:00"))
            if locked_at > cutoff:
                alive.append(lock)
        except (KeyError, ValueError):
            # Malformed lock — drop it
            pass
    data["locks"] = alive
    return data


# ── CLI commands ─────────────────────────────────────────────

def cmd_estimate(args):
    """Estimate file paths a task will touch.

    Usage: file-lock.py estimate <project_path> <prompt>
    Prints one path per line to stdout.
    """
    if len(args) < 2:
        print("Usage: file-lock.py estimate <project_path> <prompt>",
              file=sys.stderr)
        sys.exit(1)

    project_path = args[0]
    prompt = " ".join(args[1:])
    paths = estimate_paths(project_path, prompt)

    for p in paths:
        print(p)

    if not paths:
        sys.exit(1)


def cmd_check(args):
    """Check if paths conflict with existing locks.

    Usage: file-lock.py check <project> <path1> [path2 ...]
    Prints conflicting task_id(s) to stdout, one per line.
    Exits 0 if conflict found, 1 if no conflict.
    """
    if len(args) < 2:
        print("Usage: file-lock.py check <project> <path1> [path2 ...]",
              file=sys.stderr)
        sys.exit(2)

    project = args[0]
    check_paths = args[1:]

    data = prune_stale(load_locks())
    save_locks(data)  # persist pruning

    found_conflicts = []
    for lock in data["locks"]:
        if lock["project"] != project:
            continue
        overlaps = paths_overlap(check_paths, lock.get("paths", []))
        if overlaps:
            found_conflicts.append({
                "task_id": lock["task_id"],
                "overlapping": overlaps[:5],  # limit output
            })

    if found_conflicts:
        for c in found_conflicts:
            overlap_str = ", ".join(c["overlapping"][:3])
            print(f"{c['task_id']}  ({overlap_str})")
        sys.exit(0)  # 0 = conflicts found
    else:
        sys.exit(1)  # 1 = no conflicts


def cmd_acquire(args):
    """Acquire locks for a task.

    Usage: file-lock.py acquire <task_id> <project> <path1> [path2 ...]
    """
    if len(args) < 3:
        print("Usage: file-lock.py acquire <task_id> <project> <path1> ...",
              file=sys.stderr)
        sys.exit(1)

    task_id = args[0]
    project = args[1]
    paths = args[2:]

    data = prune_stale(load_locks())

    # Remove any existing locks for this task_id (re-acquire)
    data["locks"] = [l for l in data["locks"] if l["task_id"] != task_id]

    data["locks"].append({
        "task_id": task_id,
        "project": project,
        "paths": paths,
        "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    save_locks(data)
    print(f"Acquired {len(paths)} lock(s) for {task_id}")


def cmd_release(args):
    """Release locks for a task.

    Usage: file-lock.py release <task_id>
    """
    if not args:
        print("Usage: file-lock.py release <task_id>", file=sys.stderr)
        sys.exit(1)

    task_id = args[0]
    data = load_locks()
    before = len(data["locks"])
    data["locks"] = [l for l in data["locks"] if l["task_id"] != task_id]
    after = len(data["locks"])
    save_locks(data)

    released = before - after
    print(f"Released {released} lock(s) for {task_id}")


def cmd_list(_args):
    """Show current locks in human-readable format."""
    data = prune_stale(load_locks())
    save_locks(data)

    if not data["locks"]:
        print("No active locks.")
        return

    now = datetime.now(timezone.utc)
    for lock in data["locks"]:
        task_id = lock["task_id"]
        project = lock["project"]
        paths = lock.get("paths", [])
        locked_at = lock.get("locked_at", "?")

        # Calculate age
        age = "?"
        try:
            ts = datetime.fromisoformat(locked_at.replace("Z", "+00:00"))
            mins = int((now - ts).total_seconds() / 60)
            age = f"{mins}m ago"
        except (ValueError, TypeError):
            pass

        print(f"{task_id}  [{project}]  ({age})")
        concrete = [p for p in paths if not p.startswith("~")]
        patterns = [p for p in paths if p.startswith("~")]
        for p in concrete[:10]:
            print(f"  {p}")
        if patterns:
            print(f"  + {len(patterns)} pattern(s)")
        if len(concrete) > 10:
            print(f"  ... and {len(concrete) - 10} more")
        print()


def cmd_list_json(_args):
    """Show current locks as JSON."""
    data = prune_stale(load_locks())
    save_locks(data)
    print(json.dumps(data, indent=2))


# ── Main dispatch ────────────────────────────────────────────

COMMANDS = {
    "estimate":  cmd_estimate,
    "check":     cmd_check,
    "acquire":   cmd_acquire,
    "release":   cmd_release,
    "list":      cmd_list,
    "list-json": cmd_list_json,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    handler = COMMANDS.get(cmd)
    if handler:
        handler(sys.argv[2:])
    else:
        print(f"Usage: file-lock.py [{' | '.join(sorted(COMMANDS))}]",
              file=sys.stderr)
        sys.exit(1)
