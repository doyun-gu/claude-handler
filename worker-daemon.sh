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
TASK_TIMEOUT=7200  # 2 hours in seconds

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

# ─── Queue manager ────────────────────────────────────────────────────────────

if [[ -f "$SCRIPT_DIR/fleet-brain.py" ]]; then
    QM="$SCRIPT_DIR/fleet-brain.py"
    log "Using fleet-brain.py"
elif [[ -f "$SCRIPT_DIR/queue-manager.py" ]]; then
    QM="$SCRIPT_DIR/queue-manager.py"
    warn "fleet-brain.py not found, falling back to queue-manager.py"
else
    log_error "D-002" "Queue manager not found (fleet-brain.py or queue-manager.py)"
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

count_tasks() {
    local result
    result=$(python3 "$QM" count-status "$1" 2>&1) || {
        log_error "D-020" "Queue manager crash on count-status: ${result:0:100}"
        echo "0"
        return 1
    }
    echo "${result:-0}"
}

update_task_status() {
    python3 "$QM" update-status "$@" 2>/dev/null || log_error "D-020" "Queue manager crash on update-status for $1"
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
    log_error "D-004" "Stale PID file for $project (pid $pid dead) — auto-cleaning"
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
            log_error "D-005" "PID file race: $(basename "$pidfile") disappeared between check and read"
            rm -f "$pidfile"
            continue
        }
        if kill -0 "$pid" 2>/dev/null; then
            count=$((count + 1))
        else
            log_error "D-004" "Stale PID file: $(basename "$pidfile") (pid $pid dead) — auto-cleaning"
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

# ─── Run a single task ────────────────────────────────────────────────────────

run_task() {
    local task_file="$1"

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
        prompt_file_path="$TASKS_DIR/$prompt_file_ref"
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

    # Validate project path exists
    if [[ ! -d "$project_path" ]]; then
        log_error "D-011" "Project path does not exist: $project_path (task: $task_id)"
        update_task_status "$task_file" "failed" "error_message=Project path not found: $project_path"
        return 1
    fi

    log "Starting task: $task_id"
    log "  Project: $project_path"
    log "  Branch:  $branch"
    log "  Est:     $estimated_time"

    local task_started_at
    task_started_at=$(date +%s)
    update_task_status "$task_file" "running"
    write_task_status "$task_id" "starting" "Preparing git and environment" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

    # Prepare git
    cd "$project_path" || { err "cd failed: $project_path"; return 1; }
    git fetch origin 2>/dev/null || true

    if ! git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
        git checkout -b "$branch" "origin/$base_branch" 2>/dev/null ||
            git checkout -b "$branch" "$base_branch" 2>/dev/null ||
            git checkout -b "$branch" origin/main 2>/dev/null ||
            git checkout -b "$branch" main 2>/dev/null ||
            {
                log_error "D-012" "Cannot create or checkout branch $branch (task: $task_id)"
                update_task_status "$task_file" "failed" "error_message=Cannot create branch $branch"
                write_task_status "$task_id" "failed" "Cannot create branch $branch" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"
                return 1
            }
    else
        git checkout "$branch" 2>/dev/null || true
    fi
    git submodule update --init 2>/dev/null || true

    [[ -n "$subdir" ]] && { cd "$subdir" || { err "cd failed: $subdir"; return 1; }; }

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
11. PERFORMANCE: When running long computations (pytest suites, simulations, validation scripts), use run_in_background instead of waiting synchronously. Continue writing the next file, feature, or independent subtask while tests run. Check results before committing. Never block on a 5-minute test run when you have other work to do."

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
            prev_size=$cur_size
        done
    ) &
    heartbeat_pid=$!

    # ─── Run Claude in process group for clean cleanup ────────
    # setsid creates a new process group. On timeout/kill, we can
    # kill the entire group (Claude + children) with kill -PGID.
    if command -v script &>/dev/null && [[ "$(uname)" == "Darwin" ]]; then
        setsid script -q "$log_file" \
            "$CLAUDE_BIN" -p \
            --dangerously-skip-permissions \
            --max-turns "$max_turns" \
            --append-system-prompt "$worker_prompt" \
            "$task_prompt" \
            2>&1 || exit_code=$?
    elif command -v stdbuf &>/dev/null; then
        setsid stdbuf -oL "$CLAUDE_BIN" -p \
            --dangerously-skip-permissions \
            --max-turns "$max_turns" \
            --append-system-prompt "$worker_prompt" \
            "$task_prompt" \
            2>&1 | tee "$log_file" || exit_code=${PIPESTATUS[0]:-$?}
    else
        setsid "$CLAUDE_BIN" -p \
            --dangerously-skip-permissions \
            --max-turns "$max_turns" \
            --append-system-prompt "$worker_prompt" \
            "$task_prompt" \
            2>&1 | tee "$log_file" || exit_code=${PIPESTATUS[0]:-$?}
    fi

    # Stop heartbeat monitor
    kill "$heartbeat_pid" 2>/dev/null
    wait "$heartbeat_pid" 2>/dev/null

    # Handle result
    if [[ $exit_code -eq 0 ]]; then
        ok "Task $task_id completed successfully"
        write_task_status "$task_id" "completed" "Task finished successfully" "$(basename "$project_path")" "$branch" "$$" "$task_started_at"

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

        # Auto-merge safe PRs
        local auto_merged=false
        if [[ -n "$pr_url" ]]; then
            try_auto_merge "$task_file" "$task_id" "$branch" "$project_path" && auto_merged=true
        fi

        # Write review-queue item only if not auto-merged
        if [[ "$auto_merged" == "false" ]]; then
            cat > "$REVIEW_DIR/${task_id}-completed.md" << REVIEW_EOF
---
task_id: ${task_id}
project: $(basename "$project_path")
type: completed
priority: normal
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Task Completed

**Branch:** ${branch}
**Task:** $(echo "$task_prompt" | head -1)

Check the PR and summary:
- Summary: ~/.claude-fleet/logs/${task_id}.summary.md
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
  "permission_mode": "dangerously-skip-permissions",
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
log "  Strategy:      1 task per project, up to $MAX_PARALLEL parallel"
echo ""

# Loop variables (declared outside loop — `local` only works in functions)
status="" project="" queued="" running="" now="" idle_secs=""

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

    # Scan for queued tasks, one per project, up to MAX_PARALLEL
    for f in "$TASKS_DIR"/*.json; do
        [[ -f "$f" ]] || continue

        # Respect parallel limit
        if (( (running + launched) >= MAX_PARALLEL )); then
            if (( launched == 0 )); then
                log_error "D-051" "Too many running tasks ($running/$MAX_PARALLEL) — waiting"
            fi
            break
        fi

        status=""
        status=$(task_field "$f" status "")
        [[ "$status" == "queued" ]] || continue

        project=""
        project=$(task_field "$f" project_name "unknown")

        # Skip if project already has a running task
        is_project_running "$project" && continue

        # Skip if project is frozen (safe: never crashes the loop)
        if is_project_frozen "$project" 2>/dev/null; then
            log_error "D-041" "Project $project is frozen — task skipped"
            continue
        fi

        queued=$(count_tasks "queued")
        log "Launching task for $project ($queued queued)"
        run_task_async "$f"
        launched=$((launched + 1))
    done

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
