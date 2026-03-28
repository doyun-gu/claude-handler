#!/usr/bin/env python3
"""Bug database management for fleet healthcheck system.

Works as both an importable module and a CLI tool.

CLI usage:
    python3 bug-db.py <command> [args...]

Commands:
    upsert <db_path> <slug> <severity> <description>   # raw_error via stdin
    check-cooldown <db_path> <slug>                     # exit 0=cooldown, 1=ok
    record-heal <db_path> <slug>
    regenerate-md <db_path> <out_path>
    count-bugs <db_path>                                # prints "new critical"
    check-recent-completed <tasks_dir>                  # prints RECENT or nothing
    mark-all-fixed <db_path>
    check-task-branch <task_file> <project_name>        # prints branch or nothing
    get <db_path> <slug>                                # prints JSON
    list <db_path>                                      # prints JSON
    should-escalate <db_path> <slug> [threshold]        # exit 0=yes, 1=no
    mark-escalated <db_path> <slug>
"""

import datetime
import glob
import json
import os
import sys
import tempfile
import time


def _load_db(db_path):
    """Load the bug database, returning empty structure on error."""
    try:
        with open(db_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"bugs": {}, "version": 1}


def _save_db(db_path, db):
    """Atomically save the bug database."""
    dirname = os.path.dirname(db_path) or "."
    fd, tmp = tempfile.mkstemp(dir=dirname)
    with os.fdopen(fd, "w") as f:
        json.dump(db, f, indent=2)
    os.rename(tmp, db_path)


def add_bug(db_path, bug_id, description, source, severity="medium", raw_error=""):
    """Add or increment a bug entry. Returns occurrence count."""
    db = _load_db(db_path)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if bug_id in db["bugs"]:
        db["bugs"][bug_id]["occurrences"] += 1
        db["bugs"][bug_id]["last_seen"] = now
        db["bugs"][bug_id]["severity"] = severity
        db["bugs"][bug_id]["description"] = description
        if raw_error:
            db["bugs"][bug_id]["last_error"] = raw_error
    else:
        db["bugs"][bug_id] = {
            "severity": severity,
            "description": description,
            "first_seen": now,
            "last_seen": now,
            "occurrences": 1,
            "status": "new",
            "heal_count": 0,
            "heal_timestamps": [],
            "escalated": False,
            "last_error": raw_error,
            "source": source,
        }

    _save_db(db_path, db)
    return db["bugs"][bug_id]["occurrences"]


def get_bug(db_path, bug_id):
    """Get bug details. Returns dict or None."""
    db = _load_db(db_path)
    return db.get("bugs", {}).get(bug_id)


def list_bugs(db_path):
    """List all bugs. Returns dict of slug -> bug."""
    db = _load_db(db_path)
    return db.get("bugs", {})


def should_escalate(db_path, bug_id, threshold=10):
    """Check if bug's heal_count meets or exceeds threshold."""
    bug = get_bug(db_path, bug_id)
    if not bug:
        return False
    return bug.get("heal_count", 0) >= threshold


def mark_escalated(db_path, bug_id):
    """Mark a bug as escalated. Returns True if bug existed."""
    db = _load_db(db_path)
    bug = db.get("bugs", {}).get(bug_id)
    if not bug:
        return False
    bug["escalated"] = True
    bug["status"] = "escalated"
    _save_db(db_path, db)
    return True


def check_cooldown(db_path, bug_id):
    """Check if bug is in cooldown.

    Returns True if cooldown active (should NOT auto-heal).
    Cooldown triggers: >=3 heals in last 300s, or >=10 total heals.
    """
    db = _load_db(db_path)
    bug = db.get("bugs", {}).get(bug_id)
    if not bug:
        return False

    now = time.time()
    recent = [t for t in bug.get("heal_timestamps", []) if now - t < 300]
    if len(recent) >= 3:
        return True

    if bug.get("heal_count", 0) >= 10:
        return True

    return False


def record_heal(db_path, bug_id):
    """Record a successful heal. Auto-escalates after 10 heals."""
    db = _load_db(db_path)
    bug = db.get("bugs", {}).get(bug_id)
    if not bug:
        return

    bug["heal_count"] = bug.get("heal_count", 0) + 1
    timestamps = bug.get("heal_timestamps", [])
    timestamps.append(time.time())
    bug["heal_timestamps"] = timestamps[-10:]

    if bug["heal_count"] >= 10 and not bug.get("escalated", False):
        bug["escalated"] = True
        bug["status"] = "escalated"

    db["bugs"][bug_id] = bug
    _save_db(db_path, db)


