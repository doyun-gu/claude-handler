#!/usr/bin/env python3
"""
Smart Queue Manager for Fleet Worker Daemon.

Replaces simple FIFO scheduling with intelligent task ordering:
  - Dependency chains (depends_on)
  - Group affinity (similar tasks run back-to-back)
  - Project constraints (one task per project in parallel)
  - Auto-retry on failure (up to max_retries)
  - Dynamic reordering based on just-completed context

Usage:
  python3 queue-manager.py next [--just-completed SLUG] [--running-projects P1,P2]
  python3 queue-manager.py plan
  python3 queue-manager.py reorder
"""

import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

FLEET_DIR = Path.home() / ".claude-fleet"
TASKS_DIR = FLEET_DIR / "tasks"

# ── Keywords for auto-grouping and affinity ──────────────────

TOPIC_KEYWORDS = {
    "ui":       ["ui", "ux", "frontend", "css", "style", "design", "layout", "visual", "component", "button", "modal"],
    "engine":   ["engine", "solver", "mna", "powerflow", "newton", "ieee", "bus", "branch", "simulation"],
    "api":      ["api", "endpoint", "rest", "route", "server", "backend", "fastapi"],
    "test":     ["test", "qa", "coverage", "spec", "jest", "pytest", "verify"],
    "docs":     ["doc", "readme", "architecture", "claude.md", "context", "comment"],
    "infra":    ["deploy", "ci", "docker", "build", "config", "setup", "install", "daemon"],
    "fix":      ["fix", "bug", "crash", "error", "broken", "debug", "investigate"],
    "feature":  ["feat", "add", "implement", "build", "create", "new"],
    "refactor": ["refactor", "clean", "reorganize", "rename", "move", "simplify"],
}


@dataclass
class Task:
    id: str
    slug: str
    status: str
    project: str
    project_path: str
    prompt: str = ""
    group: str = ""
    depends_on: list = field(default_factory=list)
    priority: int = 0  # higher = run first
    retry_count: int = 0
    max_retries: int = 3
    started_at: str = ""
    finished_at: str = ""
    dispatched_at: str = ""
    file_path: str = ""
    topics: list = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str) -> "Task":
        with open(path) as f:
            d = json.load(f)
        t = cls(
            id=d["id"],
            slug=d.get("slug", "?"),
            status=d["status"],
            project=d.get("project_name", "?"),
            project_path=d.get("project_path", ""),
            prompt=d.get("prompt", ""),
            group=d.get("group", ""),
            depends_on=d.get("depends_on", []),
            priority=d.get("priority", 0),
            retry_count=d.get("retry_count", 0),
            max_retries=d.get("max_retries", 3),
            started_at=d.get("started_at", ""),
            finished_at=d.get("finished_at", ""),
            dispatched_at=d.get("dispatched_at", ""),
            file_path=str(path),
        )
        t.topics = classify_topics(t.slug, t.prompt)
        if not t.group:
            t.group = infer_group(t)
        return t


def classify_topics(slug: str, prompt: str) -> list:
    """Classify a task into topic categories based on slug and prompt."""
    text = f"{slug} {prompt}".lower()
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found.append(topic)
    return found or ["general"]


def infer_group(task: Task) -> str:
    """Infer a group name from project + primary topic."""
    primary = task.topics[0] if task.topics else "general"
    return f"{task.project}:{primary}"


def topic_affinity(topics_a: list, topics_b: list) -> float:
    """Score how related two tasks are by topic overlap. 0-1."""
    if not topics_a or not topics_b:
        return 0.0
    overlap = len(set(topics_a) & set(topics_b))
    total = len(set(topics_a) | set(topics_b))
    return overlap / total if total > 0 else 0.0


def load_all_tasks() -> list:
    """Load all task manifests."""
    tasks = []
    if not TASKS_DIR.exists():
        return tasks
    for f in sorted(TASKS_DIR.glob("*.json")):
        try:
            tasks.append(Task.from_file(str(f)))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[queue] Warning: skipping {f.name}: {e}", file=sys.stderr)
    return tasks


def get_queued(tasks: list) -> list:
    return [t for t in tasks if t.status == "queued"]


