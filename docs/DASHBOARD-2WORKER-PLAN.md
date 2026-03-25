# Fleet Dashboard — 2-Worker Upgrade Plan

Current dashboard at :3003 shows Mac Mini tasks only. Upgrade to show both workers.

## New Dashboard Layout

```
+----------------------------------------------------------+
|  FLEET DASHBOARD                          [3 machines]    |
+----------------------------------------------------------+
|                                                          |
|  MACHINES                                                |
|  +------------------+  +------------------+              |
|  | mac-mini (M4)    |  | dell-xps (i7)    |              |
|  | Controller + W1  |  | Worker 2         |              |
|  | CPU: 12%  RAM: 8G|  | CPU: 45% RAM: 12G|             |
|  | Tasks: 1 running |  | Tasks: 1 running |              |
|  | Uptime: 4d 12h   |  | Uptime: 1d 3h   |              |
|  | [healthy]        |  | [healthy]        |              |
|  +------------------+  +------------------+              |
|                                                          |
|  ACTIVE TASKS                                            |
|  +------------------------------------------------------+|
|  | [mac-mini] sse-streaming        DPSpice  | 12m  |||  ||
|  | [dell-xps] kron-reduction       DPSpice  |  4m  ||   ||
|  +------------------------------------------------------+|
|                                                          |
|  QUEUE (10 waiting)                                      |
|  +------------------------------------------------------+|
|  | P1  gast-governor          DPSpice   depends: kron   ||
|  | P2  flow-animation         DPSpice   depends: gast   ||
|  | P2  alarm-hmi              DPSpice   depends: flow   ||
|  | ...                                                   ||
|  +------------------------------------------------------+|
|                                                          |
|  PHASE PROGRESS                                          |
|  +------------------------------------------------------+|
|  | Tonight    [=========>          ] 5/10  50%           ||
|  | Phase 1    [                    ] 0/2    0%           ||
|  | Phase 2    [                    ] 0/3    0%           ||
|  | Phase 3    [                    ] 0/3    0%           ||
|  | Phase 4    [                    ] 0/2    0%           ||
|  | Phase 5    [                    ] 0/1    0%           ||
|  +------------------------------------------------------+|
|                                                          |
|  RECENT COMPLETIONS                                      |
|  +------------------------------------------------------+|
|  | control-blocks-exciter  DPSpice  PR #106  23m  [mac] ||
|  | bus-search-ego-graph    DPSpice  PR #98   18m  [mac] ||
|  | ...                                                   ||
|  +------------------------------------------------------+|
+----------------------------------------------------------+
```

## API Changes (dashboard/api.py)

### New endpoints

```
GET /api/machines
  Returns: [{name, role, status, cpu, ram, uptime, task_count}]
  Mac Mini: read local health file
  Dell XPS: SSH to dell-xps and read health file (cached 30s)

GET /api/machines/{name}/health
  Returns: detailed health for one machine

GET /api/phases
  Returns: [{group, tasks, completed, total, percent}]
  Groups tasks by their `group_name` field
```

### Modified endpoints

```
GET /api/tasks
  Add: `machine` field showing which worker ran/is running the task

GET /api/stats
  Add: per-machine task counts, total throughput
```

## Frontend Changes (dashboard/index.html)

### Machine Cards Section
- Card for each registered machine
- Shows: name, role, CPU/RAM (from health file), current task, uptime
- Color: green=healthy, yellow=degraded, red=down, gray=offline
- Click card to filter tasks by that machine

### Phase Progress Section
- Group tasks by `group_name` field
- Progress bar per phase
- Shows dependency chain visually
- Click phase to expand and see individual tasks

### Task Routing Indicator
- Each task row shows which machine it ran on (icon or label)
- Filter dropdown: "All machines" / "mac-mini" / "dell-xps"

## Backend Changes (worker-daemon.sh)

### Remote execution support
Add to run_task():
```bash
should_run_remote() {
    local task_id="$1" slug="$2"
    # Route engine/backend tasks to Dell if it's available
    if [[ "$slug" == *"engine"* || "$slug" == *"solver"* || \
          "$slug" == *"kron"* || "$slug" == *"governor"* || \
          "$slug" == *"validation"* || "$slug" == *"test"* ]]; then
        ssh -o ConnectTimeout=5 dell-xps "echo ok" 2>/dev/null && return 0
    fi
    return 1  # run locally
}
```

### Remote task execution
```bash
run_task_remote() {
    local task_file="$1" remote_host="$2"
    # Sync task files to remote
    scp "$task_file" "$remote_host:~/.claude-fleet/tasks/"
    # Start Claude session on remote via SSH
    ssh "$remote_host" "cd $project_path && \
        claude -p --dangerously-skip-permissions \
        --max-turns $max_turns \
        --append-system-prompt '$worker_prompt' \
        '$task_prompt'" 2>&1 | tee "$log_file"
}
```

### Health collection from Dell
```bash
collect_remote_health() {
    ssh -o ConnectTimeout=5 dell-xps \
        "cat ~/.claude-fleet/daemon-health.json 2>/dev/null" \
        > "$FLEET_DIR/remote-health/dell-xps.json" 2>/dev/null || true
}
```

## Database Changes (task-db.py)

### New column
```sql
ALTER TABLE tasks ADD COLUMN machine TEXT DEFAULT 'mac-mini';
```

### Track which machine ran each task
When claiming a task, set `machine` based on routing decision.

## Implementation Order

1. Add `machine` column to tasks DB
2. Add remote health collection to daemon
3. Add machine cards to dashboard frontend
4. Add phase progress grouping to dashboard
5. Add routing logic to daemon (should_run_remote)
6. Add remote execution to daemon (run_task_remote)
7. Test end-to-end: dispatch task, verify it runs on Dell, results visible on dashboard
