# Fleet Worker Daemon — Error Code Runbook

Single source of truth for diagnosing fleet errors. When a `[D-xxx]` code appears, look it up here for diagnosis and fix.

## Quick Reference

| Code | Severity | Category | Description | Auto-recovery |
|------|----------|----------|-------------|---------------|
| D-001 | critical | DAEMON | Crash loop (5+ restarts/5min) | Stop daemon, notify |
| D-002 | critical | DAEMON | Queue manager not found | Exit |
| D-003 | critical | DAEMON | Claude CLI missing | Exit |
| D-004 | info | PID | Stale PID file | Auto-clean |
| D-005 | info | PID | PID file race condition | Skip, retry |
| D-010 | warning | TASK | Missing manifest fields | Mark failed |
| D-011 | warning | TASK | Project path missing | Mark failed |
| D-012 | warning | TASK | Branch checkout failed | Mark failed |
| D-013 | warning | TASK | Claude non-zero exit | Mark failed, notify |
| D-014 | warning | TASK | Claude timeout (>2h) | Kill, mark failed |
| D-020 | warning | QUEUE | Queue manager crash | Retry next cycle |
| D-021 | warning | QUEUE | JSON parse error | Skip task |
| D-030 | info | MERGE | Auto-merge failed | Leave for human |
| D-031 | info | MERGE | GitHub API unreachable | Skip merge |
| D-040 | warning | FREEZE | Events.json parse error | Treat as not frozen |
| D-041 | info | FREEZE | Project frozen | Skip task |
| D-050 | warning | SYSTEM | Disk space low (<1GB) | Warn, continue |
| D-051 | info | SYSTEM | Too many parallel tasks | Wait |

---

## D-001: Crash Loop Detected

- **Severity:** critical
- **Auto-recovery:** yes — daemon stops itself, writes blocked review-queue item
- **Symptom:** Daemon repeatedly restarts and quickly dies. Review queue has `daemon-crash-loop-blocked.md`.
- **Root cause:** Something causes the daemon to crash within seconds of starting. Common causes: bad shell config sourced by the daemon, corrupt heartbeat file, missing dependencies, disk full.

### Diagnosis

```bash
# 1. Check the crash file
cat ~/.claude-fleet/daemon-crashes

# 2. Check last errors before the crash loop
tail -20 ~/.claude-fleet/daemon-errors.log

# 3. Check if daemon is still trying to run
ps aux | grep worker-daemon | grep -v grep

# 4. Check tmux session state
tmux list-sessions 2>/dev/null | grep worker

# 5. Check system logs for OOM or other kills
log show --predicate 'process == "bash"' --last 10m 2>/dev/null | tail -20

# 6. Try running the daemon manually to see immediate errors
cd ~/Developer/claude-handler && bash -x worker-daemon.sh 2>&1 | head -50
```

### Fix

```bash
# 1. Reset the crash counter
rm -f ~/.claude-fleet/daemon-crashes

# 2. Fix the underlying issue (depends on diagnosis above)
# If heartbeat file is corrupt:
rm -f ~/.claude-fleet/daemon-heartbeat

# 3. Restart the daemon
tmux kill-session -t worker-daemon 2>/dev/null
tmux new-session -d -s worker-daemon "cd ~/Developer/claude-handler && ./worker-daemon.sh"
```

### Verify

```bash
sleep 5 && cat ~/.claude-fleet/daemon-health.json
# Should show {"status":"healthy",...}
```

### Prevention

The crash counter auto-resets after 10 minutes of stable operation. If crashes recur, the underlying cause (disk, memory, dependency) needs to be addressed.

---

## D-002: Queue Manager Not Found

- **Severity:** critical
- **Auto-recovery:** no — daemon exits
- **Symptom:** Daemon fails to start. Error log shows `[D-002]`.
- **Root cause:** `fleet-brain.py` does not exist in the script directory.

### Diagnosis

```bash
# 1. Check if file exists
ls -la ~/Developer/claude-handler/fleet-brain.py 2>&1

# 2. Check if it was renamed or moved
ls ~/Developer/claude-handler/*.py

# 3. Check git status for recently deleted files
cd ~/Developer/claude-handler && git status
```

### Fix

```bash
# If fleet-brain.py was disabled:
cd ~/Developer/claude-handler
mv fleet-brain.py.disabled fleet-brain.py 2>/dev/null

# If file is missing, restore from git:
git checkout main -- fleet-brain.py

# If neither works, ensure the repo is intact:
git fetch origin && git checkout main
```