def get_running(tasks: list) -> list:
    return [t for t in tasks if t.status == "running"]


def get_completed(tasks: list) -> list:
    return [t for t in tasks if t.status in ("completed", "merged")]


def get_failed(tasks: list) -> list:
    return [t for t in tasks if t.status == "failed"]


def deps_satisfied(task: Task, tasks: list) -> bool:
    """Check if all dependencies are completed/merged."""
    if not task.depends_on:
        return True
    completed_slugs = {t.slug for t in tasks if t.status in ("completed", "merged")}
    completed_ids = {t.id for t in tasks if t.status in ("completed", "merged")}
    for dep in task.depends_on:
        if dep not in completed_slugs and dep not in completed_ids:
            return False
    return True


def running_projects(tasks: list) -> set:
    """Get set of projects that currently have a running task."""
    return {t.project for t in tasks if t.status == "running"}


def score_task(task: Task, just_completed: Optional[Task], all_tasks: list) -> float:
    """
    Score a queued task for scheduling priority.
    Higher score = run sooner.
    """
    score = 0.0

    # Base priority from manifest
    score += task.priority * 10

    # Affinity bonus: if similar to just-completed task, prefer it
    if just_completed:
        affinity = topic_affinity(task.topics, just_completed.topics)
        # Same project + high affinity = strong signal (context carryover)
        if task.project == just_completed.project:
            score += affinity * 50
        else:
            score += affinity * 20

        # Same group = explicit grouping
        if task.group == just_completed.group:
            score += 30

    # Dependency chain bonus: if this task unlocks others, run it first
    waiting_on_me = sum(1 for t in all_tasks
                        if t.status == "queued" and task.slug in t.depends_on)
    score += waiting_on_me * 15

    # Age bonus: older tasks get slight priority (prevent starvation)
    if task.dispatched_at:
        try:
            age = (datetime.now(timezone.utc) -
                   datetime.fromisoformat(task.dispatched_at.replace("Z", "+00:00")))
            score += min(age.total_seconds() / 600, 10)  # up to 10 points for age
        except (ValueError, TypeError):
            pass

    # Retry penalty: retried tasks get slight depriority
    score -= task.retry_count * 5

    return score


def pick_next(tasks: list, just_completed_slug: str = "",
              blocked_projects: set = None) -> Optional[Task]:
    """
    Pick the best next task to run.

    Args:
        tasks: All tasks
        just_completed_slug: Slug of the task that just finished (for affinity)
        blocked_projects: Projects that already have a running task
    """
    if blocked_projects is None:
        blocked_projects = running_projects(tasks)

    queued = get_queued(tasks)
    if not queued:
        return None

    # Find the just-completed task for affinity scoring
    just_completed = None
    if just_completed_slug:
        for t in tasks:
            if t.slug == just_completed_slug or t.id == just_completed_slug:
                just_completed = t
                break

    # Filter: deps satisfied and project not blocked
    eligible = [t for t in queued
                if deps_satisfied(t, tasks) and t.project not in blocked_projects]

    if not eligible:
        return None

    # Score and sort
    scored = [(score_task(t, just_completed, tasks), t) for t in eligible]
    scored.sort(key=lambda x: x[0], reverse=True)

    return scored[0][1]


def pick_all_next(tasks: list, just_completed_slug: str = "") -> list:
    """
    Pick ALL tasks that can run in parallel right now.
    Returns one task per eligible project.
    """
    blocked = running_projects(tasks)
    result = []

    while True:
        next_task = pick_next(tasks, just_completed_slug, blocked)
        if next_task is None:
            break
        result.append(next_task)
        blocked.add(next_task.project)

    return result


def should_retry(task: Task) -> bool:
    """Check if a failed task should be retried."""
    return task.status == "failed" and task.retry_count < task.max_retries


def get_retryable(tasks: list) -> list:
    """Get failed tasks that can be retried."""
    return [t for t in tasks if should_retry(t)]


