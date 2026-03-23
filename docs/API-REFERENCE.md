# API Reference — Fleet Infrastructure

APIs provided by the claude-handler fleet system.

## Fleet Dashboard API (port 3003)

**Location:** `dashboard/api.py`
**Database:** SQLite (`~/.claude-fleet/fleet.db`) + JSON task files
**Framework:** FastAPI

### Task Management

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/tasks` | List all tasks |
| GET | `/api/review` | List items in review queue |
| POST | `/api/action` | Execute action (merge, dismiss, retry) |
| GET | `/api/backlog` | List backlog items |
| GET | `/api/queue` | Current task queue by project |

### Project Status

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/projects` | List all registered projects with status |
| GET | `/api/projects/lines` | Lines of code per project |
| GET | `/api/git-status/{project}` | Git status for a specific project |
| GET | `/api/services` | Status of all running services |
| GET | `/api/system` | System metrics (CPU, RAM, disk, uptime) |

### Analytics

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/stats/daily` | Daily completion counts |
| GET | `/api/stats/projects` | Breakdown by project |
| GET | `/api/stats/queue-depth` | Queue depth over time |
| GET | `/api/stats/auto-heal` | Auto-heal log entries |
| GET | `/api/stats/task-history` | Task timeline |
| GET | `/api/stats/analytics` | Combined analytics data |
| GET | `/api/stats/cumulative` | Cumulative completions (14 day) |
| GET | `/api/stats/recent-completions` | Recent completed tasks |
| GET | `/api/stats/throughput` | Daily throughput |
| GET | `/api/costs` | Estimated API costs |
| GET | `/api/timeline` | Task timeline view |

### Notifications

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/notifications` | List notifications |
| GET | `/api/notifications/status` | Notification system status |
| POST | `/api/notifications/test` | Send test notification |
| POST | `/api/notifications/preferences` | Update preferences |

### Events and Logs

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/events` | List system events |
| POST | `/api/events` | Log a new event |
| GET | `/api/logs/{task_id}` | Get logs for a specific task |
| GET | `/api/logs` | List all log files |
| GET | `/api/debug` | Debug information |

## Health Monitor

**Location:** `health-monitor.py`
**Runs as:** Background process
**Interval:** Every 60 seconds

Monitors all fleet services and auto-fixes common issues:

| Check | Auto-fix |
|-------|----------|
| API server responding | Restart process |
| Dev server responding with correct content | Clear cache, restart |
| Git local matches remote | Reset to origin |
| Dashboard responding | Restart |
| Worker daemon alive | Restart |

Log: `~/.claude-fleet/logs/health-monitor.log`

## Supporting Scripts

| Script | Purpose |
|--------|---------|
| `worker-daemon.sh` | Watches task queue, runs Claude sessions back-to-back |
| `fleet-startup.sh` | Starts all services on boot |
| `fleet-supervisor.sh` | Keeps tmux sessions alive via launchd |
| `sync-to-secondary.sh` | Sync fleet state to second machine |
| `memory-sync.sh` | Sync memory files between machines |

## Data Flow

```
Fleet Dashboard (port 3003)
    |
    +--> SQLite DB (fleet.db) <-- sync from JSON every 30s
    |
    +--> JSON task files (~/.claude-fleet/tasks/*.json)
    |
    +--> Git status (subprocess calls)
    |
    +--> System metrics (psutil)

Health Monitor (background)
    |
    +--> Checks all services every 60s
    +--> Auto-restarts failed services
    +--> Logs to ~/.claude-fleet/logs/health-monitor.log

Worker Daemon
    |
    +--> Polls task queue every 30s
    +--> Picks oldest "queued" task
    +--> Runs Claude session autonomously
    +--> Updates task status on completion
```