### Verify

```bash
ls -la ~/Developer/claude-handler/fleet-brain.py && echo "OK"
```

### Prevention

Don't rename or delete fleet-brain.py without updating the daemon to handle the change.

---

## D-003: Claude CLI Not Found

- **Severity:** critical
- **Auto-recovery:** no — daemon exits
- **Symptom:** Daemon fails to start. Error log shows `[D-003]`.
- **Root cause:** Claude CLI binary not at expected path or not executable.

### Diagnosis

```bash
# 1. Check the expected path
ls -la ~/.local/bin/claude 2>&1

# 2. Check if claude is installed elsewhere
which claude 2>/dev/null || find /usr/local /opt/homebrew ~/.local -name claude -type f 2>/dev/null

# 3. Check WORKER_CLAUDE_BIN if set
echo "WORKER_CLAUDE_BIN=${WORKER_CLAUDE_BIN:-not set}"

# 4. Check if it's a permissions issue
file ~/.local/bin/claude 2>/dev/null
```

### Fix

```bash
# If claude is installed elsewhere, set the env var:
export WORKER_CLAUDE_BIN=$(which claude)

# Or symlink:
ln -sf $(which claude) ~/.local/bin/claude

# If not installed at all:
npm install -g @anthropic-ai/claude-code
```

### Verify

```bash
~/.local/bin/claude --version 2>&1 | head -1
```

### Prevention

Set `WORKER_CLAUDE_BIN` in `~/.claude-fleet/machine-role.conf` to the correct path.

---

## D-004: Stale PID File

- **Severity:** info
- **Auto-recovery:** yes — PID file is auto-cleaned
- **Symptom:** Log shows `[D-004] Stale PID file for <project>`. This is normal after a crash or force-kill.
- **Root cause:** A task process died without cleaning up its PID file (crash, OOM kill, `kill -9`).

### Diagnosis

```bash
# 1. Check which PID files exist
ls -la /tmp/fleet-running/*.pid 2>/dev/null

# 2. Check if any referenced PIDs are actually running
for f in /tmp/fleet-running/*.pid; do
  [ -f "$f" ] || continue
  pid=$(cat "$f")
  project=$(basename "$f" .pid)
  if kill -0 "$pid" 2>/dev/null; then
    echo "ALIVE: $project (pid $pid)"
  else
    echo "DEAD:  $project (pid $pid)"
  fi
done
```

### Fix

Auto-recovery handles this. If you want to manually clean:

```bash
rm -f /tmp/fleet-running/*.pid
```

### Verify

```bash
ls /tmp/fleet-running/*.pid 2>/dev/null || echo "Clean"
```

### Prevention

Normal operational noise. Only investigate if it happens very frequently (indicates tasks are being killed externally).

---

## D-005: PID File Race Condition

- **Severity:** info
- **Auto-recovery:** yes — skipped, retries next cycle
- **Symptom:** Log shows `[D-005]`. File existed at check time but disappeared when reading.
- **Root cause:** Another process (or the task completing) removed the PID file between the existence check and the read.

### Diagnosis

No action needed. This is a rare, harmless race condition.

### Fix

Auto-recovery handles this. No manual intervention needed.

### Verify

Check that the daemon continues operating normally:
```bash
cat ~/.claude-fleet/daemon-health.json
```

### Prevention

Inherent to concurrent file access. The daemon handles it gracefully.

---

## D-010: Task Manifest Missing Required Fields

- **Severity:** warning
- **Auto-recovery:** yes — task marked as failed, skipped
- **Symptom:** Log shows `[D-010]`. Task JSON is missing `id`, `prompt`, `project_path`, or `branch`.
- **Root cause:** Task was dispatched with incomplete data, or the JSON file was corrupted.

### Diagnosis

```bash
# 1. Find the task file
ls -lt ~/.claude-fleet/tasks/*.json | head -5

# 2. Check its contents (look for empty fields)
python3 -c "
import json, sys, glob
for f in sorted(glob.glob(sys.argv[1]))[-5:]:
    d = json.load(open(f))
    missing = [k for k in ['id','prompt','project_path','branch'] if not d.get(k)]
    if missing: print(f'{f}: missing {missing}')
" ~/.claude-fleet/tasks/*.json
```