def mark_for_retry(task: Task):
    """Reset a failed task to queued with incremented retry count."""
    with open(task.file_path, "r+") as f:
        d = json.load(f)
        d["status"] = "queued"
        d["retry_count"] = d.get("retry_count", 0) + 1
        d["last_failure"] = d.get("finished_at", "")
        f.seek(0)
        json.dump(d, f, indent=2)
        f.truncate()


# ── Prompt Merging ───────────────────────────────────────────
# When multiple queued tasks target the same project and group,
# merge them into a single combined task to save time.

MAX_MERGE = 4  # max tasks to merge into one
MIN_AFFINITY_TO_MERGE = 0.3  # minimum topic overlap to consider merging


def find_mergeable_groups(tasks: list) -> list:
    """
    Find groups of queued tasks that can be merged.
    Returns list of groups, each group is a list of Tasks.
    """
    queued = [t for t in get_queued(tasks) if deps_satisfied(t, tasks)]
    if len(queued) < 2:
        return []

    # Group by project
    by_project = {}
    for t in queued:
        by_project.setdefault(t.project, []).append(t)

    merge_groups = []
    for project, proj_tasks in by_project.items():
        if len(proj_tasks) < 2:
            continue

        # Within same project, find clusters by group + topic affinity
        used = set()
        for i, t1 in enumerate(proj_tasks):
            if i in used:
                continue
            group = [t1]
            used.add(i)

            for j, t2 in enumerate(proj_tasks):
                if j in used or len(group) >= MAX_MERGE:
                    continue
                # Must be same group OR high topic affinity
                same_group = t1.group and t1.group == t2.group
                affinity = topic_affinity(t1.topics, t2.topics)
                # Don't merge if one depends on the other
                circular = (t1.slug in t2.depends_on or t2.slug in t1.depends_on)

                if not circular and (same_group or affinity >= MIN_AFFINITY_TO_MERGE):
                    group.append(t2)
                    used.add(j)

            if len(group) >= 2:
                merge_groups.append(group)

    return merge_groups


def merge_tasks(group: list) -> Task:
    """
    Create a combined task from a group of mergeable tasks.
    Writes a new manifest and marks originals as 'merged_into'.
    """
    primary = group[0]  # use first task as template
    slugs = [t.slug for t in group]
    combined_slug = "combined-" + "-".join(s[:15] for s in slugs[:3])
    if len(slugs) > 3:
        combined_slug += f"-plus{len(slugs) - 3}"
    combined_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + combined_slug
    combined_branch = f"worker/{combined_slug}-{datetime.now().strftime('%Y%m%d')}"

    # Build merged prompt
    prompt_parts = [
        f"This is a COMBINED task merging {len(group)} related tasks. "
        f"Complete all of them in this single session.\n"
    ]
    for i, t in enumerate(group, 1):
        prompt_parts.append(f"\n{'='*60}")
        prompt_parts.append(f"TASK {i}/{len(group)}: {t.slug}")
        prompt_parts.append(f"{'='*60}")
        prompt_parts.append(t.prompt)
    prompt_parts.append(f"\n{'='*60}")
    prompt_parts.append("Commit after completing each sub-task. Open ONE PR for all changes.")

    combined_prompt = "\n".join(prompt_parts)

    # Write combined manifest
    combined_manifest = {
        "id": combined_id,
        "slug": combined_slug,
        "branch": combined_branch,
        "project_name": primary.project,
        "project_path": primary.project_path,
        "subdir": "",
        "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "queued",
        "base_branch": "main",
        "prompt": combined_prompt,
        "budget_usd": sum(10 for _ in group),  # sum budgets
        "permission_mode": "dangerously-skip-permissions",
        "tmux_session": f"claude-{combined_slug[:30]}",
        "group": primary.group,
        "max_retries": 3,
        "retry_count": 0,
        "merged_from": slugs,
    }

    combined_path = TASKS_DIR / f"{combined_id}.json"
    with open(combined_path, "w") as f:
        json.dump(combined_manifest, f, indent=2)

    # Mark originals as merged
    for t in group:
        with open(t.file_path, "r+") as f:
            d = json.load(f)
            d["status"] = "merged_into"
            d["merged_into"] = combined_id
            f.seek(0)
            json.dump(d, f, indent=2)
            f.truncate()

    print(f"[queue] Merged {len(group)} tasks → {combined_slug}", file=sys.stderr)
    for t in group:
        print(f"[queue]   - {t.slug}", file=sys.stderr)

    return Task.from_file(str(combined_path))


