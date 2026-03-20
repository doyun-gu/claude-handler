#!/bin/bash
# worker-daemon.sh — Autonomous Worker daemon for Mac Mini
# Watches the task queue and runs Claude sessions continuously.
# Usage: ./worker-daemon.sh [--poll-interval 30]
#
# Start in tmux on Mac Mini:
#   tmux new-session -d -s worker-daemon "cd ~/Developer/claude-handler && ./worker-daemon.sh"

set -euo pipefail

FLEET_DIR="$HOME/.claude-fleet"
TASKS_DIR="$FLEET_DIR/tasks"
LOGS_DIR="$FLEET_DIR/logs"
REVIEW_DIR="$FLEET_DIR/review-queue"
POLL_INTERVAL="${1:-30}"  # seconds between queue checks

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[daemon $(date +%H:%M:%S)]${NC} $1"; }
warn() { echo -e "${YELLOW}[daemon $(date +%H:%M:%S)]${NC} $1"; }
err() { echo -e "${RED}[daemon $(date +%H:%M:%S)]${NC} $1"; }
ok() { echo -e "${GREEN}[daemon $(date +%H:%M:%S)]${NC} $1"; }

# Ensure directories exist
mkdir -p "$TASKS_DIR" "$LOGS_DIR" "$REVIEW_DIR"

# Read machine role
if [[ ! -f "$FLEET_DIR/machine-role.conf" ]]; then
    err "No machine-role.conf found. This script should run on the Worker (Mac Mini)."
    exit 1
fi
source "$FLEET_DIR/machine-role.conf"
if [[ "${MACHINE_ROLE:-}" != "worker" ]]; then
    warn "MACHINE_ROLE is '$MACHINE_ROLE', not 'worker'. Proceeding anyway..."
fi

CLAUDE_BIN="${WORKER_CLAUDE_BIN:-$HOME/.local/bin/claude}"
if [[ ! -x "$CLAUDE_BIN" ]]; then
    err "Claude CLI not found at $CLAUDE_BIN"
    exit 1
fi

# Find the next queued task (oldest first)
next_queued_task() {
    # Single Python call to find oldest queued task (was one Python per file)
    python3 -c "
import json, glob, os
queued = []
for f in glob.glob('$TASKS_DIR/*.json'):
    try:
        if json.load(open(f)).get('status') == 'queued':
            queued.append((os.path.getmtime(f), f))
    except: pass
if queued:
    queued.sort()
    print(queued[0][1])
" 2>/dev/null
}

# Count tasks by status (single Python call instead of one per file)
count_tasks() {
    local status="$1"
    python3 -c "
import json, glob
count = sum(1 for f in glob.glob('$TASKS_DIR/*.json')
            if json.load(open(f)).get('status') == '$status')
print(count)
" 2>/dev/null || echo 0
}

# Update task status
update_task_status() {
    local task_file="$1"
    local new_status="$2"
    python3 -c "
import json
f = open('$task_file', 'r+')
d = json.load(f)
d['status'] = '$new_status'
$(if [[ "$new_status" == "running" ]]; then echo "import datetime; d['started_at'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')"; fi)
$(if [[ "$new_status" == "completed" || "$new_status" == "failed" ]]; then echo "import datetime; d['finished_at'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')"; fi)
f.seek(0); json.dump(d, f, indent=2); f.truncate()
f.close()
"
}