### Fix

```bash
# Edit the task file to add missing fields, or re-dispatch:
# Check the original dispatch command and re-run it
```

### Verify

```bash
# Re-dispatch the task or check it's marked as failed
grep -l '"status": "failed"' ~/.claude-fleet/tasks/*.json | tail -3
```

### Prevention

Ensure `/dispatch` validates all required fields before writing the task manifest.

---

## D-011: Project Path Does Not Exist

- **Severity:** warning
- **Auto-recovery:** yes — task marked as failed
- **Symptom:** Log shows `[D-011]` with the missing path.
- **Root cause:** Project was moved, deleted, or the path in `projects.json` is wrong.

### Diagnosis

```bash
# 1. Check what path was expected
grep 'D-011' ~/.claude-fleet/daemon-errors.log | tail -3

# 2. Check projects.json
python3 -c "
import json
data = json.load(open('$HOME/.claude-fleet/projects.json'))
for p in data.get('projects', []):
    import os
    exists = os.path.isdir(p['path'])
    print(f\"{'OK' if exists else 'MISSING'}: {p['name']} -> {p['path']}\")
"
```

### Fix

```bash
# Clone the project if it's missing:
git clone <repo-url> <expected-path>

# Or update projects.json with the correct path
```

### Verify

```bash
ls -d <expected-path>
```

### Prevention

Keep `projects.json` in sync with actual directory locations.

---

## D-012: Cannot Create or Checkout Branch

- **Severity:** warning
- **Auto-recovery:** yes — task marked as failed
- **Symptom:** Log shows `[D-012]`. Git branch operations failed.
- **Root cause:** Git repo is in a bad state (detached HEAD, merge conflict, locked index), or the base branch doesn't exist.

### Diagnosis

```bash
# 1. Check the project's git state
cd <project-path>
git status
git branch -a | head -20

# 2. Check for lock files
ls -la .git/*.lock 2>/dev/null

# 3. Check if base branch exists
git show-ref --verify refs/heads/main 2>/dev/null && echo "main exists"
git show-ref --verify refs/remotes/origin/main 2>/dev/null && echo "origin/main exists"
```

### Fix

```bash
cd <project-path>

# Clean up lock files
rm -f .git/index.lock .git/HEAD.lock

# Fetch latest
git fetch origin

# If in detached HEAD:
git checkout main
```

### Verify

```bash
git checkout -b test-branch-$$ && git branch -d test-branch-$$
echo "Branch operations working"
```

### Prevention

Ensure tasks clean up git state on failure. Run `git fetch` before branch operations.

---

## D-013: Claude Exited Non-Zero

- **Severity:** warning
- **Auto-recovery:** yes — task marked as failed, notification sent
- **Symptom:** Log shows `[D-013]` with exit code and last error from the log.
- **Root cause:** Claude CLI crashed, hit max turns, or encountered a fatal error.

### Diagnosis

```bash
# 1. Check the task log
TASK_ID="<task-id>"
tail -50 ~/.claude-fleet/logs/${TASK_ID}.log

# 2. Look for specific error patterns
grep -i "error\|fatal\|panic\|exception" ~/.claude-fleet/logs/${TASK_ID}.log | tail -10

# 3. Check exit code from error log
grep "D-013.*$TASK_ID" ~/.claude-fleet/daemon-errors.log | tail -1

# 4. Check if it's a resource issue
df -h $HOME | head -2
```

### Fix

Depends on the root cause:
- **Max turns reached:** Increase `--max-turns` or break task into smaller pieces
- **CLI crash:** Check for Claude CLI updates, restart daemon
- **API error:** Check network connectivity and API status
- **Re-dispatch:** Update task prompt and re-queue

### Verify

```bash
# Re-dispatch and monitor
cat ~/.claude-fleet/daemon-health.json
```

### Prevention

Keep task prompts focused. Set realistic `--max-turns` limits. Monitor task duration.

---

## D-014: Claude Timed Out

- **Severity:** warning
- **Auto-recovery:** yes — process killed, task marked as failed
- **Symptom:** Log shows `[D-014]`. Task ran for >2 hours.
- **Root cause:** Task is too large, stuck in a loop, or waiting for external input.

### Diagnosis

```bash
# 1. Check the task log for the last activity
TASK_ID="<task-id>"
tail -100 ~/.claude-fleet/logs/${TASK_ID}.log | head -50

# 2. Check task status file
cat ~/.claude-fleet/task-status/${TASK_ID}.status
```