def auto_merge_queued(tasks: list) -> bool:
    """
    Check for mergeable tasks and merge them.
    Returns True if any merges were performed.
    """
    groups = find_mergeable_groups(tasks)
    if not groups:
        return False

    for group in groups:
        merge_tasks(group)

    return True


def build_execution_plan(tasks: list) -> list:
    """
    Build a full execution plan showing order and parallelism.
    Returns list of rounds, each round is a list of tasks to run in parallel.
    """
    # Simulate execution
    sim_tasks = [Task(
        id=t.id, slug=t.slug, status=t.status, project=t.project,
        project_path=t.project_path, prompt=t.prompt, group=t.group,
        depends_on=list(t.depends_on), priority=t.priority,
        retry_count=t.retry_count, max_retries=t.max_retries,
        dispatched_at=t.dispatched_at, topics=list(t.topics),
        file_path=t.file_path,
    ) for t in tasks]

    plan = []
    max_rounds = 50  # safety limit

    for _ in range(max_rounds):
        # Find all runnable tasks
        runnable = pick_all_next(sim_tasks)
        if not runnable:
            break

        plan.append(runnable)

        # Simulate completion
        for t in runnable:
            for st in sim_tasks:
                if st.id == t.id:
                    st.status = "completed"
                    break

    return plan


# ── CLI ──────────────────────────────────────────────────────

def cmd_next(args):
    """Print the file path of the next task to run."""
    tasks = load_all_tasks()

    # Auto-retry failed tasks first
    for t in get_retryable(tasks):
        mark_for_retry(t)
        print(f"[queue] Auto-retrying failed task: {t.slug} "
              f"(attempt {t.retry_count + 1}/{t.max_retries})", file=sys.stderr)

    # Auto-merge similar queued tasks
    tasks = load_all_tasks()
    if auto_merge_queued(tasks):
        tasks = load_all_tasks()  # reload after merges

    # Reload after retries/merges
    tasks = load_all_tasks()

    just_completed = ""
    running_proj = set()

    for i, arg in enumerate(args):
        if arg == "--just-completed" and i + 1 < len(args):
            just_completed = args[i + 1]
        elif arg == "--running-projects" and i + 1 < len(args):
            running_proj = set(args[i + 1].split(",")) if args[i + 1] else set()

    if not running_proj:
        running_proj = running_projects(tasks)

    next_task = pick_next(tasks, just_completed, running_proj)
    if next_task:
        print(next_task.file_path)
    else:
        sys.exit(1)  # No task available


def cmd_next_all(args):
    """Print file paths of ALL tasks that can run in parallel."""
    tasks = load_all_tasks()

    # Auto-retry
    for t in get_retryable(tasks):
        mark_for_retry(t)
        print(f"[queue] Auto-retrying: {t.slug}", file=sys.stderr)

    # Auto-merge similar queued tasks
    tasks = load_all_tasks()
    if auto_merge_queued(tasks):
        tasks = load_all_tasks()

    tasks = load_all_tasks()

    just_completed = ""
    for i, arg in enumerate(args):
        if arg == "--just-completed" and i + 1 < len(args):
            just_completed = args[i + 1]

    parallel = pick_all_next(tasks, just_completed)
    for t in parallel:
        print(t.file_path)

    if not parallel:
        sys.exit(1)


