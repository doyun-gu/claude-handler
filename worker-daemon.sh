#!/bin/bash
# worker-daemon.sh — Autonomous Worker daemon for Mac Mini
# Watches the task queue and runs Claude sessions continuously.
# Usage: ./worker-daemon.sh [--poll-interval 30]
#
# Start in tmux on Mac Mini:
#   tmux new-session -d -s worker-daemon "cd ~/Developer/claude-handler && ./worker-daemon.sh"

# Use set -u for unbound variable detection, but NOT set -e.
# set -e causes silent crashes in daemons — we handle errors explicitly.
set -uo pipefail

# ─── Singleton guard ──────────────────────────────────────────────────────────
# Refuse to start if another worker-daemon.sh is already running. Prevents the
# orphan-daemon problem (multiple copies polling tasks.db simultaneously).
# Walks our own process ancestry so tmux/zsh/tee wrappers don't false-positive,
# then re-checks after a short delay to skip processes that are still dying
# (race during supervisor-triggered respawn, when the previous daemon hasn't
# yet finished cleanup).
check_singleton() {
    local candidates
    candidates=$(pgrep -f 'worker-daemon\.sh' 2>/dev/null | grep -v "^$$\$" | grep -v "^$PPID\$")
    [[ -n "$candidates" ]] || return 0

    local ancestry="$$ $PPID" p="$PPID"
    while [[ -n "$p" && "$p" != "1" && "$p" != "0" ]]; do
        p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
        [[ -n "$p" ]] && ancestry="$ancestry $p"
    done

    local pid
    for pid in $candidates; do
        grep -qw "$pid" <<<"$ancestry" && continue
        echo "$pid"
        return 1
    done
    return 0
}

FOREIGN_DAEMON=$(check_singleton) || true
if [[ -n "$FOREIGN_DAEMON" ]]; then
    # Race-tolerance: during a supervisor respawn, the previous daemon is
    # still winding down. Wait briefly and re-check before declaring conflict.
    sleep 3
    if kill -0 "$FOREIGN_DAEMON" 2>/dev/null; then
        FOREIGN_DAEMON=$(check_singleton) || true
        if [[ -n "$FOREIGN_DAEMON" ]]; then
            echo "[daemon $(date +%H:%M:%S)] ERROR: another worker-daemon already running (PID $FOREIGN_DAEMON). Exiting."
            echo "[daemon $(date +%H:%M:%S)] Run: kill $FOREIGN_DAEMON  — then restart this daemon."
            exit 1
        fi
    fi
fi

# ─── Configuration ────────────────────────────────────────────────────────────

FLEET_DIR="$HOME/.claude-fleet"
TASKS_DIR="$FLEET_DIR/tasks"
LOGS_DIR="$FLEET_DIR/logs"
REVIEW_DIR="$FLEET_DIR/review-queue"
EVENTS_FILE="$FLEET_DIR/events.json"
RUNNING_DIR="/tmp/fleet-running"
TASK_STATUS_DIR="$FLEET_DIR/task-status"
HEARTBEAT_FILE="$FLEET_DIR/daemon-heartbeat"
HEALTH_FILE="$FLEET_DIR/daemon-health.json"
CRASH_FILE="$FLEET_DIR/daemon-crashes"
ERROR_LOG="$FLEET_DIR/daemon-errors.log"
POLL_INTERVAL="${1:-30}"
IDLE_SINCE=0
MAX_PARALLEL=3
DAEMON_START=$(date +%s)
CYCLE_COUNT=0
LAST_ERROR=""
TASK_TIMEOUT="${TASK_TIMEOUT:-7200}"  # 2 hours in seconds (configurable via env)

# ─── Colors & logging ────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[daemon $(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[daemon $(date +%H:%M:%S)]${NC} $1"; }
err()  { echo -e "${RED}[daemon $(date +%H:%M:%S)]${NC} $1"; }
ok()   { echo -e "${GREEN}[daemon $(date +%H:%M:%S)]${NC} $1"; }

# ─── Error code logging ─────────────────────────────────────────────────────
# All errors logged as "[D-XXX] description" for greppability.
# Also appended to daemon-errors.log (append-only, one line per error).

log_error() {
    local code="$1" msg="$2"
    local ts
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    err "[$code] $msg"
    echo "$ts [$code] $msg" >> "$ERROR_LOG"
    LAST_ERROR="$code: $msg"
}

# ─── Rate limit detection ─────────────────────────────────────────────────────
# Checks a log file for rate limit messages. Returns 0 if rate-limited.
# Usage: check_rate_limit "$log_file" && { handle it }

check_rate_limit() {
    local check_log="$1"
    [[ ! -f "$check_log" || ! -s "$check_log" ]] && return 1
    tail -20 "$check_log" 2>/dev/null | grep -qiE "hit your limit|rate limit|too many requests|429|quota exceeded" 2>/dev/null
}

# Calculates seconds to sleep until rate limit resets. Parses "resets Xpm/am" from log.
# Falls back to 30 minutes if no reset time found.
get_rate_limit_sleep() {
    local check_log="$1"
    local reset_hour=""
    reset_hour=$(tail -20 "$check_log" 2>/dev/null | grep -oE 'resets [0-9]{1,2}(am|pm|AM|PM)' | grep -oE '[0-9]{1,2}(am|pm|AM|PM)' | tail -1) || reset_hour=""

    local sleep_seconds=1800  # default: 30 minutes
    if [[ -n "$reset_hour" ]]; then
        local hour_num ampm now_epoch target_epoch
        hour_num=$(echo "$reset_hour" | grep -oE '[0-9]+')
        ampm=$(echo "$reset_hour" | grep -oE '(am|pm|AM|PM)')
        if [[ "$ampm" =~ [pP][mM] && "$hour_num" -ne 12 ]]; then
            hour_num=$((hour_num + 12))
        elif [[ "$ampm" =~ [aA][mM] && "$hour_num" -eq 12 ]]; then
            hour_num=0
        fi
        now_epoch=$(date +%s)
        target_epoch=$(date -j -v"${hour_num}"H -v0M -v0S +%s 2>/dev/null) || target_epoch=""
        if [[ -n "$target_epoch" ]]; then
            if (( target_epoch <= now_epoch )); then
                target_epoch=$((target_epoch + 86400))
            fi
            sleep_seconds=$((target_epoch - now_epoch + 120))  # +2 min buffer
        fi
    fi
    echo "$sleep_seconds"
}

# ─── Script directory (fail fast if unresolvable) ─────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$SCRIPT_DIR" || ! -d "$SCRIPT_DIR" ]]; then
    echo "FATAL: Cannot resolve script directory" >&2
    exit 1
fi

# ─── Directories ──────────────────────────────────────────────────────────────

mkdir -p "$TASKS_DIR" "$LOGS_DIR" "$REVIEW_DIR" "$RUNNING_DIR" "$TASK_STATUS_DIR"

# ─── Machine role ─────────────────────────────────────────────────────────────

if [[ ! -f "$FLEET_DIR/machine-role.conf" ]]; then
    err "No machine-role.conf found. Run install.sh first."
    exit 1
fi
# shellcheck source=/dev/null
source "$FLEET_DIR/machine-role.conf"
if [[ "${MACHINE_ROLE:-}" != "worker" ]]; then
    warn "MACHINE_ROLE is '${MACHINE_ROLE:-unset}', not 'worker'. Proceeding anyway..."
fi

# ─── Claude CLI ───────────────────────────────────────────────────────────────

CLAUDE_BIN="${WORKER_CLAUDE_BIN:-$HOME/.local/bin/claude}"
if [[ ! -x "$CLAUDE_BIN" ]]; then
    log_error "D-003" "Claude CLI not found or not executable at $CLAUDE_BIN"
    exit 1
fi

# ─── Remote workers ──────────────────────────────────────────────────────────
# Workers are defined in ~/.claude-fleet/workers.json (optional).
# Format: [{"name": "worker-2", "ssh": "worker-2", "claude_bin": "$HOME/.local/bin/claude",
#            "topics": ["engine","test","solver"], "project_paths": {
#              "my-project": "$HOME/Developer/my-project"}}]
# If the file doesn't exist, all tasks run locally.

WORKERS_FILE="$FLEET_DIR/workers.json"
HAS_REMOTE_WORKERS=false
[[ -f "$WORKERS_FILE" ]] && HAS_REMOTE_WORKERS=true

