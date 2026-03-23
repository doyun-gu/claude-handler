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
POLL_INTERVAL="${1:-30}"
IDLE_SINCE=0
MAX_PARALLEL=3

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

# ─── Script directory (fail fast if unresolvable) ─────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$SCRIPT_DIR" || ! -d "$SCRIPT_DIR" ]]; then
    echo "FATAL: Cannot resolve script directory" >&2
    exit 1
fi

# ─── Directories ──────────────────────────────────────────────────────────────

mkdir -p "$TASKS_DIR" "$LOGS_DIR" "$REVIEW_DIR" "$RUNNING_DIR"

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
    err "Claude CLI not found at $CLAUDE_BIN"
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
    err "No queue manager found (fleet-brain.py or queue-manager.py)"
    exit 1
fi

# ─── Safe wrappers for queue manager calls ────────────────────────────────────
# These never crash the daemon — they return empty/default on failure.

task_field() {
    python3 "$QM" task-field "$@" 2>/dev/null || echo ""
}

count_tasks() {
    local result
    result=$(python3 "$QM" count-status "$1" 2>/dev/null) || result="0"
    echo "${result:-0}"
}

update_task_status() {
    python3 "$QM" update-status "$@" 2>/dev/null || warn "Failed to update status for $1"
}

# ─── Safe file read (TOCTOU-resistant) ────────────────────────────────────────

read_pidfile() {
    local pidfile="$1"
    local pid=""
    pid=$(cat "$pidfile" 2>/dev/null) || return 1
    [[ -n "$pid" ]] && echo "$pid" || return 1
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
    rm -f "$pidfile"
    return 1  # Stale PID, cleaned up
}

is_project_frozen() {
    local project="$1"
    [[ -f "$EVENTS_FILE" ]] || return 1

    python3 -c "
import json, sys
from datetime import datetime, timezone
project = sys.argv[1]
try:
    events = json.loads(open(sys.argv[2]).read())
except Exception:
    sys.exit(1)
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
" "$project" "$EVENTS_FILE" 2>/dev/null
}

count_running() {
    local count=0
    local pidfile pid
    for pidfile in "$RUNNING_DIR"/*.pid; do
        [[ -f "$pidfile" ]] || continue
        pid=$(read_pidfile "$pidfile") || { rm -f "$pidfile"; continue; }
        if kill -0 "$pid" 2>/dev/null; then
            count=$((count + 1))
        else
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
        warn "[auto-merge] No open PR for branch '$branch' in $repo"
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
        warn "[auto-merge] Failed to merge PR #$pr_number"
        return 1
    fi
}

# ─── Run a single task ────────────────────────────────────────────────────────

run_task() {
    local task_file="$1"

    # Read task manifest — validate critical fields
    local task_id task_prompt project_path branch
    task_id=$(task_field "$task_file" id)
    task_prompt=$(task_field "$task_file" prompt)
    project_path=$(task_field "$task_file" project_path)
    branch=$(task_field "$task_file" branch)

    if [[ -z "$task_id" || -z "$task_prompt" || -z "$project_path" || -z "$branch" ]]; then
        err "Task manifest missing required fields: $task_file"
        err "  id='$task_id' prompt='${task_prompt:0:30}...' path='$project_path' branch='$branch'"
        update_task_status "$task_file" "failed" "error_message=Missing required fields in manifest"
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
        err "Project path does not exist: $project_path"
        update_task_status "$task_file" "failed" "error_message=Project path not found: $project_path"
        return 1
    fi

    log "Starting task: $task_id"
    log "  Project: $project_path"
    log "  Branch:  $branch"
    log "  Est:     $estimated_time"

    update_task_status "$task_file" "running"

    # Prepare git
    cd "$project_path" || { err "cd failed: $project_path"; return 1; }
    git fetch origin 2>/dev/null || true

    if ! git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
        git checkout -b "$branch" "origin/$base_branch" 2>/dev/null ||
            git checkout -b "$branch" "$base_branch" 2>/dev/null ||
            git checkout -b "$branch" origin/main 2>/dev/null ||
            git checkout -b "$branch" main 2>/dev/null ||
            { err "Cannot create branch $branch"; return 1; }
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

    if command -v script &>/dev/null && [[ "$(uname)" == "Darwin" ]]; then
        script -q "$log_file" \
            "$CLAUDE_BIN" -p \
            --dangerously-skip-permissions \
            --max-turns 200 \
            --append-system-prompt "$worker_prompt" \
            "$task_prompt" \
            2>&1 || exit_code=$?
    elif command -v stdbuf &>/dev/null; then
        stdbuf -oL "$CLAUDE_BIN" -p \
            --dangerously-skip-permissions \
            --max-turns 200 \
            --append-system-prompt "$worker_prompt" \
            "$task_prompt" \
            2>&1 | tee "$log_file" || exit_code=${PIPESTATUS[0]:-$?}
    else
        "$CLAUDE_BIN" -p \
            --dangerously-skip-permissions \
            --max-turns 200 \
            --append-system-prompt "$worker_prompt" \
            "$task_prompt" \
            2>&1 | tee "$log_file" || exit_code=${PIPESTATUS[0]:-$?}
    fi

    # Handle result
    if [[ $exit_code -eq 0 ]]; then
        ok "Task $task_id completed successfully"

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
        err "Task $task_id failed (exit $exit_code)"

        local error_msg="exit code $exit_code"
        if [[ -f "$log_file" && -s "$log_file" ]]; then
            local extracted
            extracted=$(tail -5 "$log_file" 2>/dev/null | grep -i "error\|fail\|exception" | tail -1 | head -c 200) || extracted=""
            [[ -n "$extracted" ]] && error_msg="$extracted"
        fi
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
    next_backlog=$(python3 "$QM" backlog-next "$backlog_file" 2>/dev/null) || return 1
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

while true; do
    launched=0
    running=$(count_running)

    # Scan for queued tasks, one per project, up to MAX_PARALLEL
    for f in "$TASKS_DIR"/*.json; do
        [[ -f "$f" ]] || continue

        # Respect parallel limit
        if (( (running + launched) >= MAX_PARALLEL )); then
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
            warn "Skipping $project — frozen"
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