def cmd_plan(_args):
    """Show the full execution plan."""
    tasks = load_all_tasks()
    queued = get_queued(tasks)
    running = get_running(tasks)
    failed = get_retryable(tasks)

    print(f"Queued: {len(queued)}  Running: {len(running)}  Retryable: {len(failed)}")
    print()

    if failed:
        print("AUTO-RETRY:")
        for t in failed:
            print(f"  {t.slug} ({t.project}) — attempt {t.retry_count + 1}/{t.max_retries}")
        print()

    plan = build_execution_plan(tasks)
    if not plan:
        print("No queued tasks.")
        return

    print("EXECUTION PLAN:")
    for i, round_tasks in enumerate(plan):
        parallel_str = " + ".join(
            f"{t.slug} [{t.project}]" for t in round_tasks
        )
        mode = "parallel" if len(round_tasks) > 1 else "single"
        print(f"  Round {i + 1} ({mode}): {parallel_str}")

        # Show why this order
        for t in round_tasks:
            reasons = []
            if t.depends_on:
                reasons.append(f"after {', '.join(t.depends_on)}")
            if t.group:
                reasons.append(f"group={t.group}")
            if t.topics:
                reasons.append(f"topics={','.join(t.topics)}")
            if reasons:
                print(f"           └─ {t.slug}: {'; '.join(reasons)}")

    print()
    print(f"Total: {sum(len(r) for r in plan)} tasks in {len(plan)} rounds")


def cmd_classify(_args):
    """Show classification of all queued tasks."""
    tasks = load_all_tasks()
    queued = get_queued(tasks)

    if not queued:
        print("No queued tasks.")
        return

    for t in queued:
        print(f"{t.slug}")
        print(f"  project:  {t.project}")
        print(f"  topics:   {', '.join(t.topics)}")
        print(f"  group:    {t.group}")
        print(f"  deps:     {', '.join(t.depends_on) or 'none'}")
        print(f"  priority: {t.priority}")
        print()


# ── Watchdog — detect stuck tasks ────────────────────────────

STUCK_THRESHOLD_MULTIPLIER = 3  # flag if task takes 3x average
MIN_RUNTIME_MINUTES = 20        # don't flag tasks under 20 min
ABSOLUTE_MAX_MINUTES = 90       # always flag tasks over 90 min


def get_average_duration(tasks: list) -> float:
    """Get average duration of completed tasks in minutes."""
    durations = []
    for t in tasks:
        if t.status in ("completed", "merged") and t.started_at and t.finished_at:
            try:
                start = datetime.fromisoformat(t.started_at.replace("Z", "+00:00"))
                end = datetime.fromisoformat(t.finished_at.replace("Z", "+00:00"))
                dur = (end - start).total_seconds() / 60
                if dur > 0:
                    durations.append(dur)
            except (ValueError, TypeError):
                pass
    return sum(durations) / len(durations) if durations else 15.0  # default 15 min


def check_watchdog(tasks: list) -> list:
    """
    Check for tasks that may be stuck.
    Returns list of (task, reason, elapsed_min) tuples.
    """
    avg = get_average_duration(tasks)
    threshold = max(avg * STUCK_THRESHOLD_MULTIPLIER, MIN_RUNTIME_MINUTES)
    now = datetime.now(timezone.utc)
    alerts = []

    for t in tasks:
        if t.status != "running" or not t.started_at:
            continue
        try:
            start = datetime.fromisoformat(t.started_at.replace("Z", "+00:00"))
            elapsed = (now - start).total_seconds() / 60
        except (ValueError, TypeError):
            continue

        if elapsed > ABSOLUTE_MAX_MINUTES:
            alerts.append((t, f"exceeded absolute max ({ABSOLUTE_MAX_MINUTES}m)", elapsed))
        elif elapsed > threshold:
            alerts.append((t, f"exceeded {STUCK_THRESHOLD_MULTIPLIER}x average ({avg:.0f}m avg, threshold {threshold:.0f}m)", elapsed))

    return alerts


def check_process_health(pid: int) -> dict:
    """Check if a Claude process is actually working (not idle)."""
    import subprocess
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid,%cpu,%mem,etime"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return {"alive": False, "cpu": 0, "reason": "process not found"}
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return {"alive": False, "cpu": 0, "reason": "no output"}
        parts = lines[1].split()
        cpu = float(parts[1]) if len(parts) > 1 else 0
        return {"alive": True, "cpu": cpu, "idle": cpu < 0.1}
    except Exception as e:
        return {"alive": False, "cpu": 0, "reason": str(e)}


