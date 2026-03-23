# Fleet Worker Daemon — Error Code Catalog

All daemon errors are logged as `[D-XXX] description` in both stdout and `~/.claude-fleet/daemon-errors.log`.

| Code | Category | Description | Auto-recovery |
|------|----------|-------------|---------------|
| D-001 | DAEMON | Crash loop detected (5+ restarts in 5 min) | Stop daemon, write blocked review-queue item |
| D-002 | DAEMON | Queue manager not found | Exit with message |
| D-003 | DAEMON | Claude CLI not found or not executable | Exit with message |
| D-004 | PID | Stale PID file (process dead) | Auto-clean PID file, log |
| D-005 | PID | PID file race condition (disappeared between check and read) | Skip, retry next cycle |
| D-010 | TASK | Task manifest missing required fields | Mark task failed, skip |
| D-011 | TASK | Project path does not exist | Mark task failed, skip |
| D-012 | TASK | Cannot create or checkout branch | Mark task failed, skip |
| D-013 | TASK | Claude exited non-zero | Mark task failed, notify |
| D-014 | TASK | Claude timed out (>2 hours) | Kill process, mark failed, notify |
| D-020 | QUEUE | Queue manager Python crash | Log, retry next cycle |
| D-021 | QUEUE | Task JSON parse error | Skip task, log |
| D-030 | MERGE | Auto-merge failed (conflict or CI) | Leave PR open for human review |
| D-031 | MERGE | GitHub API unreachable | Skip merge, leave PR open |
| D-040 | FREEZE | Events.json parse error | Treat project as not frozen, warn |
| D-041 | FREEZE | Project frozen, task skipped | Log, skip task |
| D-050 | SYSTEM | Disk space low (<1GB) | Warn, continue |
| D-051 | SYSTEM | Too many running tasks (>MAX_PARALLEL) | Wait, don't launch new tasks |

## Files

| File | Purpose |
|------|---------|
| `~/.claude-fleet/daemon-heartbeat` | Per-cycle heartbeat with timestamp, running/queued counts, uptime, cycle |
| `~/.claude-fleet/daemon-health.json` | One-line JSON health summary (status, uptime, crashes, last_error) |
| `~/.claude-fleet/daemon-crashes` | Crash counter: `count=N first=<epoch> last=<epoch>` |
| `~/.claude-fleet/daemon-errors.log` | Append-only error log, one line per error with ISO timestamp |
| `~/.claude-fleet/task-status/<id>.status` | Per-task progress: phase, PID, project, branch, last activity |

## Grepping for errors

```bash
# All errors
grep '\[D-' ~/.claude-fleet/daemon-errors.log

# Specific category
grep '\[D-01' ~/.claude-fleet/daemon-errors.log   # Task errors
grep '\[D-02' ~/.claude-fleet/daemon-errors.log   # Queue errors
grep '\[D-05' ~/.claude-fleet/daemon-errors.log   # System errors

# Last 10 errors
tail -10 ~/.claude-fleet/daemon-errors.log
```