### Fix

```bash
# 1. Break the task into smaller subtasks
# 2. Re-dispatch with a more focused prompt
# 3. Increase TASK_TIMEOUT if the task genuinely needs more time
```

### Verify

```bash
cat ~/.claude-fleet/daemon-health.json
```

### Prevention

Keep tasks under 30-minute estimated time. Use the backlog for multi-part work.

---

## D-020: Queue Manager Python Crash

- **Severity:** warning
- **Auto-recovery:** yes — retries next poll cycle
- **Symptom:** Log shows `[D-020]`. Queue manager script failed.
- **Root cause:** Python error in fleet-brain.py — bad data, missing dependency, or code bug.

### Diagnosis

```bash
# 1. Test the queue manager directly
python3 ~/Developer/claude-handler/fleet-brain.py count-status queued 2>&1

# 2. Check for Python errors
python3 -c "import json, sqlite3, sys; print('deps OK')"

# 3. Check the fleet database
ls -la ~/.claude-fleet/fleet.db
python3 -c "
import sqlite3
conn = sqlite3.connect('$HOME/.claude-fleet/fleet.db')
print(conn.execute('SELECT count(*) FROM tasks').fetchone())
" 2>&1
```

### Fix

```bash
# If it's a corrupt database:
cp ~/.claude-fleet/fleet.db ~/.claude-fleet/fleet.db.backup
python3 -c "
import sqlite3
conn = sqlite3.connect('$HOME/.claude-fleet/fleet.db')
conn.execute('PRAGMA integrity_check')
print('DB OK')
" 2>&1

# If fleet-brain.py has a bug, update from git:
cd ~/Developer/claude-handler && git pull origin main
```

### Verify

```bash
python3 ~/Developer/claude-handler/fleet-brain.py count-status queued
```

### Prevention

Test queue manager changes before deploying to the Worker.

---

## D-021: Task JSON Parse Error

- **Severity:** warning
- **Auto-recovery:** yes — task skipped
- **Symptom:** Log shows `[D-021]`. A task manifest has invalid JSON.
- **Root cause:** File was corrupted, partially written, or hand-edited incorrectly.

### Diagnosis

```bash
# 1. Find corrupt task files
for f in ~/.claude-fleet/tasks/*.json; do
  python3 -c "import json; json.load(open('$f'))" 2>&1 | grep -q Error && echo "CORRUPT: $f"
done

# 2. Check specific file
python3 -m json.tool <corrupt-file>
```

### Fix

```bash
# Fix the JSON manually, or remove the corrupt file:
rm <corrupt-file>

# Re-dispatch the task if needed
```

### Verify

```bash
python3 -c "import json; json.load(open('<file>'))" && echo "Valid JSON"
```

### Prevention

Never hand-edit task JSON files. Use `/dispatch` to create tasks.

---

## D-030: Auto-Merge Failed

- **Severity:** info
- **Auto-recovery:** yes — PR left open for human review
- **Symptom:** Log shows `[D-030]`. PR couldn't be squash-merged.
- **Root cause:** Merge conflict, failing CI checks, or branch protection rules.

### Diagnosis

```bash
# 1. Check the PR status
gh pr view <pr-number> --repo <owner/repo> --json mergeable,statusCheckRollup

# 2. Check for conflicts
gh pr diff <pr-number> --repo <owner/repo> | head -50
```

### Fix

Manual review required. Run `/worker-review` to inspect and merge.

### Verify

```bash
gh pr view <pr-number> --repo <owner/repo> --json state
```

### Prevention

Keep Worker branches up to date with main. Avoid long-running branches.

---

## D-031: GitHub API Unreachable

- **Severity:** info
- **Auto-recovery:** yes — PR left open, merge skipped
- **Symptom:** Log shows `[D-031]`. `gh` commands are failing.
- **Root cause:** Network issue, GitHub outage, or expired auth token.

### Diagnosis

```bash
# 1. Test GitHub connectivity
gh auth status

# 2. Check network
curl -s -o /dev/null -w "%{http_code}" https://api.github.com/zen

# 3. Check token expiry
gh auth token | head -c 10
```

### Fix

```bash
# Re-authenticate:
gh auth login

# Or check network/proxy settings
```

### Verify