def cmd_watchdog(_args):
    """Check for stuck or suspicious tasks."""
    tasks = load_all_tasks()
    avg = get_average_duration(tasks)
    running = get_running(tasks)

    print(f"Average task duration: {avg:.0f}m")
    print(f"Stuck threshold: {max(avg * STUCK_THRESHOLD_MULTIPLIER, MIN_RUNTIME_MINUTES):.0f}m")
    print(f"Absolute max: {ABSOLUTE_MAX_MINUTES}m")
    print(f"Running: {len(running)}")
    print()

    if not running:
        print("No running tasks.")
        return

    alerts = check_watchdog(tasks)
    now = datetime.now(timezone.utc)

    for t in running:
        try:
            start = datetime.fromisoformat(t.started_at.replace("Z", "+00:00"))
            elapsed = (now - start).total_seconds() / 60
        except (ValueError, TypeError):
            elapsed = 0

        is_alert = any(a[0].id == t.id for a in alerts)
        icon = "⚠️ " if is_alert else "✅"
        print(f"{icon} {t.slug} [{t.project}]")
        print(f"   elapsed: {elapsed:.0f}m")

        # Check log file size as activity indicator
        log_path = FLEET_DIR / "logs" / f"{t.id}.log"
        if log_path.exists():
            size = log_path.stat().st_size
            print(f"   log: {size:,} bytes")
            if size == 0 and elapsed > 5:
                print(f"   ⚠️  Log is empty after {elapsed:.0f}m — possible pipe buffer issue")
        else:
            print(f"   log: not found")

        # Check if the task has made git commits (sign of progress)
        if t.project_path:
            import subprocess
            try:
                branch_field = ""
                with open(t.file_path) as _f:
                    branch_field = json.load(_f).get("branch", "")
                if branch_field:
                    result = subprocess.run(
                        ["git", "-C", t.project_path, "log", "--oneline",
                         f"main..{branch_field}"],
                        capture_output=True, text=True, timeout=5
                    )
                    commits = [l for l in result.stdout.strip().split("\n") if l]
                    if commits:
                        print(f"   commits: {len(commits)} (making progress)")
                        for c in commits[-3:]:
                            print(f"     {c}")
                    else:
                        print(f"   commits: 0 ⚠️  no commits yet")
            except Exception:
                pass

        if is_alert:
            reason = next(a[1] for a in alerts if a[0].id == t.id)
            # Downgrade alert if task has commits (it's working, just slow)
            has_commits = any("commits:" in l and "making progress" in l
                             for l in [])  # simplified check
            print(f"   🔴 ALERT: {reason}")

        print()

    if not alerts:
        print("All tasks within normal range.")
    else:
        print(f"{len(alerts)} task(s) flagged as potentially stuck.")


def cmd_merge(_args):
    """Show what would be merged, then merge."""
    tasks = load_all_tasks()
    groups = find_mergeable_groups(tasks)

    if not groups:
        print("No mergeable tasks found.")
        return

    print(f"MERGE CANDIDATES ({len(groups)} groups):\n")
    for i, group in enumerate(groups, 1):
        slugs = [t.slug for t in group]
        print(f"  Group {i}: {' + '.join(slugs)}")
        print(f"    project: {group[0].project}")
        print(f"    group:   {group[0].group}")
        affinities = []
        for a in range(len(group)):
            for b in range(a + 1, len(group)):
                aff = topic_affinity(group[a].topics, group[b].topics)
                affinities.append(f"{group[a].slug}<>{group[b].slug}={aff:.0%}")
        print(f"    affinity: {', '.join(affinities)}")
        print()

    # Perform merges
    for group in groups:
        merge_tasks(group)

    print(f"\nMerged {sum(len(g) for g in groups)} tasks into {len(groups)} combined tasks.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "next"
    args = sys.argv[2:]

    if cmd == "next":
        cmd_next(args)
    elif cmd == "next-all":
        cmd_next_all(args)
    elif cmd == "plan":
        cmd_plan(args)
    elif cmd == "classify":
        cmd_classify(args)
    elif cmd == "merge":
        cmd_merge(args)
    elif cmd == "watchdog":
        cmd_watchdog(args)
    elif cmd == "reorder":
        cmd_plan(args)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Usage: queue-manager.py [next|next-all|plan|classify|merge]", file=sys.stderr)
        sys.exit(1)
