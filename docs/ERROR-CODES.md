# Fleet Error Code Reference

All errors are logged with a code prefix for greppability and automated repair.

## Daemon Errors (D-xxx)

Emitted by `worker-daemon.sh`. Logged to `~/.claude-fleet/daemon-errors.log`.

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| D-001 | Critical | Crash restart detected. Daemon restarted within 60s of last heartbeat. 5+ in 5 min = stop. | Auto-stops after 5. Manual restart required. |
| D-002 | Fatal | Queue manager not found (fleet-brain.py). Daemon cannot start. | Reinstall claude-handler. |
| D-003 | Fatal | Claude CLI not found or not executable. | Install Claude CLI to `~/.local/bin/claude`. |
| D-004 | Warning | Stale PID file. Process died without cleanup. | Auto-cleaned. PID file removed. |
| D-005 | Warning | PID file race condition. File disappeared between existence check and read. | Auto-cleaned. |
| D-010 | Error | Task manifest missing required fields (id, prompt, project_path, branch). | Task marked failed. Fix JSON and re-queue. |
| D-011 | Error | Project path does not exist. | Task marked failed. Check `projects.json` paths. |
| D-012 | Error | Cannot create or checkout branch. | Task marked failed. Check git state of project. |
| D-013 | Error | Claude exited non-zero. Task failed during execution. | Task marked failed. Check task log. |
| D-014 | Error | Prompt file not found. The `.prompt` file referenced in the manifest doesn't exist. | Task skipped. Re-dispatch with valid prompt. |
| D-015 | Error | Prompt too short (<10 chars). Likely a dispatch failure. | Task marked failed. Re-dispatch. |
| D-020 | Warning | Queue manager Python crash. | Falls back to JSON scanning. Check Python deps. |
| D-021 | Warning | Task JSON parse error. Corrupted manifest file. | Task skipped. Regenerate JSON. |
| D-030 | Warning | Auto-merge failed. GitHub API error or merge conflict. | PR left for human review. |
| D-031 | Warning | GitHub API unreachable or no open PR for branch. | Check `gh auth status` and network. |
| D-040 | Warning | Events.json parse error. | Project treated as not frozen. Fix events.json. |
| D-041 | Info | Project is frozen (event-based freeze window). Task skipped. | Wait for freeze window to end. |
| D-050 | Warning | Disk space low (<1GB free). Daemon status set to degraded. | Free disk space. |
| D-060 | Warning | Claimed task from SQLite but JSON file missing. | Auto-created from DB data. |
| D-070 | Warning | Evaluator session crashed. | Skip evaluation, proceed to review queue. |
| D-071 | Warning | Verdict file not found after evaluator session. | Treat as UNKNOWN, proceed. |
| D-072 | Warning | Verdict file contains malformed JSON. | Treat as UNKNOWN, proceed. |
| D-073 | Warning | Generator retry failed after evaluator critique. | Mark eval as FAIL, proceed to review. |

## Diagnostic Errors (FD-xxx)

Emitted by `fleet-diagnose.py`. Run `python3 fleet-diagnose.py --json` for automation.

### Daemon Health (FD-1xx)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-100 | Critical | Daemon not running. No `worker-daemon.sh` process found. | Restart: `tmux new-session -d -s worker-daemon '...'` |
| FD-101 | Critical | Heartbeat stale (>2 min old). Daemon may be hung. | Restart daemon. |
| FD-102 | Critical | Crash loop (3+ restarts). Daemon stopped itself. | `rm ~/.claude-fleet/daemon-crashes`, then restart. |
| FD-103 | Warning | Daemon reports degraded health. | Check `~/.claude-fleet/daemon-health.json`. |

### Database (FD-11x)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-110 | Critical | SQLite DB missing or corrupt. | `python3 task-db.py init` |
| FD-111 | Warning | JSON and SQLite task statuses disagree. | `python3 task-db.py import-json` |
| FD-112 | Critical | Tasks marked "running" with no backing process. Ghost tasks. | `python3 task-db.py recover-stuck --minutes 0` |
| FD-113 | Warning | Tasks stuck: no heartbeat or log frozen for 10+ min. | `python3 task-db.py recover-stuck --minutes 10` |
| FD-114 | Critical | Queue deadlocked. All queued tasks blocked by dead running tasks. | `python3 task-db.py recover-stuck --minutes 10` |

### Dependencies (FD-12x)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-120 | Critical | Claude CLI not found at `~/.local/bin/claude`. | Install Claude CLI. |
| FD-121 | Info | `setsid` not found. Expected on macOS. Daemon uses `tee` instead. | None needed. |
| FD-122 | Warning | `stdbuf` not found. Log capture may buffer. | `brew install coreutils` |
| FD-123 | Warning | `gh` CLI not found or not authenticated. | `brew install gh && gh auth login` |

### Processes (FD-13x)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-130 | Warning | Stale PID files. Process dead but PID file remains. | `rm /tmp/fleet-running/*.pid` |
| FD-131 | Warning | Orphaned Claude processes. Running without daemon parent. | Investigate manually. May be interactive sessions. |
| FD-132 | Warning | Zombie child processes. | `kill -9 <pid>` |

### Resources (FD-14x)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-140 | Critical | Disk space <1GB free. | Free disk space. |
| FD-141 | Warning | Log directory >1GB. Old logs accumulating. | `find ~/.claude-fleet/logs -name '*.log' -mtime +7 -delete` |
| FD-142 | Warning | >500 task JSON files. Consider archiving. | Archive old completed task files. |

### Tasks (FD-15x)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-150 | Warning | Prompt file paths with double prefix (absolute path prepended with TASKS_DIR). | Fixed in daemon code. Re-dispatch affected tasks. |
| FD-151 | Warning | Task JSON missing required fields (id, project_path, branch). | Fix or regenerate the manifest. |
| FD-152 | Warning | Task JSON parse error. File is corrupted. | Delete and re-dispatch. |

### Review Queue (FD-16x)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-160 | Info | Unprocessed review queue items. | Run `/worker-review` from Commander. |
| FD-161 | Warning | Review items older than 24h. May be stale. | Review or archive. |

### Git (FD-17x)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-170 | Info | Project repo on non-main branch. | `git checkout main` in the project. |
| FD-171 | Warning | Unpushed commits on a project. | `git push origin main` in the project. |
| FD-172 | Warning | Uncommitted changes in a project. | Commit or stash. |

### Infrastructure (FD-18x)

| Code | Severity | Description | Auto-fix |
|------|----------|-------------|----------|
| FD-180 | Warning | Required tmux session missing (worker-daemon). | Recreate the tmux session. |
| FD-181 | Warning | Fleet directory structure incomplete. | `mkdir -p ~/.claude-fleet/{tasks,logs,review-queue}` |

## Usage

```bash
# Run all checks
python3 fleet-diagnose.py

# JSON output for automation
python3 fleet-diagnose.py --json

# Auto-fix all fixable issues
python3 fleet-diagnose.py --fix

# Check specific category
python3 fleet-diagnose.py --check database
python3 fleet-diagnose.py --check daemon

# Grep daemon error log for specific code
grep "D-013" ~/.claude-fleet/daemon-errors.log

# Check for stuck tasks
python3 task-db.py stuck --minutes 10

# Auto-recover stuck tasks
python3 task-db.py recover-stuck --minutes 10
```
