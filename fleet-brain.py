#!/usr/bin/env python3
"""
Fleet Brain — Single intelligent manager for the Fleet Worker system.

Consolidates queue management, PR management, conflict diagnosis, and watchdog
into one file.

Commands:
  fleet-brain.py next [--just-completed SLUG]     # pick next task
  fleet-brain.py next-all                          # parallel picks
  fleet-brain.py plan / eta / watchdog / classify / merge  # scheduling commands
  fleet-brain.py pr-create TASK_FILE               # rebase, push, create PR
  fleet-brain.py pr-auto-merge TASK_FILE           # classify + auto-merge if safe
  fleet-brain.py conflict-fix TASK_FILE            # diagnose conflict, create fix task
  fleet-brain.py cleanup                           # prune branches, archive manifests
  fleet-brain.py task-field / update-status / count-status  # manifest helpers
  fleet-brain.py cancel / backlog-next / backlog-field      # task management
"""

import json
import os
import sys
import re
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

FLEET_DIR = Path.home() / ".claude-fleet"
TASKS_DIR = FLEET_DIR / "tasks"
ARCHIVE_DIR = FLEET_DIR / "archive"

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

# ── PR Auto-Merge Policy ─────────────────────────────────────
# Tasks matching these patterns can be auto-merged without human review.
# Everything else requires Commander review.

AUTO_MERGE_TOPICS = {"docs", "infra", "test"}

AUTO_MERGE_PATH_PATTERNS = [
    r"\.context/",
    r"CLAUDE\.md$",
    r"ARCHITECTURE\.md$",
    r"\.github/",
    r"Makefile$",
    r"Dockerfile$",
    r"docker-compose",
    r"\.gitignore$",
    r"\.eslintrc",
    r"\.prettierrc",
    r"pyproject\.toml$",
    r"setup\.cfg$",
    r"requirements.*\.txt$",
    r"package\.json$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"Cargo\.lock$",
    r"go\.sum$",
]

NEEDS_REVIEW_PATTERNS = [
    r"feat",       # new features
    r"ui",         # user-facing UI changes
    r"ux",         # user experience changes
    r"refactor",   # large refactors
]

# Max lines changed before a PR always needs review
AUTO_MERGE_MAX_LINES = 500


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
    base_branch: str = "main"

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
            base_branch=d.get("base_branch", "main"),
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
            print(f"[brain] Warning: skipping {f.name}: {e}", file=sys.stderr)
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