# Determine which worker should run a task (local or remote)
# Returns: "local" or the worker SSH name (e.g., "dell-xps")
route_task() {
    local task_file="$1"
    [[ "$HAS_REMOTE_WORKERS" == "false" ]] && { echo "local"; return; }

    # Check explicit route in task JSON
    local explicit_route
    explicit_route=$(task_field "$task_file" route "")
    if [[ -n "$explicit_route" ]]; then
        echo "$explicit_route"
        return
    fi

    # Auto-route by topic affinity
    local slug_lower
    slug_lower=$(echo "$(task_field "$task_file" slug "")" | tr '[:upper:]' '[:lower:]')

    local worker
    worker=$(python3 -c "
import json, sys

slug = '${slug_lower}'
workers = json.load(open('${WORKERS_FILE}'))

# Check each worker's topic affinity
for w in workers:
    for topic in w.get('topics', []):
        if topic in slug:
            print(w['ssh'])
            sys.exit(0)

# No match = run locally
print('local')
" 2>/dev/null) || worker="local"

    echo "$worker"
}

# Get remote project path for a worker
remote_project_path() {
    local worker_ssh="$1" project_name="$2" local_path="$3"
    [[ "$worker_ssh" == "local" ]] && { echo "$local_path"; return; }

    local remote_path
    remote_path=$(python3 -c "
import json
workers = json.load(open('${WORKERS_FILE}'))
for w in workers:
    if w['ssh'] == '${worker_ssh}':
        print(w.get('project_paths', {}).get('${project_name}', ''))
        break
" 2>/dev/null) || remote_path=""

    # Fallback: mirror the local path structure under ~/Developer
    if [[ -z "$remote_path" ]]; then
        remote_path="$HOME/Developer/$(basename "$(dirname "$local_path")")/$(basename "$local_path")"
    fi
    echo "$remote_path"
}

# Check if a remote worker is reachable
check_remote_worker() {
    local worker_ssh="$1"
    ssh -o ConnectTimeout=5 -o BatchMode=yes "$worker_ssh" "echo ok" &>/dev/null
}

# ─── Queue manager ────────────────────────────────────────────────────────────

if [[ -f "$SCRIPT_DIR/fleet-brain.py" ]]; then
    QM="$SCRIPT_DIR/fleet-brain.py"
    log "Using fleet-brain.py"
else
    log_error "D-002" "Queue manager not found (fleet-brain.py)"
    exit 1
fi

# ─── Safe wrappers for queue manager calls ────────────────────────────────────
# These never crash the daemon — they return empty/default on failure.

task_field() {
    local result
    result=$(python3 "$QM" task-field "$@" 2>&1) || {
        local err_snippet="${result:0:100}"
        if [[ "$err_snippet" == *"json"* || "$err_snippet" == *"JSON"* || "$err_snippet" == *"decode"* ]]; then
            log_error "D-021" "Task JSON parse error: $err_snippet"
        fi
        echo ""
        return 1
    }
    echo "$result"
}

TASK_DB="$SCRIPT_DIR/task-db.py"
FILE_LOCK="$SCRIPT_DIR/file-lock.py"

count_tasks() {
    # Primary: SQLite
    if [[ -f "$TASK_DB" ]]; then
        local count
        count=$(python3 "$TASK_DB" count "$1" 2>/dev/null) || count=""
        if [[ -n "$count" ]]; then
            echo "$count"
            return 0
        fi
    fi
    # Fallback: queue manager (JSON)
    local result
    result=$(python3 "$QM" count-status "$1" 2>&1) || {
        log_error "D-020" "Queue manager crash on count-status: ${result:0:100}" >&2
        echo "0"
        return 1
    }
    echo "${result:-0}"
}

update_task_status() {
    local task_file="$1" new_status="$2"
    shift 2
    local qm_err task_id

    # Update JSON file via fleet-brain
    qm_err=$(python3 "$QM" update-status "$task_file" "$new_status" "$@" 2>&1)
    if [[ $? -ne 0 ]]; then
        log_error "D-020" "Fleet-brain failed for $task_file -> $new_status: ${qm_err:0:200}"
        # Fallback: update JSON directly when fleet-brain fails
        python3 -c "
import json, sys
from datetime import datetime, timezone
f = '$task_file'
try:
    d = json.loads(open(f).read())
    d['status'] = '$new_status'
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    if '$new_status' == 'running': d['started_at'] = now
    elif '$new_status' in ('completed','failed','blocked'): d['finished_at'] = now
    open(f, 'w').write(json.dumps(d, indent=2))
except Exception as e:
    print(f'D-020-FALLBACK: {e}', file=sys.stderr)
" 2>>"$ERROR_LOG" || log_error "D-020" "JSON fallback also failed for $task_file"
    fi

    # Update SQLite (primary source of truth)
    if [[ -f "$TASK_DB" ]]; then
        task_id=$(task_field "$task_file" id "") 2>/dev/null
        if [[ -n "$task_id" ]]; then
            local db_err
            db_err=$(python3 "$TASK_DB" status "$task_id" "$new_status" "$@" 2>&1)
            if [[ $? -ne 0 ]]; then
                log_error "D-022" "task-db.py failed for $task_id -> $new_status: ${db_err:0:200}"
            fi
        fi
    fi
}

# Import any new JSON tasks into SQLite (bridge: JSON files -> DB)
sync_json_to_db() {
    if [[ -f "$TASK_DB" ]]; then
        python3 "$TASK_DB" import-json 2>/dev/null
    fi
}

# ─── Safe file read (TOCTOU-resistant) ────────────────────────────────────────

read_pidfile() {
    local pidfile="$1"
    local pid=""
    pid=$(cat "$pidfile" 2>/dev/null) || return 1
    [[ -n "$pid" ]] && echo "$pid" || return 1
}

# ─── Crash detection ────────────────────────────────────────────────────────
# On startup, check if the previous daemon died recently (within 60s).
# If so, increment crash counter. After 5 crashes in 5 min, stop.

detect_crash_restart() {
    local now
    now=$(date +%s)

    if [[ -f "$HEARTBEAT_FILE" ]]; then
        local last_ts=0
        last_ts=$(sed -n 's/.*timestamp=\([0-9]*\).*/\1/p' "$HEARTBEAT_FILE" 2>/dev/null) || last_ts=0
        local delta=$(( now - last_ts ))

        if (( delta < 60 && delta >= 0 )); then
            # This looks like a crash-restart
            local crash_count=0 first_crash_ts="$now"

            if [[ -f "$CRASH_FILE" ]]; then
                crash_count=$(sed -n 's/.*count=\([0-9]*\).*/\1/p' "$CRASH_FILE" 2>/dev/null) || crash_count=0
                first_crash_ts=$(sed -n 's/.*first=\([0-9]*\).*/\1/p' "$CRASH_FILE" 2>/dev/null) || first_crash_ts="$now"
            fi

            crash_count=$((crash_count + 1))
            local window=$(( now - first_crash_ts ))

            # Reset window if >5 minutes have passed since first crash
            if (( window > 300 )); then
                crash_count=1
                first_crash_ts="$now"
            fi

            echo "count=$crash_count first=$first_crash_ts last=$now" > "$CRASH_FILE"

            local last_known_err=""
            [[ -f "$ERROR_LOG" ]] && last_known_err=$(tail -1 "$ERROR_LOG" 2>/dev/null | head -c 200)
            log_error "D-001" "Crash restart detected (count: $crash_count, last error: ${last_known_err:-unknown})"

            if (( crash_count >= 5 )); then
                log_error "D-001" "5+ restarts in 5 minutes — stopping daemon to prevent crash loop"

                cat > "$REVIEW_DIR/daemon-crash-loop-blocked.md" << CRASH_EOF
---
task_id: daemon-crash-loop
project: fleet-infrastructure
type: blocked
priority: critical
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Daemon Crash Loop Detected

The worker daemon has restarted $crash_count times in the last $((window)) seconds.

**Last known error:** ${last_known_err:-none}

Check the logs:
- Error log: ~/.claude-fleet/daemon-errors.log
- Crash file: ~/.claude-fleet/daemon-crashes

The daemon has stopped itself. Investigate and restart manually.
CRASH_EOF
                exit 1
            fi
        fi
    fi
}

# Reset crash counter after 10 minutes of stable operation
reset_crash_counter_if_stable() {
    [[ -f "$CRASH_FILE" ]] || return 0
    local now last_crash
    now=$(date +%s)
    last_crash=$(sed -n 's/.*last=\([0-9]*\).*/\1/p' "$CRASH_FILE" 2>/dev/null) || return 0
    if (( now - last_crash > 600 )); then
        rm -f "$CRASH_FILE"
        log "Crash counter reset after 10 minutes of stable operation"
    fi
}

# ─── Heartbeat & health ─────────────────────────────────────────────────────

write_heartbeat() {
    local running_count="$1" queued_count="$2"
    local now
    now=$(date +%s)
    local uptime=$(( now - DAEMON_START ))
    local idle_val="${IDLE_SINCE:-0}"
    echo "timestamp=$now running=$running_count queued=$queued_count idle_since=$idle_val uptime=$uptime cycle=$CYCLE_COUNT" > "$HEARTBEAT_FILE"
}

daemon_health() {
    local running_count="$1" queued_count="$2"
    local now
    now=$(date +%s)
    local uptime=$(( now - DAEMON_START ))
    local crash_count=0
    [[ -f "$CRASH_FILE" ]] && crash_count=$(sed -n 's/.*count=\([0-9]*\).*/\1/p' "$CRASH_FILE" 2>/dev/null)
    crash_count="${crash_count:-0}"
    local last_err="null"
    if [[ -n "$LAST_ERROR" ]]; then
        # Escape quotes and truncate for JSON safety
        local escaped
        escaped=$(echo "$LAST_ERROR" | sed 's/"/\\"/g' | head -c 200)
        last_err="\"$escaped\""
    fi

    local status="healthy"
    if (( crash_count >= 3 )); then
        status="degraded"
    fi

    # Check disk space (warn if <1GB free)
    local free_kb
    free_kb=$(df -k "$HOME" 2>/dev/null | awk 'NR==2{print $4}') || free_kb=999999999
    if (( free_kb < 1048576 )); then
        status="degraded"
        log_error "D-050" "Disk space low: $((free_kb / 1024))MB free (<1GB)"
    fi

    cat > "$HEALTH_FILE" << HEALTH_EOF
{"status":"$status","uptime":$uptime,"running":$running_count,"queued":$queued_count,"crashes":$crash_count,"last_error":$last_err,"cycle":$CYCLE_COUNT}
HEALTH_EOF
}

# ─── Task status file helpers ────────────────────────────────────────────────

write_task_status() {
    local task_id="$1" phase="$2" msg="${3:-}"
    local project="${4:-unknown}" branch="${5:-unknown}" pid="${6:-$$}"
    local now
    now=$(date +%s)
    local started="${7:-$now}"

    cat > "$TASK_STATUS_DIR/${task_id}.status" << STATUS_EOF
phase=$phase
last_activity=$now
pid=$pid
project=$project
branch=$branch
started_at=$started
msg=$msg
STATUS_EOF
}

clean_task_status() {
    local task_id="$1"
    rm -f "$TASK_STATUS_DIR/${task_id}.status"
}

# ─── Task timeout enforcement ─────────────────────────────────────────────────
# Check all running tasks against TASK_TIMEOUT. Kill any that exceed it.
# Called every poll cycle from the main loop.

check_task_timeouts() {
    local now status_file task_id pid started_at elapsed
    now=$(date +%s)

    for status_file in "$TASK_STATUS_DIR"/*.status; do
        [[ -f "$status_file" ]] || continue

        # Read fields from status file
        local phase=""
        phase=$(sed -n 's/^phase=//p' "$status_file" 2>/dev/null) || continue
        # Only check actively running phases
        case "$phase" in
            running|planning|evaluating|rebasing) ;;
            *) continue ;;
        esac

        task_id=$(basename "$status_file" .status)
        pid=$(sed -n 's/^pid=//p' "$status_file" 2>/dev/null) || pid=""
        started_at=$(sed -n 's/^started_at=//p' "$status_file" 2>/dev/null) || started_at=""

        [[ -z "$started_at" || -z "$pid" ]] && continue

        elapsed=$(( now - started_at ))
        if (( elapsed > TASK_TIMEOUT )); then
            log_error "D-090" "Task $task_id timed out after ${elapsed}s (limit: ${TASK_TIMEOUT}s)"

            # Kill the Claude process using existing process group killer
            kill_task_group "$pid" "$task_id"

            # Find and update the task JSON file
            local task_file="$TASKS_DIR/${task_id}.json"
            if [[ -f "$task_file" ]]; then
                local branch project_path
                branch=$(sed -n 's/^branch=//p' "$status_file" 2>/dev/null) || branch="unknown"
                project_path=$(task_field "$task_file" project_path "unknown")
                update_task_status "$task_file" "failed" "error_message=Task timed out after ${elapsed}s"
                write_task_status "$task_id" "failed" "Timed out after ${elapsed}s" \
                    "$(sed -n 's/^project=//p' "$status_file" 2>/dev/null)" "$branch" "$$" "$started_at"

                # Release file locks
                release_file_locks "$task_id"

                # Notify
                "$HOME/Developer/claude-handler/fleet-notify.sh" --task-failed "$task_id" 2>/dev/null &

                # Write review-queue item
                cat > "$REVIEW_DIR/${task_id}-failed.md" << TIMEOUT_EOF
---
task_id: ${task_id}
project: $(sed -n 's/^project=//p' "$status_file" 2>/dev/null)
type: failed
priority: high
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Task Timed Out

**Branch:** ${branch}
**Elapsed:** ${elapsed}s (limit: ${TASK_TIMEOUT}s)
**Phase:** ${phase}

The task exceeded the timeout limit and was killed.
Check the log: ~/.claude-fleet/logs/${task_id}.log
TIMEOUT_EOF
            fi

            # Clean up status file
            clean_task_status "$task_id"
        fi
    done
}

# ─── Process group management ─────────────────────────────────────────────────
# Kill a task and ALL its child processes (Claude + node + MCP servers).
# Without this, orphaned processes accumulate and eat RAM.

kill_task_group() {
    local pid="$1"
    local task_id="${2:-unknown}"

    if [[ -z "$pid" || "$pid" == "0" ]]; then
        return 1
    fi

    # Try SIGTERM on the process group first (graceful)
    if kill -0 "$pid" 2>/dev/null; then
        log "Sending SIGTERM to process group of PID $pid (task: $task_id)"
        kill -TERM -- -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
        # Wait up to 5 seconds for graceful shutdown
        local wait_count=0
        while kill -0 "$pid" 2>/dev/null && (( wait_count < 5 )); do
            sleep 1
            wait_count=$((wait_count + 1))
        done
    fi

    # Force kill survivors
    if kill -0 "$pid" 2>/dev/null; then
        log "Force-killing process group of PID $pid (task: $task_id)"
        kill -KILL -- -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
    fi

    # Walk the tree for any that escaped the process group
    pkill -P "$pid" 2>/dev/null
    sleep 1
    pkill -9 -P "$pid" 2>/dev/null

    # Clean up the PID file
    local project_pidfile
    for project_pidfile in "$RUNNING_DIR"/*.pid; do
        [[ -f "$project_pidfile" ]] || continue
        local stored_pid
        stored_pid=$(cat "$project_pidfile" 2>/dev/null)
        if [[ "$stored_pid" == "$pid" ]]; then
            rm -f "$project_pidfile"
        fi
    done
}

# ─── Project state checks ────────────────────────────────────────────────────

is_project_running() {
    local project="$1"
    local pidfile="$RUNNING_DIR/$project.pid"
    local pid

    pid=$(read_pidfile "$pidfile") || return 1
    if kill -0 "$pid" 2>/dev/null; then
        return 0  # Still running
    fi
    log_error "D-004" "Stale PID file for $project (pid $pid dead) — auto-cleaning" >&2
    rm -f "$pidfile"
    return 1  # Stale PID, cleaned up
}

is_project_frozen() {
    local project="$1"
    [[ -f "$EVENTS_FILE" ]] || return 1

    local result
    result=$(python3 -c "
import json, sys
from datetime import datetime, timezone
project = sys.argv[1]
try:
    events = json.loads(open(sys.argv[2]).read())
except Exception as e:
    print('PARSE_ERROR:' + str(e), file=sys.stderr)
    sys.exit(2)
now = datetime.now(timezone.utc)
for e in events:
    if project not in e.get('freeze_projects', []):
        continue
    freeze_from = e.get('freeze_from', e.get('start', ''))
    freeze_until = e.get('freeze_until', e.get('end', ''))
    if not freeze_from or not freeze_until:
        continue
    try:
        ff = datetime.fromisoformat(freeze_from.replace('Z', '+00:00'))
        fu = datetime.fromisoformat(freeze_until.replace('Z', '+00:00'))
        if ff <= now <= fu:
            print(e.get('title', 'event'))
            sys.exit(0)
    except Exception:
        continue
sys.exit(1)
" "$project" "$EVENTS_FILE" 2>/dev/null)
    local rc=$?
    if (( rc == 2 )); then
        log_error "D-040" "Events.json parse error — treating $project as not frozen"
        return 1
    elif (( rc == 0 )); then
        return 0  # frozen
    fi
    return 1
}

count_running() {
    local count=0
    local pidfile pid
    for pidfile in "$RUNNING_DIR"/*.pid; do
        [[ -f "$pidfile" ]] || continue
        pid=$(read_pidfile "$pidfile") || {
            log_error "D-005" "PID file race: $(basename "$pidfile") disappeared between check and read" >&2
            rm -f "$pidfile"
            continue
        }
        if kill -0 "$pid" 2>/dev/null; then
            count=$((count + 1))
        else
            log_error "D-004" "Stale PID file: $(basename "$pidfile") (pid $pid dead) — auto-cleaning" >&2
            rm -f "$pidfile"
        fi
    done
    echo "$count"
}

# ─── Auto-merge helpers ──────────────────────────────────────────────────────

is_auto_mergeable() {
    local slug_lower
    slug_lower=$(echo "$1" | tr '[:upper:]' '[:lower:]')

    # UI/visual tasks need human review
    local kw
    for kw in ui ux visual design frontend css style; do
        [[ "$slug_lower" == *"$kw"* ]] && return 1
    done

    # Auto-merge: functional fixes, docs, infra
    for kw in bug fix docs doc readme arch infra maintenance sync cleanup; do
        [[ "$slug_lower" == *"$kw"* ]] && return 0
    done

    return 1
}

find_repo_for_project() {
    local project_path="$1"
    local projects_file="$FLEET_DIR/projects.json"
    [[ -f "$projects_file" ]] || return 1

    python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
for p in data.get('projects', []):
    if p.get('path') == sys.argv[2]:
        repo = p.get('repo', '')
        if repo.startswith('git@github.com:'):
            print(repo.replace('git@github.com:', '').replace('.git', ''))
        elif 'github.com/' in repo:
            parts = repo.rstrip('/').replace('.git', '').split('github.com/')
            if len(parts) > 1:
                print(parts[-1])
        sys.exit(0)
" "$projects_file" "$project_path" 2>/dev/null
}

try_auto_merge() {
    local task_file="$1" task_id="$2" branch="$3" project_path="$4"

    local task_slug
    task_slug=$(task_field "$task_file" slug "")
    [[ -z "$task_slug" ]] && task_slug="$task_id"

    if ! is_auto_mergeable "$task_slug"; then
        log "[auto-merge] '$task_slug' requires human review — skipping"
        return 1
    fi

    local repo
    repo=$(find_repo_for_project "$project_path") || repo=""
    if [[ -z "$repo" ]]; then
        warn "[auto-merge] No GitHub repo found for $project_path"
        return 1
    fi

    local pr_number
    pr_number=$(gh pr list --repo "$repo" --head "$branch" --json number --jq '.[0].number' 2>/dev/null) || pr_number=""
    if [[ -z "$pr_number" ]]; then
        log_error "D-031" "GitHub API unreachable or no open PR for branch '$branch' in $repo"
        return 1
    fi

    log "[auto-merge] Merging PR #$pr_number ($repo)"
    if gh pr merge "$pr_number" --repo "$repo" --squash --delete-branch 2>/dev/null; then
        ok "[auto-merge] Merged PR #$pr_number"
        update_task_status "$task_file" "merged"

        # Archive review-queue items
        local archive_dir="$REVIEW_DIR/archived"
        mkdir -p "$archive_dir"
        local rq_file
        for rq_file in "$REVIEW_DIR"/*"${task_id}"*.md; do
            [[ -f "$rq_file" ]] || continue
            mv "$rq_file" "$archive_dir/" 2>/dev/null &&
                log "[auto-merge] Archived: $(basename "$rq_file")"
        done
        return 0
    else
        log_error "D-030" "Auto-merge failed for PR #$pr_number ($repo) — leaving for human review"
        return 1
    fi
}

# ─── Planner: expand short prompts into detailed specs ────────────────────────

run_planner() {
    local task_id="$1" task_file="$2" project_path="$3" task_prompt="$4"

    local spec_file="$TASKS_DIR/${task_id}.spec.md"
    local planner_log="$LOGS_DIR/${task_id}.planner.log"

    local planner_system="You are a PLANNER agent. Your job is to expand a short task description into a detailed specification that a developer agent can implement and an evaluator agent can grade.

PLANNER RULES:
1. Read the project's CLAUDE.md and codebase structure to understand context.
2. Write a specification to: ${spec_file}
3. The spec MUST include:
   - Objective (one paragraph expanding the prompt)
   - Acceptance criteria (numbered, each must be testable)
   - Implementation approach (ordered steps)
   - Files to modify (with reasons)
   - Edge cases to handle
   - Out of scope (prevent scope creep)
   - Evaluator grading rubric (table: criterion, weight, how to verify)
4. Keep the spec under 200 lines. Be specific, not verbose.
5. Do NOT implement anything. Only write the spec file.
6. Spend at most 15 turns reading the project and writing the spec."

    log "  Planner: expanding prompt into spec"
    "$CLAUDE_BIN" -p \
        --permission-mode auto \
        --max-turns 20 \
        --append-system-prompt "$planner_system" \
        "Create a detailed specification for this task.

## Task
${task_prompt}

## Project
Path: ${project_path}
Read the project's CLAUDE.md and key source files to understand the codebase.
Write the spec to: ${spec_file}" \
        2>&1 | tee "$planner_log" || {
            warn "  Planner session failed -- using original prompt"
            return 1
        }

    if [[ -f "$spec_file" && -s "$spec_file" ]]; then
        ok "  Planner produced spec: $(wc -l < "$spec_file") lines"
        echo "$spec_file"
    else
        warn "  Planner produced no spec file"
        echo ""
    fi
}

# ─── Evaluator: independent QA of completed work ─────────────────────────────

run_evaluator() {
    local task_id="$1" task_file="$2" project_path="$3" branch="$4"
    local original_prompt="$5" eval_round="$6"

    local eval_dir="$FLEET_DIR/eval"
    local eval_log="$LOGS_DIR/${task_id}.eval-${eval_round}.log"
    local verdict_file="$eval_dir/${task_id}.verdict-${eval_round}.json"
    local critique_file="$eval_dir/${task_id}.critique-${eval_round}.md"
    mkdir -p "$eval_dir"

    # Gather branch diff
    local base_branch
    base_branch=$(task_field "$task_file" base_branch "main")
    local diff_stat diff_full
    diff_stat=$(cd "$project_path" && git diff "origin/${base_branch}...${branch}" --stat 2>/dev/null | tail -20) || diff_stat="(diff unavailable)"
    diff_full=$(cd "$project_path" && git diff "origin/${base_branch}...${branch}" 2>/dev/null | head -2000) || diff_full=""

    # Read generator summary if it exists
    local summary=""
    [[ -f "$LOGS_DIR/${task_id}.summary.md" ]] && summary=$(head -200 "$LOGS_DIR/${task_id}.summary.md")

    # Determine task type for grading criteria
    local task_type="default"
    local slug_lower
    slug_lower=$(echo "$(task_field "$task_file" slug "")" | tr '[:upper:]' '[:lower:]')

    local override_type
    override_type=$(task_field "$task_file" eval_criteria_type "")
    if [[ -n "$override_type" ]]; then
        task_type="$override_type"
    else
        case "$slug_lower" in
            *ui*|*frontend*|*design*|*layout*|*theme*|*css*|*visual*|*hmi*|*animation*) task_type="ui" ;;
            *engine*|*solver*|*algorithm*|*matrix*|*convergence*|*kron*|*idp*|*pf*) task_type="engine" ;;
            *api*|*endpoint*|*route*|*backend*|*server*|*sse*|*rest*) task_type="api" ;;
            *fix*|*bug*|*crash*|*error*|*broken*|*hotfix*) task_type="fix" ;;
            *refactor*|*rename*|*restructure*|*cleanup*|*reorganize*) task_type="refactor" ;;
            *doc*|*readme*|*changelog*|*comment*) task_type="docs" ;;
            *test*|*spec*|*validation*|*coverage*) task_type="test" ;;
            *infra*|*ci*|*docker*|*deploy*|*config*|*daemon*) task_type="infra" ;;
        esac
    fi

    # Load grading criteria
    local criteria_file="$SCRIPT_DIR/eval-criteria/${task_type}.md"
    local criteria=""
    if [[ -f "$criteria_file" ]]; then
        criteria=$(cat "$criteria_file")
    elif [[ -f "$SCRIPT_DIR/eval-criteria/default.md" ]]; then
        criteria=$(cat "$SCRIPT_DIR/eval-criteria/default.md")
    else
        criteria="Judge correctness, quality, testing, and completeness. Score 0-100."
    fi

    # Load planner spec if it exists (overrides criteria for task-specific rubric)
    local spec_content=""
    [[ -f "$TASKS_DIR/${task_id}.spec.md" ]] && spec_content=$(cat "$TASKS_DIR/${task_id}.spec.md")

    # Load previous critique if retry round
    local prev_section=""
    if (( eval_round > 1 )); then
        local prev_file="$eval_dir/${task_id}.critique-$((eval_round - 1)).md"
        if [[ -f "$prev_file" ]]; then
            prev_section="
## Previous Critique (Round $((eval_round - 1)))
The generator was given this feedback and tried again. Check whether the issues were fixed:

$(cat "$prev_file")
"
        fi
    fi

    # Build evaluator system prompt
    local eval_system="You are an EVALUATOR for an autonomous coding agent fleet. You independently assess whether a task was completed correctly. You are NOT the agent that did the work.

EVALUATOR RULES:
1. Be rigorous but fair. Judge against the SPECIFIC criteria provided.
2. Write your verdict as JSON to: ${verdict_file}
   Format: {\"verdict\": \"PASS\" or \"FAIL\", \"score\": 0-100, \"issues\": [\"issue1\", \"issue2\"], \"summary\": \"one line\"}
3. If FAIL, also write actionable critique to: ${critique_file}
   Include: specific files, line numbers, what is wrong, what to fix.
4. Do NOT make code changes yourself. Only evaluate and write verdict files.
5. For web UI tasks: use /browse or /qa to verify the UI renders and works.
6. For API tasks: verify endpoints respond correctly (curl or test runner).
7. For engine/algorithm tasks: verify tests pass and results are numerically correct.
8. Score guide: 90-100=excellent, 70-89=good with minor issues, 50-69=significant gaps, <50=major failures."

    # Build evaluator task prompt
    local eval_prompt="Evaluate whether this task was completed correctly.

## Original Task
${original_prompt}

## Branch Diff Summary
\`\`\`
${diff_stat}
\`\`\`

## Detailed Diff (first 2000 lines)
\`\`\`diff
${diff_full}
\`\`\`

## Generator Summary
${summary}

## Grading Criteria
${criteria}
"
    # Append spec rubric if planner ran
    if [[ -n "$spec_content" ]]; then
        eval_prompt="${eval_prompt}
## Planner Specification (use this rubric for task-specific grading)
${spec_content}
"
    fi

    # Append previous critique if retry
    [[ -n "$prev_section" ]] && eval_prompt="${eval_prompt}${prev_section}"

    eval_prompt="${eval_prompt}
## Instructions
1. Read the original task carefully
2. Review the diff against the grading criteria
3. For web/UI tasks: verify visually with /browse or /qa
4. For code tasks: check tests pass, logic is correct
5. Write verdict JSON to: ${verdict_file}
6. If FAIL: write actionable critique to: ${critique_file}
"

    # Run evaluator Claude session (short: 30 turns max, separate context)
    log "  Evaluator round ${eval_round}: launching (type=${task_type}, max_turns=30)"
    "$CLAUDE_BIN" -p \
        --permission-mode auto \
        --max-turns 30 \
        --append-system-prompt "$eval_system" \
        "$eval_prompt" \
        2>&1 | tee "$eval_log" || {
            log_error "D-070" "Evaluator session crashed for task $task_id round $eval_round"
            echo "UNKNOWN"
            return 1
        }

    # Parse verdict
    if [[ -f "$verdict_file" ]]; then
        local verdict
        verdict=$(python3 -c "
import json, sys
try:
    d = json.load(open('${verdict_file}'))
    print(d.get('verdict', 'UNKNOWN'))
except Exception as e:
    print('UNKNOWN', file=sys.stderr)
    print('UNKNOWN')
" 2>/dev/null) || verdict="UNKNOWN"
        echo "$verdict"
    else
        log_error "D-071" "Verdict file not found after evaluator for task $task_id round $eval_round"
        echo "UNKNOWN"
    fi
}

# ─── Run a task on a remote worker via SSH ────────────────────────────────────

run_task_remote() {
    local task_file="$1" worker_ssh="$2"

    local task_id project_name project_path branch max_turns base_branch
    task_id=$(task_field "$task_file" id)
    project_name=$(task_field "$task_file" project_name "unknown")
    project_path=$(task_field "$task_file" project_path)
    branch=$(task_field "$task_file" branch)
    max_turns=$(task_field "$task_file" max_turns "200")
    base_branch=$(task_field "$task_file" base_branch "main")

    # Resolve remote project path
    local remote_path
    remote_path=$(remote_project_path "$worker_ssh" "$project_name" "$project_path")

    log "  Remote worker: $worker_ssh"
    log "  Remote path:   $remote_path"
    log "  Branch:        $branch"

    local task_started_at
    task_started_at=$(date +%s)
    # Stamp which machine is running this task
    python3 -c "
import json
f = '$task_file'
try:
    d = json.loads(open(f).read())
    d['route'] = '$worker_ssh'
    open(f, 'w').write(json.dumps(d, indent=2))
except: pass
" 2>/dev/null
    update_task_status "$task_file" "running"
    write_task_status "$task_id" "running" "Running on $worker_ssh" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

    # Sync prompt file to remote worker
    local prompt_file_ref
    prompt_file_ref=$(task_field "$task_file" prompt_file "")
    if [[ -n "$prompt_file_ref" ]]; then
        local local_prompt="$TASKS_DIR/$prompt_file_ref"
        if [[ -f "$local_prompt" ]]; then
            ssh "$worker_ssh" "mkdir -p ~/.claude-fleet/tasks" 2>/dev/null
            scp -q "$local_prompt" "$worker_ssh:~/.claude-fleet/tasks/" 2>/dev/null
        fi
    fi

    # Sync task JSON to remote
    scp -q "$task_file" "$worker_ssh:~/.claude-fleet/tasks/" 2>/dev/null

    # Read prompt locally (for evaluator later)
    local task_prompt=""
    if [[ -n "$prompt_file_ref" && -f "$TASKS_DIR/$prompt_file_ref" ]]; then
        task_prompt=$(cat "$TASKS_DIR/$prompt_file_ref")
    else
        task_prompt=$(task_field "$task_file" prompt "")
    fi

    # Build worker prompt (same as local but notes remote execution)
    local queued_count
    queued_count=$(count_tasks "queued")
    local worker_prompt="You are running as a WORKER on ${worker_ssh}. Task ID: ${task_id}. Branch: ${branch}.

WORKER RULES:
1. You are FULLY AUTONOMOUS. Make good decisions without asking questions.
2. All work goes on branch: ${branch}. NEVER push to main.
3. Commit frequently with descriptive messages.
4. When DONE: push the branch, open a PR with gh pr create, write a summary to ~/.claude-fleet/logs/${task_id}.summary.md.
5. Update ~/.claude-fleet/tasks/${task_id}.json status to completed or failed.
6. Use /review before pushing. Use /qa if testing a web app.
7. There are ${queued_count} more tasks in the queue. Work efficiently."

    local log_file="$LOGS_DIR/${task_id}.log"
    local exit_code=0

    # Run Claude on remote worker via SSH
    # Write a self-contained script to remote, then execute it.
    # This avoids all quoting/escaping issues with SSH + bash -c.
    log "  Launching Claude on $worker_ssh..."
    local remote_script="/tmp/fleet-task-${task_id}.sh"
    local escaped_system_prompt
    escaped_system_prompt=$(printf '%s' "$worker_prompt" | sed "s/'/'\\''/g")

    cat > /tmp/_fleet_remote_script.sh << REMOTE_SCRIPT_EOF
#!/bin/bash
export PATH="\$HOME/.local/bin:\$HOME/.bun/bin:/usr/local/bin:\$PATH"
cd '${remote_path}' || exit 1
git fetch origin 2>/dev/null
git checkout -b '${branch}' 'origin/${base_branch}' 2>/dev/null || git checkout '${branch}' 2>/dev/null || git checkout -b '${branch}' 2>/dev/null
git submodule update --init 2>/dev/null

PROMPT_FILE="\$HOME/.claude-fleet/tasks/${prompt_file_ref:-${task_id}.prompt}"
if [[ ! -f "\$PROMPT_FILE" ]]; then
    echo "[D-014] Prompt file not found on remote: \$PROMPT_FILE" >&2
    exit 1
fi

PROMPT=\$(cat "\$PROMPT_FILE")
if [[ -z "\$PROMPT" ]]; then
    echo "[D-014] Prompt file empty on remote: \$PROMPT_FILE" >&2
    exit 1
fi

claude -p \\
    --permission-mode auto \\
    --max-turns ${max_turns} \\
    --append-system-prompt '${escaped_system_prompt}' \\
    "\$PROMPT"
REMOTE_SCRIPT_EOF

    scp -q /tmp/_fleet_remote_script.sh "$worker_ssh:$remote_script" 2>/dev/null
    ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=10 "$worker_ssh" \
        "bash '$remote_script'" 2>&1 | tee "$log_file" || exit_code=${PIPESTATUS[0]:-$?}
    ssh "$worker_ssh" "rm -f '$remote_script'" 2>/dev/null

    # Fetch results back (the remote pushed the branch, we fetch it)
    log "  Fetching results from $worker_ssh..."
    if [[ -d "$project_path" ]]; then
        (cd "$project_path" && git fetch origin "$branch" 2>/dev/null) || true
    fi

    # Collect summary if remote wrote one
    ssh "$worker_ssh" "cat ~/.claude-fleet/logs/${task_id}.summary.md 2>/dev/null" > "$LOGS_DIR/${task_id}.summary.md" 2>/dev/null || true

    # Handle result (same as local: evaluator, PR, review-queue)
    if [[ $exit_code -eq 0 ]]; then
        ok "Task $task_id completed on $worker_ssh"
        write_task_status "$task_id" "completed" "Completed on $worker_ssh" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

        local pr_url=""
        if [[ -d "$project_path" ]]; then
            pr_url=$(cd "$project_path" && gh pr list --head "$branch" --json url -q '.[0].url' 2>/dev/null) || pr_url=""
        fi
        if [[ -n "$pr_url" ]]; then
            update_task_status "$task_file" "completed" "pr_url=$pr_url"
        else
            update_task_status "$task_file" "completed"
        fi

        # Notifications
        "$HOME/Developer/claude-handler/fleet-notify.sh" --task-complete "$task_id" 2>/dev/null &

        # Auto-merge safe PRs
        local auto_merged=false
        if [[ -n "$pr_url" ]]; then
            try_auto_merge "$task_file" "$task_id" "$branch" "$project_path" && auto_merged=true
        fi

        if [[ "$auto_merged" == "false" ]]; then
            cat > "$REVIEW_DIR/${task_id}-completed.md" << REVIEW_EOF
---
task_id: ${task_id}
project: $(basename "$project_path")
type: completed
worker: ${worker_ssh}
priority: normal
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Task Completed (on ${worker_ssh})

**Branch:** ${branch}
**Worker:** ${worker_ssh}
**Task:** $(echo "$task_prompt" | head -1)

Check the PR and summary:
- Summary: ~/.claude-fleet/logs/${task_id}.summary.md
- Run \`/worker-review\` to review and merge.
REVIEW_EOF
        fi
    else
        local error_msg="exit code $exit_code on $worker_ssh"
        log_error "D-013" "Claude exited non-zero on $worker_ssh for task $task_id (exit $exit_code)"
        write_task_status "$task_id" "failed" "$error_msg" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"
        update_task_status "$task_file" "failed" "error_message=$error_msg"

        "$HOME/Developer/claude-handler/fleet-notify.sh" --task-failed "$task_id" 2>/dev/null &

        cat > "$REVIEW_DIR/${task_id}-failed.md" << REVIEW_EOF
---
task_id: ${task_id}
project: $(basename "$project_path")
type: failed
worker: ${worker_ssh}
priority: high
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Task Failed (on ${worker_ssh})

**Branch:** ${branch}
**Worker:** ${worker_ssh}
**Exit code:** ${exit_code}
**Task:** $(echo "$task_prompt" | head -1)

Check the log: ~/.claude-fleet/logs/${task_id}.log
REVIEW_EOF
    fi
}

# ─── File lock helpers ──────────────────────────────────────────────────────
# Layer 1: Prevent overlapping file edits between parallel tasks.
# file-lock.py is a standalone CLI — called via subprocess.
# All calls are safe if file-lock.py is missing (backward compatible).

acquire_file_locks() {
    local task_id="$1" project="$2" project_path="$3" prompt="$4"
    [[ -f "$FILE_LOCK" ]] || return 0

    # Estimate which paths this task will touch
    local paths
    paths=$(python3 "$FILE_LOCK" estimate "$project_path" "$prompt" 2>/dev/null) || return 0
    [[ -z "$paths" ]] && return 0

    # Check for conflicts with running tasks
    local conflict_rc=1
    # shellcheck disable=SC2086
    echo "$paths" | xargs python3 "$FILE_LOCK" check "$project" >/dev/null 2>&1 || conflict_rc=$?
    if [[ $conflict_rc -eq 0 ]]; then
        local conflicts
        conflicts=$(echo "$paths" | xargs python3 "$FILE_LOCK" check "$project" 2>/dev/null)
        warn "[file-lock] Conflict detected for $task_id:"
        echo "$conflicts" | while IFS= read -r line; do warn "  $line"; done
        return 1  # signal conflict
    fi

    # Acquire locks
    # shellcheck disable=SC2086
    echo "$paths" | xargs python3 "$FILE_LOCK" acquire "$task_id" "$project" 2>/dev/null
    local rc=$?
    if [[ $rc -eq 0 ]]; then
        local count
        count=$(echo "$paths" | wc -l | tr -d ' ')
        log "[file-lock] Acquired $count lock(s) for $task_id"
    fi
    return 0
}

release_file_locks() {
    local task_id="$1"
    [[ -f "$FILE_LOCK" ]] || return 0
    python3 "$FILE_LOCK" release "$task_id" 2>/dev/null || true
}

check_file_lock_conflicts() {
    # Check if a task's estimated paths conflict with running locks.
    # Returns 0 if conflict, 1 if clear.
    local project="$1" project_path="$2" prompt="$3"
    [[ -f "$FILE_LOCK" ]] || return 1

    local paths
    paths=$(python3 "$FILE_LOCK" estimate "$project_path" "$prompt" 2>/dev/null) || return 1
    [[ -z "$paths" ]] && return 1

    # shellcheck disable=SC2086
    echo "$paths" | xargs python3 "$FILE_LOCK" check "$project" >/dev/null 2>&1
    return $?  # 0 = conflict found, 1 = no conflict
}

# ─── Rebase before PR ──────────────────────────────────────────────────────
# Layer 2: After generator finishes, rebase onto latest main before evaluator.
# If rebase fails, attempt a short Claude session to resolve conflicts.

rebase_before_pr() {
    local task_id="$1" project_path="$2" branch="$3" base_branch="${4:-main}"

    log "[rebase] Rebasing $branch onto origin/$base_branch"

    cd "$project_path" || return 1
    git fetch origin 2>/dev/null || true

    # Check if there's anything to rebase (are we behind?)
    local behind
    behind=$(git rev-list --count "$branch..origin/$base_branch" 2>/dev/null) || behind=0
    if [[ "$behind" == "0" ]]; then
        log "[rebase] Already up to date with origin/$base_branch"
        return 0
    fi

    log "[rebase] $behind commit(s) behind origin/$base_branch — rebasing"

    # Attempt rebase
    if git rebase "origin/$base_branch" 2>/dev/null; then
        ok "[rebase] Rebase succeeded"
        # Force-push the rebased branch
        git push --force-with-lease origin "$branch" 2>/dev/null || git push -f origin "$branch" 2>/dev/null || {
            warn "[rebase] Push after rebase failed — continuing anyway"
        }
        return 0
    fi

    # Rebase failed — try Claude conflict resolution (15 turns max)
    warn "[rebase] Rebase conflict detected — attempting auto-resolution"
    git rebase --abort 2>/dev/null

    local resolve_log="$LOGS_DIR/${task_id}.rebase-resolve.log"
    local resolve_prompt="REBASE CONFLICT RESOLUTION — Automated.

The branch '$branch' has conflicts when rebasing onto 'origin/$base_branch'.

Steps:
1. Run: git rebase origin/$base_branch
2. For each conflict, resolve it by reading both sides and merging logically
3. After resolving each file: git add <file> && git rebase --continue
4. When done: git push --force-with-lease origin $branch
5. If you cannot resolve: git rebase --abort and exit with error

Prefer keeping the branch's changes unless the base changes are clearly newer."

    log "[rebase] Launching conflict resolver Claude (15 turns max)"
    local resolve_exit=0
    "$CLAUDE_BIN" -p \
        --permission-mode auto \
        --max-turns 15 \
        --append-system-prompt "You are a CONFLICT RESOLVER. Resolve git rebase conflicts. Be quick and precise. Do NOT create new features or refactor." \
        "$resolve_prompt" \
        2>&1 | tee "$resolve_log" || resolve_exit=${PIPESTATUS[0]:-$?}

    if [[ $resolve_exit -eq 0 ]]; then
        # Verify the rebase completed (we should no longer be mid-rebase)
        if [[ ! -d "$project_path/.git/rebase-merge" && ! -d "$project_path/.git/rebase-apply" ]]; then
            ok "[rebase] Conflict resolution succeeded"
            return 0
        fi
    fi

    # Still broken — abort and mark for manual rebase
    git rebase --abort 2>/dev/null
    log_error "D-080" "Rebase conflict resolution failed for $task_id ($branch)"
    return 1
}

# ─── Run a single task ────────────────────────────────────────────────────────

run_task() {
    local task_file="$1"

    # Per-task env hygiene: clear volatile vars leaked from the long-lived
    # daemon shell or a prior task. run_task runs in a subshell via run_task_async,
    # so these unsets are scoped to this task only.
    # Keep HOME, PATH, SSH_*, WORKER_CLAUDE_BIN — those are infra.
    local _leak
    while IFS= read -r _leak; do
        unset "$_leak" 2>/dev/null || true
    done < <(compgen -v 2>/dev/null | awk '/^(ANTHROPIC_|TASK_)/ || (/^CLAUDE_/ && !/^CLAUDE_CODE_/)')
    unset NO_COLOR CI FORCE_COLOR 2>/dev/null || true

    # Read task manifest — validate critical fields
    local task_id task_prompt project_path branch
    task_id=$(task_field "$task_file" id)
    project_path=$(task_field "$task_file" project_path)
    branch=$(task_field "$task_file" branch)

    # Read prompt: prefer separate .prompt file, fall back to inline JSON field
    local prompt_file_ref prompt_file_path
    prompt_file_ref=$(task_field "$task_file" prompt_file "")
    if [[ -n "$prompt_file_ref" ]]; then
        # New format: prompt in separate file (referenced by manifest)
        if [[ "$prompt_file_ref" == /* ]]; then
            prompt_file_path="$prompt_file_ref"
        else
            prompt_file_path="$TASKS_DIR/$prompt_file_ref"
        fi
        if [[ -f "$prompt_file_path" ]]; then
            task_prompt=$(cat "$prompt_file_path")
        else
            log_error "D-014" "Prompt file not found: $prompt_file_path (task: $task_id)"
            task_prompt=""
        fi
    else
        # Legacy format: inline prompt in JSON
        task_prompt=$(task_field "$task_file" prompt)
    fi

    # Also check for .prompt file by convention (id-based) even if not referenced
    if [[ -z "$task_prompt" ]]; then
        local convention_prompt="$TASKS_DIR/${task_id}.prompt"
        if [[ -f "$convention_prompt" ]]; then
            log "Recovered prompt from convention file: $convention_prompt"
            task_prompt=$(cat "$convention_prompt")
        fi
    fi

    if [[ -z "$task_id" || -z "$task_prompt" || -z "$project_path" || -z "$branch" ]]; then
        log_error "D-010" "Task manifest missing required fields: $task_file (id='$task_id' prompt_len=${#task_prompt} path='$project_path' branch='$branch')"
        update_task_status "$task_file" "failed" "error_message=Missing required fields in manifest"
        return 1
    fi

    # Validate prompt is substantive (not just whitespace or a few chars)
    if [[ ${#task_prompt} -lt 10 ]]; then
        log_error "D-015" "Prompt too short (${#task_prompt} chars) for task $task_id — likely a dispatch failure"
        update_task_status "$task_file" "failed" "error_message=Prompt too short (${#task_prompt} chars) — re-dispatch with valid prompt"
        return 1
    fi

    local permission_mode subdir estimated_time base_branch
    permission_mode=$(task_field "$task_file" permission_mode "auto")
    subdir=$(task_field "$task_file" subdir "")
    estimated_time=$(task_field "$task_file" estimated_time "30 min")
    base_branch=$(task_field "$task_file" base_branch "main")

    local work_dir="$project_path"
    [[ -n "$subdir" ]] && work_dir="$project_path/$subdir"

    # ─── Route decision: local or remote worker ──────────────
    local target_worker
    target_worker=$(route_task "$task_file")

    if [[ "$target_worker" != "local" ]]; then
        # Delegate to remote worker
        if check_remote_worker "$target_worker"; then
            log "Routing task $task_id to remote worker: $target_worker"
            run_task_remote "$task_file" "$target_worker"
            return $?
        else
            warn "Remote worker $target_worker unreachable — falling back to local"
            target_worker="local"
        fi
    fi

    # Validate project path exists (local execution only)
    if [[ ! -d "$project_path" ]]; then
        log_error "D-011" "Project path does not exist: $project_path (task: $task_id)"
        update_task_status "$task_file" "failed" "error_message=Project path not found: $project_path"
        return 1
    fi

    log "Starting task: $task_id (local)"
    log "  Project: $project_path"
    log "  Branch:  $branch"
    log "  Est:     $estimated_time"

    local task_started_at
    task_started_at=$(date +%s)
    # Stamp which machine is running this task
    python3 -c "
import json
f = '$task_file'
try:
    d = json.loads(open(f).read())
    d['route'] = '${MACHINE_NAME:-$(hostname -s)}'
    open(f, 'w').write(json.dumps(d, indent=2))
except: pass
" 2>/dev/null
    update_task_status "$task_file" "running"
    write_task_status "$task_id" "starting" "Preparing git and environment" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

    # Prepare git -- always start from fresh origin/main
    cd "$project_path" || { err "cd failed: $project_path"; return 1; }

    # Step 1: Return to main and clean all state
    git checkout main 2>/dev/null || git checkout "$base_branch" 2>/dev/null || true
    git checkout -- . 2>/dev/null || true
    git clean -fd 2>/dev/null || true
    git rebase --abort 2>/dev/null || true
    git merge --abort 2>/dev/null || true

    # Step 2: Fetch latest and fast-forward main to origin
    git fetch origin 2>/dev/null || true
    git reset --hard "origin/$base_branch" 2>/dev/null || git reset --hard origin/main 2>/dev/null || true

    log "[git] Starting from fresh origin/$base_branch ($(git rev-parse --short HEAD 2>/dev/null))"

    # Step 3: Delete any stale local branch with the same name
    git branch -D "$branch" 2>/dev/null || true

    # Step 4: Create fresh branch from latest origin/main
    if ! git checkout -b "$branch" "origin/$base_branch" 2>/dev/null; then
        if ! git checkout -b "$branch" origin/main 2>/dev/null; then
            log_error "D-012" "Cannot create branch $branch from origin/$base_branch (task: $task_id)"
            update_task_status "$task_file" "failed" "error_message=Cannot create branch $branch"
            write_task_status "$task_id" "failed" "Cannot create branch $branch" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"
            return 1
        fi
    fi
    git submodule update --init 2>/dev/null || true

    [[ -n "$subdir" ]] && { cd "$subdir" || { err "cd failed: $subdir"; return 1; }; }

    # ─── Acquire file locks (Layer 1) ────────────────────
    local project_name_for_lock
    project_name_for_lock=$(task_field "$task_file" project_name "unknown")
    acquire_file_locks "$task_id" "$project_name_for_lock" "$project_path" "$task_prompt" || {
        warn "[file-lock] Skipping lock acquisition (conflict or unavailable) for $task_id"
        # Don't block — conflicts are advisory. The task runs anyway.
    }

    # ─── Planner (optional) ──────────────────────────────
    local planner_enabled
    planner_enabled=$(task_field "$task_file" planner "false")
    # Auto-enable for very short prompts
    if [[ "$planner_enabled" == "false" && ${#task_prompt} -lt 200 ]]; then
        planner_enabled="true"
        log "Auto-enabling planner (prompt is ${#task_prompt} chars)"
    fi

    if [[ "$planner_enabled" == "true" ]]; then
        log "Running planner for task $task_id"
        write_task_status "$task_id" "planning" "Planner expanding prompt" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

        local spec_file
        spec_file=$(run_planner "$task_id" "$task_file" "$project_path" "$task_prompt")

        if [[ -n "$spec_file" && -f "$spec_file" ]]; then
            # Prepend spec to generator prompt
            task_prompt="## Task Specification (from planner)

$(cat "$spec_file")

## Original Task Prompt

${task_prompt}"
        fi
    fi

    # Build worker prompt
    local queued_count
    queued_count=$(count_tasks "queued")

    local worker_prompt="You are running as a WORKER on Mac Mini. Task ID: ${task_id}. Branch: ${branch}.

WORKER RULES:
1. You are FULLY AUTONOMOUS. Make good decisions without asking questions. Never wait for input.
2. All work goes on branch: ${branch}. NEVER push to main.
3. Commit frequently with descriptive messages.
4. When DONE: push the branch, open a PR with gh pr create, write a summary.
5. If you need Commander feedback on a DECISION (not a blocker — keep working):
   Write to ~/.claude-fleet/review-queue/${task_id}-decision.md with this format:
   ---
   task_id: ${task_id}
   project: $(basename "$project_path")
   type: decision_needed
   priority: normal
   created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
   ---
   ## Decision Needed
   [What you need input on]
   ## Context
   [Why this matters]
   ## What I Did
   [The choice you made and why — you kept working, this is just a flag for review]
6. If genuinely BLOCKED (cannot proceed at all):
   Write to ~/.claude-fleet/review-queue/${task_id}-blocked.md with type: blocked
   Update ~/.claude-fleet/tasks/${task_id}.json with status=blocked
   Then STOP — do not spin.
7. Write a completion summary to ~/.claude-fleet/logs/${task_id}.summary.md when finished.
8. Update ~/.claude-fleet/tasks/${task_id}.json status to completed or failed when done.
   On completion, also set pr_url to the PR URL from gh pr create.
   On failure, also set error_message to a one-line summary of what went wrong.
9. Use gstack skills as appropriate: /review before pushing, /qa if testing a web app.
10. There are ${queued_count} more tasks in the queue after this one. Estimated time: ${estimated_time}. Work efficiently — the daemon will start the next task when you finish.
11. PERFORMANCE: When running long computations (pytest suites, simulations, validation scripts), use run_in_background instead of waiting synchronously. Continue writing the next file, feature, or independent subtask while tests run. Check results before committing. Never block on a 5-minute test run when you have other work to do.
12. CHECKPOINTING: For long tasks, write a handoff file to ~/.claude-fleet/eval/${task_id}.handoff.md every time you complete a major subtask. Include: what is done (checked items), what is in progress, what remains (unchecked items), key decisions made. This lets a fresh session pick up your work if the context gets too large."

    # Run Claude
    local log_file="$LOGS_DIR/${task_id}.log"
    local exit_code=0
    local max_turns
    max_turns=$(task_field "$task_file" max_turns "200")
    write_task_status "$task_id" "running" "Claude session active" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

    # ─── Heartbeat monitor (background) ───────────────────────
    # Monitors log file growth every 60s. Records heartbeat to SQLite.
    # If log stops growing for 10+ minutes, task is flagged as stuck.
    local heartbeat_pid=0
    (
        local prev_size=0
        local start_epoch
        start_epoch=$(date +%s)
        while true; do
            sleep 60
            local cur_size=0
            [[ -f "$log_file" ]] && cur_size=$(wc -c < "$log_file" 2>/dev/null || echo 0)
            local pid_alive=1
            # Record heartbeat via task-db if available
            if [[ -f "$SCRIPT_DIR/task-db.py" ]]; then
                python3 "$SCRIPT_DIR/task-db.py" heartbeat "$task_id" "$cur_size" "$pid_alive" 2>/dev/null
            fi
            # Also touch a progress file for simple monitoring
            echo "$cur_size" > "$TASK_STATUS_DIR/${task_id}.progress" 2>/dev/null

            # Context reset trigger detection
            local elapsed_min=$(( ($(date +%s) - start_epoch) / 60 ))
            local reset_file="$FLEET_DIR/eval/${task_id}.reset-trigger"
            if [[ ! -f "$reset_file" ]]; then
                if (( cur_size > 512000 )); then
                    echo "RESET_TRIGGER=log_size" > "$reset_file" 2>/dev/null
                elif (( elapsed_min > 60 )); then
                    echo "RESET_TRIGGER=time_${elapsed_min}m" > "$reset_file" 2>/dev/null
                fi
            fi

            prev_size=$cur_size
        done
    ) &
    heartbeat_pid=$!

    # ─── Run Claude with readable log capture ────────────────
    # Note: setsid is Linux-only (not available on macOS).
    # Note: script -q produces binary typescript on macOS — use tee instead.
    if command -v stdbuf &>/dev/null; then
        stdbuf -oL "$CLAUDE_BIN" -p \
            --permission-mode auto \
            --max-turns "$max_turns" \
            --append-system-prompt "$worker_prompt" \
            "$task_prompt" \
            2>&1 | tee "$log_file" || exit_code=${PIPESTATUS[0]:-$?}
    else
        "$CLAUDE_BIN" -p \
            --permission-mode auto \
            --max-turns "$max_turns" \
            --append-system-prompt "$worker_prompt" \
            "$task_prompt" \
            2>&1 | tee "$log_file" || exit_code=${PIPESTATUS[0]:-$?}
    fi

    # Stop heartbeat monitor
    kill "$heartbeat_pid" 2>/dev/null
    wait "$heartbeat_pid" 2>/dev/null

    # ─── Rate limit detection: re-queue and sleep instead of failing ───
    if [[ $exit_code -ne 0 ]] && check_rate_limit "$log_file"; then
        local rl_line
        rl_line=$(tail -20 "$log_file" 2>/dev/null | grep -iE "hit your limit|rate limit|too many requests|429|quota exceeded" | tail -1) || rl_line=""
        warn "Rate limit detected for task $task_id: $rl_line"

        # Re-queue the task (not failed — just waiting for rate limit)
        update_task_status "$task_file" "queued" "error_message="
        write_task_status "$task_id" "rate_limited" "Waiting for rate limit reset" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"
        log "Re-queued task $task_id — will retry after rate limit resets"

        local rl_sleep
        rl_sleep=$(get_rate_limit_sleep "$log_file")
        local rl_min=$((rl_sleep / 60))
        log "Sleeping ${rl_min} minutes until rate limit resets..."
        sleep "$rl_sleep"
        log "Rate limit sleep done — resuming task processing"

        # Clean up and return (don't fall through to failure handling)
        release_file_locks "$task_id"
        clean_task_status "$task_id"
        return 0
    fi

    # ─── Context reset: continue in fresh session if handoff exists ────
    local reset_trigger="$FLEET_DIR/eval/${task_id}.reset-trigger"
    local handoff_file="$FLEET_DIR/eval/${task_id}.handoff.md"
    local context_reset_round=0
    local max_context_resets=3

    while [[ -f "$reset_trigger" && -f "$handoff_file" && $exit_code -eq 0 ]] && (( context_reset_round < max_context_resets )); do
        context_reset_round=$((context_reset_round + 1))
        local trigger_reason
        trigger_reason=$(cat "$reset_trigger" 2>/dev/null)
        log "Context reset (round $context_reset_round/$max_context_resets) for task $task_id ($trigger_reason)"
        rm -f "$reset_trigger"

        local handoff_content
        handoff_content=$(cat "$handoff_file")

        local continuation_prompt="CONTINUATION: Picking up from a previous session that ran out of context.

## Handoff from Previous Session
${handoff_content}

## Original Task
${task_prompt}

Continue from where the previous session left off. Run 'git log --oneline -10' to see what has been committed.
All work continues on branch ${branch}. Push and open/update PR when done."

        local reset_log="$LOGS_DIR/${task_id}.reset-${context_reset_round}.log"
        write_task_status "$task_id" "running" "Context reset round $context_reset_round" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

        # Remove old handoff so generator writes a new one if needed
        rm -f "$handoff_file"

        # Fresh heartbeat monitor for continuation
        (
            local prev_size=0 start_epoch
            start_epoch=$(date +%s)
            while true; do
                sleep 60
                local cur_size=0
                [[ -f "$reset_log" ]] && cur_size=$(wc -c < "$reset_log" 2>/dev/null || echo 0)
                if [[ -f "$SCRIPT_DIR/task-db.py" ]]; then
                    python3 "$SCRIPT_DIR/task-db.py" heartbeat "$task_id" "$cur_size" "1" 2>/dev/null
                fi
                local elapsed_min=$(( ($(date +%s) - start_epoch) / 60 ))
                if [[ ! -f "$reset_trigger" ]]; then
                    if (( cur_size > 512000 )); then
                        echo "RESET_TRIGGER=log_size_r${context_reset_round}" > "$reset_trigger" 2>/dev/null
                    elif (( elapsed_min > 60 )); then
                        echo "RESET_TRIGGER=time_r${context_reset_round}_${elapsed_min}m" > "$reset_trigger" 2>/dev/null
                    fi
                fi
                prev_size=$cur_size
            done
        ) &
        local reset_hb_pid=$!

        exit_code=0
        "$CLAUDE_BIN" -p \
            --permission-mode auto \
            --max-turns "$max_turns" \
            --append-system-prompt "$worker_prompt" \
            "$continuation_prompt" \
            2>&1 | tee "$reset_log" || exit_code=${PIPESTATUS[0]:-$?}

        kill "$reset_hb_pid" 2>/dev/null
        wait "$reset_hb_pid" 2>/dev/null

        # Rate limit check for context reset runs
        if [[ $exit_code -ne 0 ]] && check_rate_limit "$reset_log"; then
            warn "Rate limit hit during context reset for task $task_id"
            update_task_status "$task_file" "queued" "error_message="
            write_task_status "$task_id" "rate_limited" "Waiting for rate limit reset (context reset)" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"
            local rl_sleep
            rl_sleep=$(get_rate_limit_sleep "$reset_log")
            log "Re-queued task $task_id — sleeping $((rl_sleep / 60)) minutes for rate limit..."
            sleep "$rl_sleep"
            log "Rate limit sleep done — resuming"
            release_file_locks "$task_id"
            clean_task_status "$task_id"
            return 0
        fi
    done

    # Handle result
    if [[ $exit_code -eq 0 ]]; then
        ok "Task $task_id completed successfully (generator done)"

        # ─── Rebase before PR (Layer 2) ──────────────────────
        local rebase_note=""
        write_task_status "$task_id" "rebasing" "Rebasing onto latest $base_branch" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"
        if ! rebase_before_pr "$task_id" "$project_path" "$branch" "$base_branch"; then
            warn "[rebase] Rebase failed for $task_id — task will need manual rebase"
            rebase_note="⚠️ **Needs manual rebase** — auto-rebase onto $base_branch failed."
        fi

        # ─── Evaluator loop ───────────────────────────────────
        local eval_enabled eval_passed=true eval_round=0 eval_total_rounds=0
        local eval_score=0 eval_verdict="SKIPPED"

        eval_enabled=$(task_field "$task_file" evaluate "auto")

        # "auto" = evaluate features/engine/api, skip docs/infra/cleanup
        if [[ "$eval_enabled" == "auto" ]]; then
            local slug_check
            slug_check=$(echo "$(task_field "$task_file" slug "")" | tr '[:upper:]' '[:lower:]')
            case "$slug_check" in
                *doc*|*readme*|*context*|*cleanup*|*lint*|*changelog*) eval_enabled="false" ;;
                *) eval_enabled="true" ;;
            esac
        fi

        local max_eval_rounds
        max_eval_rounds=$(task_field "$task_file" max_eval_rounds "2")

        if [[ "$eval_enabled" == "true" ]]; then
            eval_passed=false
            eval_round=1

            while (( eval_round <= max_eval_rounds )); do
                log "Running evaluator (round $eval_round/$max_eval_rounds) for task $task_id"
                write_task_status "$task_id" "evaluating" "Evaluator round $eval_round" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

                eval_verdict=$(run_evaluator "$task_id" "$task_file" "$project_path" "$branch" "$task_prompt" "$eval_round")
                eval_total_rounds=$eval_round

                # Try to read score from verdict file
                local verdict_file="$FLEET_DIR/eval/${task_id}.verdict-${eval_round}.json"
                if [[ -f "$verdict_file" ]]; then
                    eval_score=$(python3 -c "import json; print(json.load(open('${verdict_file}')).get('score', 0))" 2>/dev/null) || eval_score=0
                fi

                if [[ "$eval_verdict" == "PASS" ]]; then
                    eval_passed=true
                    ok "  Evaluator PASSED (round $eval_round, score $eval_score)"
                    break
                elif [[ "$eval_verdict" == "FAIL" && eval_round -lt max_eval_rounds ]]; then
                    warn "  Evaluator FAILED (round $eval_round, score $eval_score) -- re-running generator with critique"
                    eval_round=$((eval_round + 1))

                    # Build retry prompt from critique
                    local critique_file="$FLEET_DIR/eval/${task_id}.critique-$((eval_round - 1)).md"
                    local critique_content=""
                    [[ -f "$critique_file" ]] && critique_content=$(cat "$critique_file")

                    local retry_prompt="RETRY: Your previous attempt at this task was evaluated and found insufficient.

## Original Task
${task_prompt}

## Evaluator Critique (Round $((eval_round - 1)))
${critique_content}

## Instructions
You are on branch ${branch}. Your previous work is already committed.
Pick up where you left off and fix the issues identified above.
Do NOT create a new branch -- continue on ${branch}.
Push and update the PR when done."

                    # Re-run generator (fresh context, same branch)
                    local retry_log="$LOGS_DIR/${task_id}.retry-${eval_round}.log"
                    log "  Re-running generator (retry round $eval_round)"
                    write_task_status "$task_id" "running" "Generator retry round $eval_round" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

                    "$CLAUDE_BIN" -p \
                        --permission-mode auto \
                        --max-turns "$max_turns" \
                        --append-system-prompt "$worker_prompt" \
                        "$retry_prompt" \
                        2>&1 | tee "$retry_log" || {
                            if check_rate_limit "$retry_log"; then
                                warn "Rate limit hit during evaluator retry for task $task_id"
                                update_task_status "$task_file" "queued" "error_message="
                                write_task_status "$task_id" "rate_limited" "Waiting for rate limit reset (eval retry)" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"
                                local rl_sleep
                                rl_sleep=$(get_rate_limit_sleep "$retry_log")
                                log "Re-queued task $task_id — sleeping $((rl_sleep / 60)) minutes for rate limit..."
                                sleep "$rl_sleep"
                                release_file_locks "$task_id"
                                clean_task_status "$task_id"
                                return 0
                            fi
                            log_error "D-073" "Generator retry failed for task $task_id round $eval_round"
                            break
                        }
                    # Loop continues to run evaluator on the retry
                else
                    warn "  Evaluator FAILED or UNKNOWN (final round $eval_round, score $eval_score) -- proceeding"
                    break
                fi
            done
        fi

        # Update eval metadata in task DB
        if [[ -f "$SCRIPT_DIR/task-db.py" ]]; then
            python3 "$SCRIPT_DIR/task-db.py" status "$task_id" "completed" \
                "eval_result=$eval_verdict" \
                "eval_rounds=$eval_total_rounds" \
                "eval_score=$eval_score" 2>/dev/null || true
        fi

        ok "Task $task_id completed (eval: $eval_verdict, rounds: $eval_total_rounds, score: $eval_score)"
        write_task_status "$task_id" "completed" "Task finished (eval: $eval_verdict)" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

        local pr_url=""
        pr_url=$(cd "$project_path" && gh pr list --head "$branch" --json url -q '.[0].url' 2>/dev/null) || pr_url=""

        if [[ -n "$pr_url" ]]; then
            update_task_status "$task_file" "completed" "pr_url=$pr_url"
        else
            update_task_status "$task_file" "completed"
        fi

        # Async notifications
        "$HOME/Developer/claude-handler/fleet-notify.sh" --task-complete "$task_id" 2>/dev/null &
        "$HOME/Developer/claude-handler/memory-sync.sh" sync 2>/dev/null &
        "$HOME/Developer/claude-handler/fleet-backup.sh" 2>/dev/null &

        # Auto-merge safe PRs
        local auto_merged=false
        if [[ -n "$pr_url" ]]; then
            try_auto_merge "$task_file" "$task_id" "$branch" "$project_path" && auto_merged=true
        fi

        # Write review-queue item only if not auto-merged
        if [[ "$auto_merged" == "false" ]]; then
            local eval_section=""
            if [[ "$eval_verdict" != "SKIPPED" ]]; then
                eval_section="
**Eval Result:** ${eval_verdict} (score: ${eval_score}/100, rounds: ${eval_total_rounds})
"
                if [[ "$eval_verdict" == "FAIL" ]]; then
                    local last_verdict="$FLEET_DIR/eval/${task_id}.verdict-${eval_total_rounds}.json"
                    if [[ -f "$last_verdict" ]]; then
                        local issues
                        issues=$(python3 -c "import json; [print(f'- {i}') for i in json.load(open('${last_verdict}')).get('issues',[])]" 2>/dev/null) || issues=""
                        [[ -n "$issues" ]] && eval_section="${eval_section}
**Evaluator Issues:**
${issues}
"
                    fi
                fi
            fi

            cat > "$REVIEW_DIR/${task_id}-completed.md" << REVIEW_EOF
---
task_id: ${task_id}
project: $(basename "$project_path")
type: completed
priority: normal
eval_result: ${eval_verdict}
eval_score: ${eval_score}
eval_rounds: ${eval_total_rounds}
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Task Completed
${eval_section}${rebase_note:+
${rebase_note}
}
**Branch:** ${branch}
**Task:** $(echo "$task_prompt" | head -1)

Check the PR and summary:
- Summary: ~/.claude-fleet/logs/${task_id}.summary.md
- Eval verdicts: ~/.claude-fleet/eval/${task_id}.verdict-*.json
- Run \`/worker-review\` to review and merge.
REVIEW_EOF
        fi
    else
        local error_msg="exit code $exit_code"
        if [[ -f "$log_file" && -s "$log_file" ]]; then
            local extracted
            extracted=$(tail -5 "$log_file" 2>/dev/null | grep -i "error\|fail\|exception" | tail -1 | head -c 200) || extracted=""
            [[ -n "$extracted" ]] && error_msg="$extracted"
        fi
        log_error "D-013" "Claude exited non-zero for task $task_id (exit $exit_code): $error_msg"
        write_task_status "$task_id" "failed" "$error_msg" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"
        update_task_status "$task_file" "failed" "error_message=$error_msg"

        "$HOME/Developer/claude-handler/fleet-notify.sh" --task-failed "$task_id" 2>/dev/null &
        "$HOME/Developer/claude-handler/memory-sync.sh" sync 2>/dev/null &
        "$HOME/Developer/claude-handler/fleet-backup.sh" 2>/dev/null &

        cat > "$REVIEW_DIR/${task_id}-failed.md" << REVIEW_EOF
---
task_id: ${task_id}
project: $(basename "$project_path")
type: failed
priority: high
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Task Failed

**Branch:** ${branch}
**Exit code:** ${exit_code}
**Error:** ${error_msg}
**Task:** $(echo "$task_prompt" | head -1)

Check the log: ~/.claude-fleet/logs/${task_id}.log
REVIEW_EOF
    fi

    # ─── Release file locks (Layer 1) ────────────────────────
    release_file_locks "$task_id"

    # ─── Return to main (prevents stale branch for next task) ──
    if [[ -d "$project_path" ]]; then
        cd "$project_path" 2>/dev/null || true
        git checkout main 2>/dev/null || git checkout "$base_branch" 2>/dev/null || true
        git reset --hard "origin/$base_branch" 2>/dev/null || true
        log "[cleanup] Returned $project_path to $base_branch"
    fi
}

# ─── Async task launcher ─────────────────────────────────────────────────────

run_task_async() {
    local task_file="$1"
    local project
    project=$(task_field "$task_file" project_name "unknown")

    (
        run_task "$task_file" || err "run_task crashed for $(basename "$task_file")"
        rm -f "$RUNNING_DIR/$project.pid"
    ) &
    local pid=$!
    echo "$pid" > "$RUNNING_DIR/$project.pid"
    log "Started task in background (PID $pid, project: $project)"
}

# ─── Backlog dispatch ─────────────────────────────────────────────────────────

try_dispatch_backlog() {
    local backlog_file="$FLEET_DIR/backlog.json"
    [[ -f "$backlog_file" ]] || return 1

    local next_backlog
    next_backlog=$(python3 "$QM" backlog-next "$backlog_file" 2>&1) || {
        [[ -n "$next_backlog" ]] && log_error "D-020" "Queue manager backlog-next crash: ${next_backlog:0:100}"
        return 1
    }
    [[ -n "$next_backlog" ]] || { log "Backlog empty."; return 1; }

    # Parse backlog item fields
    local bl_slug bl_project bl_path bl_prompt_json bl_budget
    bl_slug=$(echo "$next_backlog" | python3 "$QM" backlog-field slug 2>/dev/null) || bl_slug="unknown"
    bl_project=$(echo "$next_backlog" | python3 "$QM" backlog-field project_name 2>/dev/null) || bl_project="unknown"
    bl_path=$(echo "$next_backlog" | python3 "$QM" backlog-field project_path 2>/dev/null) || bl_path=""
    bl_prompt_json=$(echo "$next_backlog" | python3 "$QM" backlog-field prompt "" --json 2>/dev/null) || bl_prompt_json='""'
    bl_budget=$(echo "$next_backlog" | python3 "$QM" backlog-field budget_usd 5 2>/dev/null) || bl_budget="5"

    if [[ -z "$bl_path" ]]; then
        warn "Backlog item missing project_path — skipping"
        return 1
    fi

    local bl_id="backlog-$(date +%Y%m%d-%H%M%S)-${bl_slug}"
    local bl_branch="worker/backlog-${bl_slug}-$(date +%Y%m%d)"

    ok "Backlog auto-dispatch: ${bl_slug} (${bl_project})"

    cat > "$TASKS_DIR/${bl_id}.json" << TASKEOF
{
  "id": "${bl_id}",
  "slug": "${bl_slug}",
  "branch": "${bl_branch}",
  "project_name": "${bl_project}",
  "project_path": "${bl_path}",
  "dispatched_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "status": "queued",
  "base_branch": "main",
  "prompt": ${bl_prompt_json},
  "budget_usd": ${bl_budget},
  "permission_mode": "auto",
  "source": "backlog"
}
TASKEOF
    return 0
}

# ─── Main loop ────────────────────────────────────────────────────────────────

# Crash detection on startup
detect_crash_restart

log "Worker daemon started (PARALLEL MODE)"
log "  Poll interval: ${POLL_INTERVAL}s"
log "  Claude CLI:    $CLAUDE_BIN"
log "  Tasks dir:     $TASKS_DIR"
log "  Review queue:  $REVIEW_DIR"
log "  Max parallel:  $MAX_PARALLEL"
log "  Task timeout:  ${TASK_TIMEOUT}s"
log "  Strategy:      1 task per project, up to $MAX_PARALLEL parallel"
echo ""

# Loop variables (declared outside loop — `local` only works in functions)
status="" project="" queued="" running="" now="" idle_secs=""
claimed_json="" claimed_id="" claimed_project="" task_file=""

DAILY_BUDGET="${DAILY_BUDGET:-50}"  # $50/day default, override with env var

while true; do
    CYCLE_COUNT=$((CYCLE_COUNT + 1))
    launched=0
    running=$(count_running)

    # ─── Daily budget check ───────────────────────────────────
    # Pause queue processing if daily spend exceeds budget.
    if [[ -f "$SCRIPT_DIR/task-db.py" ]]; then
        today_cost=$(python3 "$SCRIPT_DIR/task-db.py" cost-today 2>/dev/null || echo "0")
        today_cost="${today_cost//\$/}"  # strip $ sign
        if python3 -c "import sys; sys.exit(0 if float('${today_cost}') >= float('${DAILY_BUDGET}') else 1)" 2>/dev/null; then
            if (( CYCLE_COUNT % 60 == 1 )); then  # log once per ~10 min, not every cycle
                log "Daily budget reached (\$${today_cost}/\$${DAILY_BUDGET}). Queue paused."
            fi
            sleep "$POLL_INTERVAL"
            continue
        fi
    fi

    # ─── Sync new JSON tasks into SQLite ─────────────────────
    sync_json_to_db

    # ─── Stuck task auto-recovery (every ~5 min) ─────────────
    if (( CYCLE_COUNT % 30 == 0 )) && [[ -f "$TASK_DB" ]]; then
        recovered=$(python3 "$TASK_DB" recover-stuck --minutes 20 2>/dev/null) || recovered=""
        if [[ -n "$recovered" && "$recovered" != "Recovered 0 stuck tasks." ]]; then
            warn "Auto-recovery: $recovered"
        fi
    fi

    # ─── Task timeout enforcement ────────────────────────────
    check_task_timeouts

    # ─── Claim tasks from SQLite (atomic, priority-ordered) ──
    # SQLite claim handles: priority ordering, one-per-project,
    # dependency chains, parallel limits — all atomically.
    if [[ -f "$TASK_DB" ]]; then
        while (( (running + launched) < MAX_PARALLEL )); do
            claimed_json=""
            claimed_json=$(python3 "$TASK_DB" claim 2>/dev/null) || break

            claimed_id=""
            claimed_project=""
            claimed_id=$(echo "$claimed_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null) || break
            claimed_project=$(echo "$claimed_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['project_name'])" 2>/dev/null) || break

            # Skip if project is frozen
            if is_project_frozen "$claimed_project" 2>/dev/null; then
                log_error "D-041" "Project $claimed_project is frozen — task $claimed_id skipped"
                python3 "$TASK_DB" status "$claimed_id" "queued" 2>/dev/null
                break
            fi

            # Find the JSON file for run_task_async
            task_file="$TASKS_DIR/${claimed_id}.json"
            if [[ ! -f "$task_file" ]]; then
                log_error "D-060" "Claimed task $claimed_id but JSON file not found — writing from DB"
                # Write JSON from DB data so run_task can read it
                echo "$claimed_json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
json.dump(d, open(sys.argv[1], 'w'), indent=2)
" "$task_file" 2>/dev/null
            fi

            queued=$(count_tasks "queued")
            log "Launching task for $claimed_project ($queued queued) [SQLite claim]"
            run_task_async "$task_file"
            launched=$((launched + 1))
        done
    else
        # ─── Fallback: scan JSON files (legacy mode) ─────────
        for f in "$TASKS_DIR"/*.json; do
            [[ -f "$f" ]] || continue

            if (( (running + launched) >= MAX_PARALLEL )); then
                break
            fi

            status=""
            status=$(task_field "$f" status "")
            [[ "$status" == "queued" ]] || continue

            project=""
            project=$(task_field "$f" project_name "unknown")

            is_project_running "$project" && continue

            if is_project_frozen "$project" 2>/dev/null; then
                log_error "D-041" "Project $project is frozen — task skipped"
                continue
            fi

            queued=$(count_tasks "queued")
            log "Launching task for $project ($queued queued) [JSON fallback]"
            run_task_async "$f"
            launched=$((launched + 1))
        done
    fi

    if (( launched > 0 )); then
        running=$(count_running)
        log "Running $running tasks in parallel"
    fi

    # Adaptive poll interval
    running=$(count_running)
    queued=$(count_tasks "queued")

    # Write heartbeat + health every cycle
    write_heartbeat "$running" "$queued"
    daemon_health "$running" "$queued"

    # Reset crash counter after 10 min of stable operation
    reset_crash_counter_if_stable

    if (( running > 0 )); then
        sleep 10
        IDLE_SINCE=0
    elif (( queued > 0 )); then
        sleep 5
        IDLE_SINCE=0
    else
        # Queue empty — start idle timer, check backlog after 2 min
        if (( IDLE_SINCE == 0 )); then
            IDLE_SINCE=$(date +%s)
            log "Queue empty. Idle timer started."
        fi

        now=$(date +%s)
        idle_secs=$(( now - IDLE_SINCE ))

        if (( idle_secs >= 120 )); then
            if try_dispatch_backlog; then
                IDLE_SINCE=0
            else
                sleep "$POLL_INTERVAL"
            fi
        else
            sleep "$POLL_INTERVAL"
        fi
    fi
done