def regenerate_debug_md(db_path, out_path):
    """Regenerate DEBUG_DETECTOR.md from bug-db.json (capped at 50 bugs)."""
    db = _load_db(db_path)
    bugs = db.get("bugs", {})
    sorted_bugs = sorted(
        bugs.items(), key=lambda x: x[1].get("last_seen", ""), reverse=True
    )[:50]

    status_icons = {
        "new": "\U0001f534 NEW",
        "escalated": "\u26a0\ufe0f ESCALATED",
        "healed": "\U0001f7e2 HEALED",
        "fixed": "\u2705 FIXED",
    }

    lines = [
        "# DEBUG_DETECTOR \u2014 Auto-detected Bugs & Errors",
        "",
        "This file is auto-generated from `bug-db.json`. Do not edit manually.",
        "",
        f"**Total tracked bugs:** {len(bugs)} | **Showing:** {len(sorted_bugs)}",
        "",
        "---",
        "",
    ]

    for slug, bug in sorted_bugs:
        icon = status_icons.get(bug.get("status", "new"), "\U0001f534 NEW")
        lines.append(f'### {icon}: {bug.get("description", slug)}')
        lines.append("")
        lines.append(f"- **slug:** {slug}")
        lines.append(f'- **severity:** {bug.get("severity", "unknown")}')
        lines.append(f'- **first_seen:** {bug.get("first_seen", "?")}')
        lines.append(f'- **last_seen:** {bug.get("last_seen", "?")}')
        lines.append(f'- **occurrences:** {bug.get("occurrences", 0)}')
        lines.append(f'- **heal_count:** {bug.get("heal_count", 0)}')
        lines.append(f"- **status:** {icon}")
        error = bug.get("last_error", "")
        if error:
            lines.append("")
            lines.append("```")
            for line in str(error).split("\n")[:10]:
                lines.append(line)
            lines.append("```")
        lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))


def count_bugs(db_path):
    """Count new and critical bugs. Returns (new_count, critical_count)."""
    db = _load_db(db_path)
    bugs = db.get("bugs", {})
    critical = sum(
        1
        for b in bugs.values()
        if b.get("severity") == "critical" and b.get("status") == "new"
    )
    new = sum(1 for b in bugs.values() if b.get("status") == "new")
    return new, critical


def check_recent_completed(tasks_dir):
    """Check if any auto-bugfix task completed in the last 30 minutes."""
    now = time.time()
    pattern = os.path.join(tasks_dir, "auto-*-bugfix.json")
    for f in sorted(glob.glob(pattern), reverse=True)[:10]:
        try:
            with open(f) as fh:
                d = json.load(fh)
            if d.get("status") == "completed" and d.get("finished_at"):
                fin = datetime.datetime.fromisoformat(
                    d["finished_at"].replace("Z", "+00:00")
                ).timestamp()
                if now - fin < 1800:
                    return True
        except Exception:
            pass
    return False


def mark_all_fixed(db_path):
    """Mark all 'new' bugs as fixed (auto-cleared by worker)."""
    db = _load_db(db_path)
    changed = False
    for bug in db.get("bugs", {}).values():
        if bug.get("status") == "new":
            bug["status"] = "fixed"
            bug["fixed_by"] = "auto-cleared: worker found no NEW bugs"
            changed = True
    if changed:
        _save_db(db_path, db)
    return changed


def check_task_branch(task_file, project_name):
    """Get the branch of a completed task matching project_name, or None."""
    try:
        with open(task_file) as f:
            d = json.load(f)
        if d.get("status") == "completed" and d.get("project_name") == project_name:
            return d.get("branch", "")
    except Exception:
        pass
    return None


def _cli():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    try:
        if cmd == "upsert":
            db_path, slug, severity, description = (
                sys.argv[2],
                sys.argv[3],
                sys.argv[4],
                sys.argv[5],
            )
            raw_error = ""
            if not sys.stdin.isatty():
                raw_error = sys.stdin.read().strip()
            count = add_bug(
                db_path,
                slug,
                description,
                source="healthcheck",
                severity=severity,
                raw_error=raw_error,
            )
            print(count)

        elif cmd == "check-cooldown":
            db_path, slug = sys.argv[2], sys.argv[3]
            sys.exit(0 if check_cooldown(db_path, slug) else 1)

        elif cmd == "record-heal":
            db_path, slug = sys.argv[2], sys.argv[3]
            record_heal(db_path, slug)

        elif cmd == "regenerate-md":
            db_path, out_path = sys.argv[2], sys.argv[3]
            regenerate_debug_md(db_path, out_path)

        elif cmd == "count-bugs":
            db_path = sys.argv[2]
            new, critical = count_bugs(db_path)
            print(f"{new} {critical}")

        elif cmd == "check-recent-completed":
            tasks_dir = sys.argv[2]
            if check_recent_completed(tasks_dir):
                print("RECENT")

        elif cmd == "mark-all-fixed":
            db_path = sys.argv[2]
            mark_all_fixed(db_path)

        elif cmd == "check-task-branch":
            task_file, project_name = sys.argv[2], sys.argv[3]
            branch = check_task_branch(task_file, project_name)
            if branch:
                print(branch)

        elif cmd == "get":
            db_path, slug = sys.argv[2], sys.argv[3]
            bug = get_bug(db_path, slug)
            if bug:
                json.dump(bug, sys.stdout, indent=2)
                print()
            else:
                sys.exit(1)

        elif cmd == "list":
            db_path = sys.argv[2]
            bugs = list_bugs(db_path)
            json.dump(bugs, sys.stdout, indent=2)
            print()

        elif cmd == "should-escalate":
            db_path, slug = sys.argv[2], sys.argv[3]
            threshold = int(sys.argv[4]) if len(sys.argv) > 4 else 10
            sys.exit(0 if should_escalate(db_path, slug, threshold) else 1)

        elif cmd == "mark-escalated":
            db_path, slug = sys.argv[2], sys.argv[3]
            if not mark_escalated(db_path, slug):
                sys.exit(1)

        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)

    except IndexError:
        print(f"Missing arguments for command: {cmd}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