def estimate_duration(task: Task, all_tasks: list) -> float:
    """
    Estimate how long a task will take in minutes,
    based on historical data from similar completed tasks.
    """
    completed = [t for t in all_tasks
                 if t.status in ("completed", "merged") and t.started_at and t.finished_at]
    if not completed:
        return 15.0  # default

    # Find similar tasks by topic/project
    similar = []
    for t in completed:
        try:
            start = datetime.fromisoformat(t.started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(t.finished_at.replace("Z", "+00:00"))
            dur = (end - start).total_seconds() / 60
            if dur <= 0:
                continue
        except (ValueError, TypeError):
            continue

        affinity = topic_affinity(task.topics, t.topics)
        same_proj = task.project == t.project
        is_combined = "combined" in t.slug
        is_heavy = any(kw in t.slug for kw in ["review", "optimization", "maintenance"])

        # Weight by similarity
        weight = 0.5
        if same_proj:
            weight += 0.3
        if affinity > 0.5:
            weight += 0.2
        # Combined/heavy tasks skew the average — weight them less for normal tasks
        if is_combined and "combined" not in task.slug:
            weight *= 0.3
        if is_heavy and not any(kw in task.slug for kw in ["review", "optimization", "maintenance"]):
            weight *= 0.3

        similar.append((dur, weight))

    if not similar:
        return 15.0

    weighted_sum = sum(d * w for d, w in similar)
    weight_total = sum(w for _, w in similar)
    estimate = weighted_sum / weight_total if weight_total > 0 else 15.0

    # Combined tasks take longer — scale by sub-task count
    if "combined" in task.slug:
        with open(task.file_path) as f:
            merged_from = json.load(f).get("merged_from", [])
        if merged_from:
            estimate *= min(len(merged_from) * 0.7, 3.0)  # not linear, diminishing

    return round(estimate, 1)


def format_eta(minutes: float) -> str:
    """Format minutes into human-readable ETA."""
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return f"~{int(minutes)}m"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"~{hours}h {mins}m" if mins else f"~{hours}h"


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
# Conservative merging: only combine tasks that are genuinely
# small and similar. The goal is efficiency, not cramming
# everything into one session that might fail.

MAX_MERGE = 3           # max tasks to merge into one (keep sessions focused)
MIN_AFFINITY_TO_MERGE = 0.6  # high overlap required (was 0.3 — too aggressive)
MAX_PROMPT_CHARS = 4000  # don't merge if combined prompt would be huge


def is_merge_safe(task: Task) -> bool:
    """Check if a task is safe to merge with others."""
    # Never merge retried tasks — they have existing branches/commits
    if task.retry_count > 0:
        return False
    # Never merge tasks that are already combined
    if task.slug.startswith("combined-"):
        return False
    # Never merge heavy/review/audit tasks
    heavy_keywords = ["review", "optimization", "audit", "maintenance", "overnight"]
    if any(kw in task.slug for kw in heavy_keywords):
        return False
    # Never merge tasks with explicit dependencies
    if task.depends_on:
        return False
    return True


def find_mergeable_groups(tasks: list) -> list:
    """
    Find groups of queued tasks that can be merged.
    Conservative: only merge small, similar, fresh tasks.
    """
    queued = [t for t in get_queued(tasks)
              if deps_satisfied(t, tasks) and is_merge_safe(t)]
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

        # Within same project, find clusters by SAME group AND high affinity
        used = set()
        for i, t1 in enumerate(proj_tasks):
            if i in used:
                continue
            group = [t1]
            used.add(i)

            for j, t2 in enumerate(proj_tasks):
                if j in used or len(group) >= MAX_MERGE:
                    continue
                # Must be SAME group (not just similar topics)
                same_group = t1.group and t1.group == t2.group
                affinity = topic_affinity(t1.topics, t2.topics)

                if not same_group:
                    continue  # different groups = don't merge
                if t1.base_branch != t2.base_branch:
                    continue  # different base branches = incompatible
                if affinity < MIN_AFFINITY_TO_MERGE:
                    continue  # not similar enough

                # Check combined prompt size wouldn't be too large
                total_chars = sum(len(t.prompt) for t in group) + len(t2.prompt)
                if total_chars > MAX_PROMPT_CHARS:
                    continue  # would make a bloated session

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

    print(f"[brain] Merged {len(group)} tasks → {combined_slug}", file=sys.stderr)
    for t in group:
        print(f"[brain]   - {t.slug}", file=sys.stderr)

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


# ── Git helpers ──────────────────────────────────────────────

def git_run(args: list, cwd: str = None, check: bool = False,
            timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + args
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=cwd, timeout=timeout,
    )


def gh_run(args: list, cwd: str = None, check: bool = False,
           timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a gh CLI command and return the result."""
    cmd = ["gh"] + args
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=cwd, timeout=timeout,
    )


# ── PR Classification ────────────────────────────────────────

def get_pr_changed_files(project_path: str, branch: str,
                         base_branch: str = "main") -> list:
    """Get list of files changed in this branch vs base."""
    result = git_run(
        ["diff", "--name-only", f"origin/{base_branch}...{branch}"],
        cwd=project_path,
    )
    if result.returncode != 0:
        # Try without origin/ prefix
        result = git_run(
            ["diff", "--name-only", f"{base_branch}...{branch}"],
            cwd=project_path,
        )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f]


def get_pr_diff_stats(project_path: str, branch: str,
                      base_branch: str = "main") -> dict:
    """Get insertions/deletions stats for a branch."""
    result = git_run(
        ["diff", "--shortstat", f"origin/{base_branch}...{branch}"],
        cwd=project_path,
    )
    if result.returncode != 0:
        result = git_run(
            ["diff", "--shortstat", f"{base_branch}...{branch}"],
            cwd=project_path,
        )
    stats = {"files": 0, "insertions": 0, "deletions": 0, "total_lines": 0}
    if result.returncode == 0 and result.stdout.strip():
        text = result.stdout.strip()
        m = re.search(r"(\d+) file", text)
        if m:
            stats["files"] = int(m.group(1))
        m = re.search(r"(\d+) insertion", text)
        if m:
            stats["insertions"] = int(m.group(1))
        m = re.search(r"(\d+) deletion", text)
        if m:
            stats["deletions"] = int(m.group(1))
        stats["total_lines"] = stats["insertions"] + stats["deletions"]
    return stats


def classify_pr(task: Task) -> dict:
    """
    Classify a PR for auto-merge eligibility.

    Returns:
        {
            "auto_merge": bool,
            "reason": str,
            "category": str,  # "docs", "infra", "test", "feature", "refactor", "ui", etc.
            "changed_files": list,
            "stats": dict,
        }
    """
    project_path = task.project_path
    with open(task.file_path) as f:
        manifest = json.load(f)
    branch = manifest.get("branch", "")
    base_branch = task.base_branch

    if not branch:
        return {
            "auto_merge": False,
            "reason": "no branch in manifest",
            "category": "unknown",
            "changed_files": [],
            "stats": {},
        }

    # Fetch latest
    git_run(["fetch", "origin"], cwd=project_path)

    changed_files = get_pr_changed_files(project_path, branch, base_branch)
    stats = get_pr_diff_stats(project_path, branch, base_branch)

    # Determine primary category from task topics
    primary_topic = task.topics[0] if task.topics else "general"

    # Check if too large for auto-merge
    if stats.get("total_lines", 0) > AUTO_MERGE_MAX_LINES:
        return {
            "auto_merge": False,
            "reason": f"too many lines changed ({stats['total_lines']} > {AUTO_MERGE_MAX_LINES})",
            "category": primary_topic,
            "changed_files": changed_files,
            "stats": stats,
        }

    # Check if all changed files match auto-merge path patterns
    all_files_safe = True
    unsafe_files = []
    for fpath in changed_files:
        is_safe = any(re.search(pat, fpath) for pat in AUTO_MERGE_PATH_PATTERNS)
        if not is_safe:
            all_files_safe = False
            unsafe_files.append(fpath)

    # Auto-merge if: topic is safe AND (all files match safe patterns OR topic is purely safe)
    if primary_topic in AUTO_MERGE_TOPICS:
        if all_files_safe or primary_topic in ("docs", "test"):
            return {
                "auto_merge": True,
                "reason": f"safe category ({primary_topic}) with compatible files",
                "category": primary_topic,
                "changed_files": changed_files,
                "stats": stats,
            }

    # If all files match safe patterns regardless of topic
    if all_files_safe and changed_files:
        return {
            "auto_merge": True,
            "reason": "all changed files match safe path patterns",
            "category": primary_topic,
            "changed_files": changed_files,
            "stats": stats,
        }

    # Check for needs-review signals
    needs_review_reason = None
    for pat in NEEDS_REVIEW_PATTERNS:
        if re.search(pat, task.slug) or re.search(pat, primary_topic):
            needs_review_reason = f"matches review pattern: {pat}"
            break

    if needs_review_reason:
        return {
            "auto_merge": False,
            "reason": needs_review_reason,
            "category": primary_topic,
            "changed_files": changed_files,
            "stats": stats,
        }

    # Default: if small and files are mostly safe, auto-merge
    if stats.get("total_lines", 0) <= 100 and len(unsafe_files) <= 2:
        return {
            "auto_merge": True,
            "reason": f"small change ({stats.get('total_lines', 0)} lines, {len(unsafe_files)} non-pattern files)",
            "category": primary_topic,
            "changed_files": changed_files,
            "stats": stats,
        }

    return {
        "auto_merge": False,
        "reason": f"requires review ({len(unsafe_files)} files outside safe patterns)",
        "category": primary_topic,
        "changed_files": changed_files,
        "stats": stats,
    }


# ── Conflict Handling ─────────────────────────────────────────

def rebase_on_base(project_path: str, branch: str,
                   base_branch: str = "main") -> dict:
    """
    Attempt to rebase a branch onto the latest base branch.

    Returns:
        {
            "success": bool,
            "conflict": bool,
            "conflict_files": list,
            "conflict_details": str,
        }
    """
    # Fetch latest
    git_run(["fetch", "origin"], cwd=project_path)

    # Make sure we're on the right branch
    git_run(["checkout", branch], cwd=project_path)

    # Attempt rebase
    result = git_run(
        ["rebase", f"origin/{base_branch}"],
        cwd=project_path, timeout=120,
    )

    if result.returncode == 0:
        return {
            "success": True,
            "conflict": False,
            "conflict_files": [],
            "conflict_details": "",
        }

    # Rebase failed — likely conflict
    # Abort the rebase to leave the repo clean
    git_run(["rebase", "--abort"], cwd=project_path)

    # Parse conflict information
    conflict_files = []
    conflict_details = result.stderr + "\n" + result.stdout

    # Try a merge to get conflict file list (dry-run style)
    merge_result = git_run(
        ["merge", "--no-commit", "--no-ff", f"origin/{base_branch}"],
        cwd=project_path,
    )

    if merge_result.returncode != 0:
        # Parse conflict files from merge output
        for line in merge_result.stdout.split("\n"):
            if "CONFLICT" in line:
                # Extract filename from "CONFLICT (content): Merge conflict in <file>"
                m = re.search(r"Merge conflict in (.+)", line)
                if m:
                    conflict_files.append(m.group(1).strip())
                # Also match "CONFLICT (add/add): Merge conflict in <file>"
                m = re.search(r"CONFLICT \([^)]+\): .+ in (.+)", line)
                if m and m.group(1).strip() not in conflict_files:
                    conflict_files.append(m.group(1).strip())

        conflict_details += "\n" + merge_result.stdout + "\n" + merge_result.stderr

    # Abort the merge too
    git_run(["merge", "--abort"], cwd=project_path)

    return {
        "success": False,
        "conflict": True,
        "conflict_files": conflict_files,
        "conflict_details": conflict_details.strip(),
    }


def rebase_open_prs(project_path: str, base_branch: str = "main",
                    exclude_branch: str = "") -> list:
    """
    After merging a PR, trigger rebase on all remaining open worker/ PRs
    from the same project. This keeps subsequent PRs up-to-date with main
    and prevents cascading conflicts.

    Returns list of (pr_number, success) tuples.
    """
    # Fetch latest so we have the new main
    git_run(["fetch", "origin"], cwd=project_path)

    # List open PRs with worker/ prefix
    result = gh_run(
        ["pr", "list", "--state", "open",
         "--json", "number,headRefName",
         "-q", f'[.[] | select(.headRefName | startswith("worker/"))]'],
        cwd=project_path,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        prs = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return []

    results = []
    for pr in prs:
        pr_number = pr.get("number")
        head_branch = pr.get("headRefName", "")

        if not pr_number or head_branch == exclude_branch:
            continue

        print(f"[brain] Rebasing PR #{pr_number} ({head_branch}) onto {base_branch}...",
              file=sys.stderr)

        # Use GitHub API to update the PR branch
        # gh api repos/{owner}/{repo}/pulls/{number}/update-branch -f update_method=rebase
        update_result = gh_run(
            ["pr", "update-branch", str(pr_number), "--rebase"],
            cwd=project_path,
        )

        success = update_result.returncode == 0
        if success:
            print(f"[brain]   ✅ PR #{pr_number} rebased", file=sys.stderr)
        else:
            # Fallback: try local rebase + force push
            print(f"[brain]   ⚠️  GitHub rebase failed for PR #{pr_number}, trying local...",
                  file=sys.stderr)
            local_result = rebase_on_base(project_path, head_branch, base_branch)
            if local_result["success"]:
                push = git_run(
                    ["push", "--force-with-lease", "origin", head_branch],
                    cwd=project_path,
                )
                success = push.returncode == 0
                if success:
                    print(f"[brain]   ✅ PR #{pr_number} rebased (local)", file=sys.stderr)
                else:
                    print(f"[brain]   ❌ PR #{pr_number} push failed", file=sys.stderr)
            else:
                print(f"[brain]   ❌ PR #{pr_number} has conflicts — needs manual rebase",
                      file=sys.stderr)

        results.append((pr_number, success))

    return results


def diagnose_conflict(project_path: str, branch: str,
                      base_branch: str = "main",
                      conflict_files: list = None) -> str:
    """
    Produce a detailed diagnosis of why a conflict occurred.
    Returns a human-readable string suitable as prompt context for a fix task.
    """
    git_run(["fetch", "origin"], cwd=project_path)

    lines = [f"## Conflict Diagnosis", ""]
    lines.append(f"**Branch:** `{branch}`")
    lines.append(f"**Base:** `origin/{base_branch}`")
    lines.append("")

    if not conflict_files:
        # Try to determine conflict files
        rebase_result = rebase_on_base(project_path, branch, base_branch)
        conflict_files = rebase_result.get("conflict_files", [])

    if not conflict_files:
        lines.append("Could not determine conflicting files. Manual inspection needed.")
        return "\n".join(lines)

    lines.append(f"**Conflicting files ({len(conflict_files)}):**")
    for f in conflict_files:
        lines.append(f"  - `{f}`")
    lines.append("")

    # For each conflict file, show who changed what
    for fpath in conflict_files[:10]:  # limit to 10 files
        lines.append(f"### `{fpath}`")
        lines.append("")

        # What changed on the branch
        branch_log = git_run(
            ["log", "--oneline", f"origin/{base_branch}..{branch}", "--", fpath],
            cwd=project_path,
        )
        if branch_log.returncode == 0 and branch_log.stdout.strip():
            lines.append(f"**Changes on `{branch}`:**")
            for commit_line in branch_log.stdout.strip().split("\n")[:5]:
                lines.append(f"  - {commit_line}")
        else:
            lines.append(f"**No direct changes on `{branch}`**")

        # What changed on base since branch diverged
        base_log = git_run(
            ["log", "--oneline", f"{branch}..origin/{base_branch}", "--", fpath],
            cwd=project_path,
        )
        if base_log.returncode == 0 and base_log.stdout.strip():
            lines.append(f"**Changes on `origin/{base_branch}`:**")
            for commit_line in base_log.stdout.strip().split("\n")[:5]:
                lines.append(f"  - {commit_line}")
        else:
            lines.append(f"**No changes on `origin/{base_branch}`**")

        lines.append("")

    return "\n".join(lines)


def create_conflict_fix_task(task: Task, diagnosis: str,
                             conflict_files: list) -> str:
    """
    Create a high-priority fix task to resolve a merge conflict.
    Returns the path to the new task manifest.
    """
    fix_slug = f"conflict-fix-{task.slug[:30]}"
    fix_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + fix_slug
    fix_branch = f"worker/{fix_slug}-{datetime.now().strftime('%Y%m%d')}"

    with open(task.file_path) as f:
        original_manifest = json.load(f)

    original_branch = original_manifest.get("branch", "")

    prompt = f"""CONFLICT RESOLUTION TASK (auto-generated by fleet-brain)

The branch `{original_branch}` has merge conflicts with `origin/{task.base_branch}`.
Your job: resolve the conflicts so this branch can be merged cleanly.

{diagnosis}

## Instructions

1. Check out `{original_branch}`
2. Run `git fetch origin && git rebase origin/{task.base_branch}`
3. Resolve each conflict file — prefer the branch changes unless the base changes are clearly newer/better
4. For each conflict:
   - Read both sides carefully
   - Keep the intent of both changes where possible
   - If changes are in different sections of the file, keep both
   - If changes overlap, merge them logically
5. After resolving: `git rebase --continue`
6. Push the rebased branch: `git push --force-with-lease origin {original_branch}`
7. Do NOT create a new PR — the existing PR will update automatically

Conflicting files: {', '.join(conflict_files)}
"""

    fix_manifest = {
        "id": fix_id,
        "slug": fix_slug,
        "branch": original_branch,  # work on the SAME branch
        "project_name": task.project,
        "project_path": task.project_path,
        "subdir": "",
        "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "queued",
        "base_branch": task.base_branch,
        "prompt": prompt,
        "budget_usd": 5,
        "permission_mode": "dangerously-skip-permissions",
        "priority": 10,  # highest priority — run immediately
        "max_retries": 2,
        "retry_count": 0,
        "conflict_fix_for": task.id,
        "conflict_files": conflict_files,
    }

    fix_path = TASKS_DIR / f"{fix_id}.json"
    with open(fix_path, "w") as f:
        json.dump(fix_manifest, f, indent=2)

    return str(fix_path)


# ── CLI Commands ─────────────────────────────────────────────

def cmd_next(args):
    """Print the file path of the next task to run."""
    tasks = load_all_tasks()

    # Auto-retry failed tasks first
    for t in get_retryable(tasks):
        mark_for_retry(t)
        print(f"[brain] Auto-retrying failed task: {t.slug} "
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
        print(f"[brain] Auto-retrying: {t.slug}", file=sys.stderr)

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
            print(f"   🔴 ALERT: {reason}")

        print()

    if not alerts:
        print("All tasks within normal range.")
    else:
        print(f"{len(alerts)} task(s) flagged as potentially stuck.")


def cmd_eta(_args):
    """Show estimated time for all running and queued tasks."""
    tasks = load_all_tasks()
    running = get_running(tasks)
    queued = [t for t in get_queued(tasks) if deps_satisfied(t, tasks)]
    now = datetime.now(timezone.utc)

    print("ESTIMATED TIMELINE")
    print()

    cumulative = 0.0  # tracks when queued tasks would start

    for t in running:
        est = estimate_duration(t, tasks)
        try:
            start = datetime.fromisoformat(t.started_at.replace("Z", "+00:00"))
            elapsed = (now - start).total_seconds() / 60
        except (ValueError, TypeError):
            elapsed = 0
        remaining = max(est - elapsed, 1)
        print(f"  🔄 {t.slug:35s} {t.project:15s}  {format_eta(remaining)} remaining ({int(elapsed)}m elapsed of {format_eta(est)})")
        cumulative = max(cumulative, remaining)

    by_project = {}
    if queued:
        print()
        # Group queued by project to show sequential chains
        for t in queued:
            by_project.setdefault(t.project, []).append(t)

        for project, proj_tasks in by_project.items():
            proj_wait = cumulative if any(r.project == project for r in running) else 0
            for t in proj_tasks:
                est = estimate_duration(t, tasks)
                start_in = proj_wait
                done_in = start_in + est
                print(f"  📋 {t.slug:35s} {t.project:15s}  starts in {format_eta(start_in)}, done in {format_eta(done_in)} (est {format_eta(est)})")
                proj_wait = done_in

    # Total queue drain time
    total = cumulative
    for project, proj_tasks in by_project.items():
        for t in proj_tasks:
            total += estimate_duration(t, tasks)
    if total > 0:
        print(f"\n  Queue empty in: {format_eta(total)}")


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


# ── New PR Commands ──────────────────────────────────────────

def cmd_pr_create(args):
    """Rebase branch on base, push, and create a GitHub PR.

    Usage: fleet-brain.py pr-create <task-file>
    """
    if not args:
        print("Usage: fleet-brain.py pr-create <task-file>", file=sys.stderr)
        sys.exit(1)

    task_file = args[0]
    task = Task.from_file(task_file)

    with open(task_file) as f:
        manifest = json.load(f)

    branch = manifest.get("branch", "")
    base_branch = task.base_branch
    project_path = task.project_path

    if not branch or not project_path:
        print(f"[brain] Error: task missing branch or project_path", file=sys.stderr)
        sys.exit(1)

    print(f"[brain] PR create for {task.slug} ({branch})", file=sys.stderr)

    # Step 1: Fetch and rebase
    print(f"[brain] Rebasing {branch} onto origin/{base_branch}...", file=sys.stderr)
    rebase_result = rebase_on_base(project_path, branch, base_branch)

    if not rebase_result["success"]:
        if rebase_result["conflict"]:
            print(f"[brain] CONFLICT detected during rebase", file=sys.stderr)
            conflict_files = rebase_result["conflict_files"]
            for cf in conflict_files:
                print(f"[brain]   - {cf}", file=sys.stderr)

            # Output conflict info as JSON for the caller
            print(json.dumps({
                "status": "conflict",
                "conflict_files": conflict_files,
                "task_file": task_file,
            }))
            sys.exit(2)  # Special exit code for conflict
        else:
            print(f"[brain] Rebase failed (not a conflict)", file=sys.stderr)
            sys.exit(1)

    # Step 2: Push
    print(f"[brain] Pushing {branch}...", file=sys.stderr)
    push_result = git_run(
        ["push", "--force-with-lease", "origin", branch],
        cwd=project_path,
    )
    if push_result.returncode != 0:
        # Try regular push if force-with-lease fails (new branch)
        push_result = git_run(
            ["push", "-u", "origin", branch],
            cwd=project_path,
        )
    if push_result.returncode != 0:
        print(f"[brain] Push failed: {push_result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Step 3: Create PR (if one doesn't already exist)
    existing_pr = gh_run(
        ["pr", "list", "--head", branch, "--json", "number,url", "-q", ".[0].url"],
        cwd=project_path,
    )
    if existing_pr.returncode == 0 and existing_pr.stdout.strip():
        pr_url = existing_pr.stdout.strip()
        print(f"[brain] PR already exists: {pr_url}", file=sys.stderr)
    else:
        # Build PR title and body from task
        pr_title = task.slug.replace("-", " ").title()
        if len(pr_title) > 70:
            pr_title = pr_title[:67] + "..."

        stats = get_pr_diff_stats(project_path, branch, base_branch)
        changed_files = get_pr_changed_files(project_path, branch, base_branch)

        pr_body = f"""## Summary

Auto-generated PR from fleet-brain for task `{task.slug}`.

**Task prompt:** {task.prompt[:200]}{'...' if len(task.prompt) > 200 else ''}

## Stats
- Files changed: {stats.get('files', '?')}
- Lines: +{stats.get('insertions', '?')} / -{stats.get('deletions', '?')}

## Changed files
{chr(10).join(f'- `{f}`' for f in changed_files[:20])}
{'...' if len(changed_files) > 20 else ''}

---
🤖 Generated by fleet-brain
"""
        create_result = gh_run(
            ["pr", "create",
             "--base", base_branch,
             "--head", branch,
             "--title", pr_title,
             "--body", pr_body],
            cwd=project_path,
        )
        if create_result.returncode != 0:
            print(f"[brain] PR creation failed: {create_result.stderr}", file=sys.stderr)
            sys.exit(1)

        pr_url = create_result.stdout.strip()
        print(f"[brain] PR created: {pr_url}", file=sys.stderr)

    # Update task manifest with PR URL
    with open(task_file, "r+") as f:
        d = json.load(f)
        d["pr_url"] = pr_url
        f.seek(0)
        json.dump(d, f, indent=2)
        f.truncate()

    # Output the PR URL
    print(pr_url)


def cmd_pr_auto_merge(args):
    """Classify a PR and auto-merge if policy allows.

    Usage: fleet-brain.py pr-auto-merge <task-file>
    """
    if not args:
        print("Usage: fleet-brain.py pr-auto-merge <task-file>", file=sys.stderr)
        sys.exit(1)

    task_file = args[0]
    task = Task.from_file(task_file)

    with open(task_file) as f:
        manifest = json.load(f)

    branch = manifest.get("branch", "")
    project_path = task.project_path

    if not branch or not project_path:
        print(f"[brain] Error: task missing branch or project_path", file=sys.stderr)
        sys.exit(1)

    # Classify the PR
    classification = classify_pr(task)

    print(f"[brain] PR classification for {task.slug}:", file=sys.stderr)
    print(f"[brain]   category:   {classification['category']}", file=sys.stderr)
    print(f"[brain]   auto_merge: {classification['auto_merge']}", file=sys.stderr)
    print(f"[brain]   reason:     {classification['reason']}", file=sys.stderr)
    print(f"[brain]   files:      {len(classification['changed_files'])}", file=sys.stderr)
    stats = classification.get("stats", {})
    print(f"[brain]   lines:      +{stats.get('insertions', 0)} / -{stats.get('deletions', 0)}", file=sys.stderr)

    if not classification["auto_merge"]:
        print(json.dumps({
            "action": "needs_review",
            "reason": classification["reason"],
            "category": classification["category"],
            "stats": classification["stats"],
        }))
        sys.exit(0)

    # Auto-merge: find the PR number
    base_branch = task.base_branch
    pr_info = gh_run(
        ["pr", "list", "--head", branch, "--json", "number,url", "-q", ".[0]"],
        cwd=project_path,
    )
    if pr_info.returncode != 0 or not pr_info.stdout.strip():
        print(f"[brain] No PR found for branch {branch}", file=sys.stderr)
        print(json.dumps({"action": "no_pr", "reason": "PR not found"}))
        sys.exit(1)

    pr_data = json.loads(pr_info.stdout.strip())
    pr_number = pr_data.get("number")
    pr_url = pr_data.get("url", "")

    if not pr_number:
        print(f"[brain] Could not determine PR number", file=sys.stderr)
        sys.exit(1)

    # Layer 3: Rebase onto latest main before merging
    print(f"[brain] Rebasing PR #{pr_number} onto latest {base_branch}...",
          file=sys.stderr)
    rebase_result = rebase_on_base(project_path, branch, base_branch)
    if rebase_result["success"]:
        # Push rebased branch
        push_result = git_run(
            ["push", "--force-with-lease", "origin", branch],
            cwd=project_path,
        )
        if push_result.returncode != 0:
            git_run(["push", "-f", "origin", branch], cwd=project_path)
        print(f"[brain] PR #{pr_number} rebased successfully", file=sys.stderr)
    else:
        print(f"[brain] ⚠️  Pre-merge rebase failed for PR #{pr_number} — "
              f"attempting merge anyway", file=sys.stderr)

    # Merge the PR
    print(f"[brain] Auto-merging PR #{pr_number}...", file=sys.stderr)
    merge_result = gh_run(
        ["pr", "merge", str(pr_number), "--squash", "--delete-branch"],
        cwd=project_path,
    )

    if merge_result.returncode != 0:
        print(f"[brain] Merge failed: {merge_result.stderr}", file=sys.stderr)
        print(json.dumps({
            "action": "merge_failed",
            "reason": merge_result.stderr.strip(),
            "pr_number": pr_number,
        }))
        sys.exit(1)

    # Update task status
    with open(task_file, "r+") as f:
        d = json.load(f)
        d["status"] = "merged"
        d["merged_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        d["pr_url"] = pr_url
        f.seek(0)
        json.dump(d, f, indent=2)
        f.truncate()

    print(f"[brain] ✅ Auto-merged PR #{pr_number}", file=sys.stderr)

    # Layer 3: Cascade rebase to remaining open PRs
    cascade_results = rebase_open_prs(
        project_path, base_branch, exclude_branch=branch)
    cascade_info = []
    for cascade_pr, success in cascade_results:
        cascade_info.append({"pr": cascade_pr, "rebased": success})

    print(json.dumps({
        "action": "auto_merged",
        "pr_number": pr_number,
        "pr_url": pr_url,
        "category": classification["category"],
        "reason": classification["reason"],
        "cascade_rebased": cascade_info,
    }))


def cmd_conflict_fix(args):
    """Diagnose a conflict and create a high-priority fix task.

    Usage: fleet-brain.py conflict-fix <task-file>
    """
    if not args:
        print("Usage: fleet-brain.py conflict-fix <task-file>", file=sys.stderr)
        sys.exit(1)

    task_file = args[0]
    task = Task.from_file(task_file)

    with open(task_file) as f:
        manifest = json.load(f)

    branch = manifest.get("branch", "")
    project_path = task.project_path
    base_branch = task.base_branch

    if not branch or not project_path:
        print(f"[brain] Error: task missing branch or project_path", file=sys.stderr)
        sys.exit(1)

    print(f"[brain] Diagnosing conflicts for {task.slug} ({branch})...", file=sys.stderr)

    # Step 1: Attempt rebase to identify conflicts
    rebase_result = rebase_on_base(project_path, branch, base_branch)

    if rebase_result["success"]:
        print(f"[brain] No conflict — rebase succeeded!", file=sys.stderr)
        print(json.dumps({"status": "no_conflict", "message": "Rebase succeeded cleanly"}))
        sys.exit(0)

    conflict_files = rebase_result["conflict_files"]
    print(f"[brain] Found {len(conflict_files)} conflicting files", file=sys.stderr)

    # Step 2: Build diagnosis
    diagnosis = diagnose_conflict(project_path, branch, base_branch, conflict_files)
    print(f"[brain] Diagnosis complete", file=sys.stderr)

    # Step 3: Create fix task
    fix_path = create_conflict_fix_task(task, diagnosis, conflict_files)
    print(f"[brain] Created fix task: {fix_path}", file=sys.stderr)

    # Output result
    print(json.dumps({
        "status": "conflict_detected",
        "conflict_files": conflict_files,
        "fix_task": fix_path,
        "diagnosis_preview": diagnosis[:500],
    }))


def cmd_cleanup(_args):
    """Prune merged branches, archive old task manifests.

    Usage: fleet-brain.py cleanup
    """
    tasks = load_all_tasks()
    now = datetime.now(timezone.utc)
    archive_threshold_days = 7
    pruned_branches = 0
    archived_tasks = 0

    # Ensure archive directory exists
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    print("[brain] CLEANUP")
    print()

    # Step 1: Prune remote branches for merged/completed tasks
    print("── Branch Cleanup ──")
    for t in tasks:
        if t.status not in ("completed", "merged", "cancelled"):
            continue

        with open(t.file_path) as f:
            manifest = json.load(f)
        branch = manifest.get("branch", "")
        project_path = t.project_path

        if not branch or not project_path or not branch.startswith("worker/"):
            continue

        # Check if remote branch still exists
        check = git_run(
            ["ls-remote", "--heads", "origin", branch],
            cwd=project_path,
        )
        if check.returncode == 0 and check.stdout.strip():
            # Delete remote branch
            delete_result = git_run(
                ["push", "origin", "--delete", branch],
                cwd=project_path,
            )
            if delete_result.returncode == 0:
                print(f"  Pruned remote: origin/{branch}")
                pruned_branches += 1
            else:
                print(f"  Failed to prune: origin/{branch} ({delete_result.stderr.strip()})")

        # Delete local branch
        git_run(["branch", "-D", branch], cwd=project_path)

    print(f"  Pruned {pruned_branches} remote branches")
    print()

    # Step 2: Archive old completed/merged/failed/cancelled task manifests
    print("── Task Archive ──")
    for t in tasks:
        if t.status not in ("completed", "merged", "failed", "cancelled", "merged_into"):
            continue

        # Check age
        finished = t.finished_at or t.dispatched_at
        if not finished:
            continue
        try:
            ts = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            age_days = (now - ts).total_seconds() / 86400
        except (ValueError, TypeError):
            continue

        if age_days < archive_threshold_days:
            continue

        # Move to archive
        src = Path(t.file_path)
        dst = ARCHIVE_DIR / src.name
        shutil.move(str(src), str(dst))
        print(f"  Archived: {src.name} ({t.status}, {age_days:.0f} days old)")
        archived_tasks += 1

    print(f"  Archived {archived_tasks} task manifests to {ARCHIVE_DIR}")
    print()

    # Step 3: Clean up stale review queue items
    print("── Review Queue Cleanup ──")
    review_dir = FLEET_DIR / "review-queue"
    cleaned_reviews = 0
    if review_dir.exists():
        for review_file in review_dir.glob("*.md"):
            # Check if corresponding task is archived
            task_id_match = re.match(r"(.+?)-(completed|failed|blocked|decision)\.md",
                                     review_file.name)
            if task_id_match:
                task_id = task_id_match.group(1)
                # If task manifest no longer in active tasks dir, clean up
                task_manifest = TASKS_DIR / f"{task_id}.json"
                if not task_manifest.exists():
                    review_file.unlink()
                    print(f"  Cleaned: {review_file.name}")
                    cleaned_reviews += 1

    print(f"  Cleaned {cleaned_reviews} stale review queue items")
    print()

    # Step 4: Prune stale PID files
    print("── PID Cleanup ──")
    pid_dir = Path("/tmp/fleet-running")
    cleaned_pids = 0
    if pid_dir.exists():
        for pidfile in pid_dir.glob("*.pid"):
            try:
                pid = int(pidfile.read_text().strip())
                # Check if process is still alive
                result = subprocess.run(
                    ["kill", "-0", str(pid)],
                    capture_output=True, timeout=5,
                )
                if result.returncode != 0:
                    pidfile.unlink()
                    print(f"  Cleaned stale PID: {pidfile.name} (pid {pid})")
                    cleaned_pids += 1
            except (ValueError, OSError):
                pidfile.unlink()
                cleaned_pids += 1

    print(f"  Cleaned {cleaned_pids} stale PID files")
    print()

    print(f"SUMMARY: {pruned_branches} branches pruned, {archived_tasks} tasks archived, "
          f"{cleaned_reviews} review items cleaned, {cleaned_pids} PIDs cleaned")


# ── Task manifest helpers (called from worker-daemon.sh) ──


def cmd_task_field(args):
    """Read a single field from a task manifest JSON file.

    Usage: fleet-brain.py task-field <file> <field> [default]
    Prints the field value to stdout. Exits 1 if field missing and no default.
    """
    if len(args) < 2:
        print("Usage: task-field <file> <field> [default]", file=sys.stderr)
        sys.exit(1)
    filepath, field = args[0], args[1]
    default = args[2] if len(args) > 2 else None
    try:
        with open(filepath) as f:
            data = json.load(f)
        value = data.get(field)
        if value is None:
            if default is not None:
                print(default)
            else:
                sys.exit(1)
        else:
            print(value)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        if default is not None:
            print(default)
        else:
            sys.exit(1)


def cmd_update_status(args):
    """Update a task manifest's status and timestamps.

    Usage: fleet-brain.py update-status <file> <status> [key=value ...]
    Sets status, updates started_at/finished_at as appropriate,
    and applies any extra key=value pairs.
    """
    if len(args) < 2:
        print("Usage: update-status <file> <status> [key=value ...]", file=sys.stderr)
        sys.exit(1)
    filepath, new_status = args[0], args[1]
    extras = {}
    for kv in args[2:]:
        if "=" in kv:
            k, v = kv.split("=", 1)
            extras[k] = v

    try:
        with open(filepath, "r+") as f:
            data = json.load(f)
            data["status"] = new_status
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if new_status == "running":
                data["started_at"] = now
            elif new_status in ("completed", "failed", "blocked"):
                data["finished_at"] = now
            for k, v in extras.items():
                data[k] = v
            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error updating {filepath}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_count_status(args):
    """Count tasks with a given status.

    Usage: fleet-brain.py count-status <status>
    Prints the count to stdout.
    """
    if not args:
        print("Usage: count-status <status>", file=sys.stderr)
        sys.exit(1)
    target = args[0]
    tasks = load_all_tasks()
    count = sum(1 for t in tasks if t.status == target)
    print(count)


def cmd_cancel(args):
    """Cancel a running or queued task.

    Usage: fleet-brain.py cancel <slug-or-id>
    Finds the task, updates status to 'cancelled', and kills the tmux session
    if the task was running.
    """
    if not args:
        print("Usage: cancel <slug-or-id>", file=sys.stderr)
        sys.exit(1)
    target = args[0]
    tasks = load_all_tasks()

    found = None
    for t in tasks:
        if t.slug == target or t.id == target:
            found = t
            break

    if not found:
        print(f"Task not found: {target}", file=sys.stderr)
        sys.exit(1)

    if found.status not in ("queued", "running"):
        print(f"Task {found.slug} is {found.status} — can only cancel queued/running tasks",
              file=sys.stderr)
        sys.exit(1)

    was_running = found.status == "running"

    # Update manifest
    with open(found.file_path, "r+") as f:
        data = json.load(f)
        data["status"] = "cancelled"
        data["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["error_message"] = "Cancelled by user"
        f.seek(0)
        json.dump(data, f, indent=2)
        f.truncate()

    print(f"Cancelled: {found.slug} ({found.id})")

    # Kill tmux session if running
    if was_running:
        # Try to find tmux session by task slug
        tmux_candidates = [
            f"claude-{found.slug[:30]}",
            f"claude-{found.id}",
        ]
        for session_name in tmux_candidates:
            result = subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                print(f"Killed tmux session: {session_name}")
                break

        # Also clean up the PID file
        pid_file = Path("/tmp/fleet-running") / f"{found.project}.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                subprocess.run(["kill", str(pid)], capture_output=True, timeout=5)
                pid_file.unlink()
                print(f"Killed process {pid}")
            except (ValueError, OSError):
                pass


def cmd_backlog_next(args):
    """Find the next backlog task not already dispatched.

    Usage: fleet-brain.py backlog-next <backlog-file>
    Prints the task JSON to stdout. Exits 1 if no task available.
    """
    if not args:
        print("Usage: backlog-next <backlog-file>", file=sys.stderr)
        sys.exit(1)
    backlog_file = args[0]
    try:
        with open(backlog_file) as f:
            bl = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading backlog: {e}", file=sys.stderr)
        sys.exit(1)

    # Get all existing task slugs
    existing_slugs = set()
    if TASKS_DIR.exists():
        for tf in TASKS_DIR.glob("*.json"):
            try:
                data = json.loads(tf.read_text())
                slug = data.get("slug", "")
                if slug:
                    existing_slugs.add(slug)
                # Also check filename for slug
                existing_slugs.add(tf.stem)
            except (json.JSONDecodeError, OSError):
                pass

    # Find highest priority task not already dispatched
    for task in sorted(bl.get("tasks", []), key=lambda t: t.get("priority", 99)):
        slug = task.get("slug", "")
        if slug and slug not in existing_slugs:
            # Also check if slug appears in any filename
            found = any(slug in tf.name for tf in TASKS_DIR.glob("*.json"))
            if not found:
                print(json.dumps(task))
                return

    sys.exit(1)  # No available backlog task


def cmd_backlog_field(args):
    """Read a field from a JSON object passed via stdin.

    Usage: echo '{"key":"val"}' | fleet-brain.py backlog-field <field> [default]
    """
    if not args:
        print("Usage: backlog-field <field> [default]", file=sys.stderr)
        sys.exit(1)
    field = args[0]
    default = args[1] if len(args) > 1 else None
    try:
        data = json.load(sys.stdin)
        value = data.get(field)
        if value is None:
            if default is not None:
                print(default)
            else:
                sys.exit(1)
        else:
            # For prompt field, JSON-encode it so it's safe for embedding
            if field == "prompt" and len(args) > 2 and args[2] == "--json":
                print(json.dumps(value))
            else:
                print(value)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if default is not None:
            print(default)
        else:
            sys.exit(1)


# ── Main dispatch ────────────────────────────────────────────

COMMANDS = {
    "next":          cmd_next,
    "next-all":      cmd_next_all,
    "plan":          cmd_plan,
    "classify":      cmd_classify,
    "merge":         cmd_merge,
    "eta":           cmd_eta,
    "watchdog":      cmd_watchdog,
    "reorder":       cmd_plan,  # alias
    "pr-create":     cmd_pr_create,
    "pr-auto-merge": cmd_pr_auto_merge,
    "conflict-fix":  cmd_conflict_fix,
    "cleanup":       cmd_cleanup,
    "task-field":    cmd_task_field,
    "update-status": cmd_update_status,
    "count-status":  cmd_count_status,
    "backlog-next":  cmd_backlog_next,
    "backlog-field": cmd_backlog_field,
    "cancel":        cmd_cancel,
}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "next"
    args = sys.argv[2:]

    handler = COMMANDS.get(cmd)
    if handler:
        handler(args)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Usage: fleet-brain.py [" + "|".join(sorted(COMMANDS.keys())) + "]",
              file=sys.stderr)
        sys.exit(1)
