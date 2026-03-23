# /sitrep — Fleet Situation Report

Quick health check of the entire fleet: daemon, tasks, errors, and queue state. No SSH required — reads local files only.

## Steps

### Step 1: Daemon health

Read `~/.claude-fleet/daemon-health.json`. This is a one-line JSON file updated every poll cycle:
```json
{"status":"healthy","uptime":3600,"running":1,"queued":3,"crashes":0,"last_error":null,"cycle":120}
```

If the file doesn't exist or is older than 2 minutes, the daemon is likely down.

### Step 2: Heartbeat freshness

Read `~/.claude-fleet/daemon-heartbeat`:
```
timestamp=<epoch> running=<N> queued=<N> idle_since=<epoch|0> uptime=<seconds> cycle=<N>
```

Calculate staleness: `now - timestamp`. If >120 seconds, flag as stale — daemon may be dead or frozen.

### Step 3: Crash history

Read `~/.claude-fleet/daemon-crashes` (if exists):
```
count=<N> first=<epoch> last=<epoch>
```

If count > 0, report how many crashes and when the last one was.

### Step 4: Recent errors

Read the last 10 lines of `~/.claude-fleet/daemon-errors.log` (if exists). Each line is:
```
<ISO timestamp> [D-XXX] description
```

Group by error code prefix if there are many. Reference `ERROR_CODES.md` for the full catalog.

### Step 5: Running tasks

Read all `~/.claude-fleet/task-status/*.status` files. Each contains:
```
phase=running
last_activity=<epoch>
pid=<pid>
project=<name>
branch=<branch>
started_at=<epoch>
msg=<last status message>
```

For each running task, calculate duration and check if `last_activity` is stale (>5 min).

### Step 6: Queue summary

```bash
# Count tasks by status
for status in queued running completed failed blocked merged; do
  count=$(grep -l "\"status\": \"$status\"" ~/.claude-fleet/tasks/*.json 2>/dev/null | wc -l)
  echo "$status: $count"
done
```

### Step 7: Review queue

```bash
ls ~/.claude-fleet/review-queue/*.md 2>/dev/null | grep -v archived
```

Count items by type (completed, failed, blocked, decision_needed).

### Step 8: Present the sitrep

Format as a compact dashboard:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FLEET SITREP — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Daemon:   HEALTHY | uptime 2h 15m | cycle 270 | 0 crashes
Heartbeat: 12s ago (fresh)

Tasks:    1 running | 3 queued | 12 completed | 0 failed
Review:   2 items pending (1 completed, 1 decision)

Running:
  claude-handler    worker/daemon-obs-20260323   18m   "Claude session active"
  dpspice           worker/solar-pv-20260323     42m   "Running tests"

Recent errors (last 5):
  22:05:12  [D-004] Stale PID file for dpspice (pid 12345 dead)
  21:58:03  [D-020] Queue manager crash on count-status

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Health indicators

- **HEALTHY**: daemon-health.json says "healthy", heartbeat <60s old, 0 crashes
- **DEGRADED**: heartbeat 60-120s old, or 1-4 crashes, or disk space warning
- **DOWN**: heartbeat >120s old or missing, or daemon-health.json missing
- **CRASH LOOP**: 5+ crashes logged in daemon-crashes

### Quick checks

If the user just wants a yes/no:
```bash
# Is the daemon alive?
cat ~/.claude-fleet/daemon-health.json 2>/dev/null || echo "DAEMON DOWN"
```