```bash
gh pr list --limit 1
```

### Prevention

Use long-lived tokens. Monitor GitHub status page.

---

## D-040: Events.json Parse Error

- **Severity:** warning
- **Auto-recovery:** yes — treats project as not frozen, warns
- **Symptom:** Log shows `[D-040]`. The freeze schedule file can't be parsed.
- **Root cause:** `events.json` has invalid JSON.

### Diagnosis

```bash
python3 -m json.tool ~/.claude-fleet/events.json 2>&1
```

### Fix

```bash
# Fix the JSON, or reset to empty:
echo "[]" > ~/.claude-fleet/events.json
```

### Verify

```bash
python3 -c "import json; json.load(open('$HOME/.claude-fleet/events.json')); print('OK')"
```

### Prevention

Use tooling (not manual editing) to update events.json.

---

## D-041: Project Frozen — Task Skipped

- **Severity:** info
- **Auto-recovery:** yes — task stays queued, skipped this cycle
- **Symptom:** Log shows `[D-041]`. A queued task is for a frozen project.
- **Root cause:** An event in `events.json` has a freeze window covering the current time.

### Diagnosis

```bash
# Check freeze schedule
python3 -c "
import json
from datetime import datetime, timezone
events = json.load(open('$HOME/.claude-fleet/events.json'))
now = datetime.now(timezone.utc)
for e in events:
    if e.get('freeze_projects'):
        print(f\"{e.get('title')}: {e.get('freeze_from')} -> {e.get('freeze_until')} projects={e.get('freeze_projects')}\")
"
```

### Fix

Wait for the freeze window to end, or remove the freeze event if it's no longer needed:

```bash
# Edit events.json to remove or adjust the freeze window
```

### Verify

```bash
# Task will be picked up automatically on the next poll cycle after the freeze ends
cat ~/.claude-fleet/daemon-health.json
```

### Prevention

Plan freeze windows carefully. The task will auto-run when the window expires.

---

## D-050: Disk Space Low

- **Severity:** warning
- **Auto-recovery:** yes — warns, continues operating
- **Symptom:** Log shows `[D-050]`. Less than 1GB free on the home partition.
- **Root cause:** Logs, task outputs, git repos, or npm cache filling disk.

### Diagnosis

```bash
# 1. Check disk usage
df -h $HOME

# 2. Find large directories
du -sh ~/.claude-fleet/logs/ ~/Developer/*/node_modules/ ~/.npm/ 2>/dev/null | sort -rh | head -10

# 3. Check log sizes
du -sh ~/.claude-fleet/logs/*.log 2>/dev/null | sort -rh | head -10
```

### Fix

```bash
# 1. Clean old logs (keep last 7 days)
find ~/.claude-fleet/logs/ -name "*.log" -mtime +7 -delete

# 2. Clean npm cache
npm cache clean --force

# 3. Remove old node_modules
find ~/Developer -name node_modules -type d -maxdepth 3 -exec rm -rf {} + 2>/dev/null

# 4. Clean up archived review queue items
rm -rf ~/.claude-fleet/review-queue/archived/*
```

### Verify

```bash
df -h $HOME | awk 'NR==2{print "Free: "$4}'
```

### Prevention

Set up a weekly cron to clean old logs. Monitor disk usage in `/sitrep`.

---

## D-051: Too Many Running Tasks

- **Severity:** info
- **Auto-recovery:** yes — waits, doesn't launch new tasks
- **Symptom:** Log shows `[D-051]`. All `MAX_PARALLEL` slots are in use.
- **Root cause:** Normal operation — the daemon is busy.

### Diagnosis

```bash
# Check what's running
for f in /tmp/fleet-running/*.pid; do
  [ -f "$f" ] || continue
  pid=$(cat "$f")
  project=$(basename "$f" .pid)
  if kill -0 "$pid" 2>/dev/null; then
    echo "RUNNING: $project (pid $pid)"
  fi
done

# Check task durations
ls -la ~/.claude-fleet/task-status/*.status 2>/dev/null
```

### Fix

No fix needed unless tasks are stuck. If a task is running too long:

```bash
# Kill a stuck task
kill <pid>
rm /tmp/fleet-running/<project>.pid
```

### Verify

```bash
cat ~/.claude-fleet/daemon-health.json
```

### Prevention

Normal operational state. Increase `MAX_PARALLEL` if the machine has capacity.