# Run a single task
run_task() {
    local task_file="$1"
    local task_id task_prompt project_path branch permission_mode subdir budget

    # Read all fields in a single Python call (was 8 separate processes)
    eval "$(python3 -c "
import json, shlex
d = json.load(open('$task_file'))
for k, default in [('id',''), ('prompt',''), ('project_path',''), ('branch',''),
                    ('permission_mode','auto'), ('subdir',''), ('budget_usd',5), ('base_branch','main')]:
    v = d.get(k, default) or default
    var = {'id':'task_id','prompt':'task_prompt','project_path':'project_path','branch':'branch',
           'permission_mode':'permission_mode','subdir':'subdir','budget_usd':'budget',
           'base_branch':'base_branch'}[k]
    print(f'{var}={shlex.quote(str(v))}')
")"
    local base_branch="${base_branch}"

    local work_dir="$project_path"
    [[ -n "$subdir" ]] && work_dir="$project_path/$subdir"

    log "Starting task: $task_id"
    log "  Project: $project_path"
    log "  Branch:  $branch"
    log "  Budget:  \$$budget"

    # Update status
    update_task_status "$task_file" "running"

    # Ensure repo is ready
    cd "$project_path"
    git fetch origin 2>/dev/null || true

    # Create branch if it doesn't exist (use base_branch from manifest)
    if ! git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
        # Try origin/base_branch first, then local base_branch, then origin/main
        git checkout -b "$branch" "origin/$base_branch" 2>/dev/null \
            || git checkout -b "$branch" "$base_branch" 2>/dev/null \
            || git checkout -b "$branch" origin/main 2>/dev/null \
            || git checkout -b "$branch" main 2>/dev/null \
            || true
    else
        git checkout "$branch" 2>/dev/null || true
    fi
    git submodule update --init 2>/dev/null || true

    [[ -n "$subdir" ]] && cd "$subdir"

    # Build worker system prompt
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
9. Use gstack skills as appropriate: /review before pushing, /qa if testing a web app.
10. There are ${queued_count} more tasks in the queue after this one. Work efficiently — the daemon will start the next task when you finish."

    local perm_flag="--dangerously-skip-permissions"

    # Run Claude
    local log_file="$LOGS_DIR/${task_id}.log"

    "$CLAUDE_BIN" -p \
        $perm_flag \
        --max-turns 200 \
        --append-system-prompt "$worker_prompt" \
        "$task_prompt" \
        2>&1 | tee "$log_file"

    local exit_code=${PIPESTATUS[0]}

    # Check result
    if [[ $exit_code -eq 0 ]]; then
        ok "Task $task_id completed successfully"
        update_task_status "$task_file" "completed"

        # Email notification
        "$HOME/Developer/claude-handler/fleet-notify.sh" --task-complete "$task_id" 2>/dev/null &

        # Write a review-queue item so Commander knows
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
    else
        err "Task $task_id failed with exit code $exit_code"
        update_task_status "$task_file" "failed"

        # Email notification
        "$HOME/Developer/claude-handler/fleet-notify.sh" --task-failed "$task_id" 2>/dev/null &

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
**Task:** $(echo "$task_prompt" | head -1)

Check the log: ~/.claude-fleet/logs/${task_id}.log
REVIEW_EOF
    fi
}

# ─── Track running projects (file-based for bash 3 compat) ───

RUNNING_DIR="/tmp/fleet-running"
mkdir -p "$RUNNING_DIR"

# Check if a project already has a running task
is_project_running() {
    local project="$1"
    local pidfile="$RUNNING_DIR/$project.pid"
    if [[ -f "$pidfile" ]]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            return 0  # Still running
        fi
        rm -f "$pidfile"
    fi
    return 1  # Not running
}

# Run a task in the background
run_task_async() {
    local task_file="$1"
    local project
    project=$(python3 -c "import json; print(json.load(open('$task_file')).get('project_name','unknown'))")

    (
        run_task "$task_file" || err "run_task crashed for $(basename "$task_file")"
        rm -f "$RUNNING_DIR/$project.pid"
    ) &
    local pid=$!
    echo "$pid" > "$RUNNING_DIR/$project.pid"
    log "Started task in background (PID $pid, project: $project)"
}

# Count currently running tasks
count_running() {
    local count=0
    for pidfile in "$RUNNING_DIR"/*.pid; do
        [[ -f "$pidfile" ]] || continue
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            count=$((count + 1))
        else
            rm -f "$pidfile"
        fi
    done
    echo "$count"
}

# ─── Main loop (parallel per project) ────────────────────────

log "Worker daemon started (PARALLEL MODE)"
log "  Poll interval: ${POLL_INTERVAL}s"
log "  Claude CLI:    $CLAUDE_BIN"
log "  Tasks dir:     $TASKS_DIR"
log "  Review queue:  $REVIEW_DIR"
log "  Strategy:      1 task per project in parallel, same-project tasks queue"
echo ""

while true; do
    launched=0

    # Find queued tasks, one per project (single Python call for all files)
    while IFS='|' read -r task_file project; do
        [[ -z "$task_file" ]] && continue
        if is_project_running "$project"; then continue; fi
        queued=$(count_tasks "queued")
        log "Launching task for $project ($queued in queue)"
        run_task_async "$task_file"
        launched=$((launched + 1))
    done < <(python3 -c "
import json, glob
for f in glob.glob('$TASKS_DIR/*.json'):
    try:
        d = json.load(open(f))
        if d.get('status') == 'queued':
            print(f + '|' + d.get('project_name','unknown'))
    except: pass
" 2>/dev/null)

    if (( launched > 0 )); then
        running=$(count_running)
        log "Running $running tasks in parallel"
    fi

    # Poll interval: faster when tasks are active
    running=$(count_running)
    if (( running > 0 )); then
        sleep 10
    else
        sleep "$POLL_INTERVAL"
    fi
done
