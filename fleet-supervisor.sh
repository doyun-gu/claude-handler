#!/bin/bash
# fleet-supervisor.sh — Ensures all fleet tmux sessions are alive.
# Managed by launchd. Checks every 30s, restarts dead sessions.
# Auto-restarts services when their code changes (git pull detection).

set -uo pipefail

# Dynamic PATH — include common tool directories that exist
for p in /opt/homebrew/bin "$HOME/.local/bin" /usr/local/bin; do
    [[ -d "$p" ]] && export PATH="$p:$PATH"
done

# Resolve handler directory from script location
HANDLER="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$HOME/.claude-fleet/logs/supervisor.log"
COMMIT_CACHE="$HOME/.claude-fleet/.supervisor-commits"
mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$COMMIT_CACHE")"

log() { echo "[supervisor $(date +%Y-%m-%dT%H:%M:%S)] $1" | tee -a "$LOG_FILE"; }

ensure_session() {
    local name="$1"
    local cmd="$2"

    if ! tmux has-session -t "$name" 2>/dev/null; then
        log "Session '$name' is dead — restarting"
        tmux new-session -d -s "$name" "$cmd"
        if tmux has-session -t "$name" 2>/dev/null; then
            log "Session '$name' restarted successfully"
        else
            log "ERROR: Failed to restart session '$name'"
        fi
    fi
}

# Check if a repo has new commits and restart its service if so
check_and_restart() {
    local repo_path="$1"
    local session_name="$2"
    local start_cmd="$3"
    local cache_key
    cache_key=$(echo "$repo_path" | tr '/' '_')

    # Get current commit
    local current_commit
    current_commit=$(git -C "$repo_path" rev-parse HEAD 2>/dev/null) || return

    # Get cached commit
    local cached_commit=""
    if [[ -f "${COMMIT_CACHE}_${cache_key}" ]]; then
        cached_commit=$(cat "${COMMIT_CACHE}_${cache_key}")
    fi

    # If commit changed, restart the service
    if [[ "$current_commit" != "$cached_commit" ]]; then
        if [[ -n "$cached_commit" ]]; then
            log "Code changed in $(basename "$repo_path") — restarting '$session_name'"
            tmux kill-session -t "$session_name" 2>/dev/null
            sleep 1
            tmux new-session -d -s "$session_name" "$start_cmd"
            if tmux has-session -t "$session_name" 2>/dev/null; then
                log "Session '$session_name' restarted after code change"
            else
                log "ERROR: Failed to restart '$session_name' after code change"
            fi
        fi
        echo "$current_commit" > "${COMMIT_CACHE}_${cache_key}"
    fi
}

log "Fleet supervisor started (PID $$)"

# Idle-restart policy for worker-daemon tmux session.
# Long-running bash shells accumulate env drift, zombie background jobs,
# and file-handle leaks. Restart when: uptime > threshold AND no running
# tasks AND no immediately-runnable queued tasks. Restart is safe because
# ensure_session below will respawn the session on the next cycle.
WORKER_IDLE_RESTART_SECS="${WORKER_IDLE_RESTART_SECS:-86400}"  # 24h

idle_restart_worker_daemon() {
    tmux has-session -t worker-daemon 2>/dev/null || return 0

    local pane_pid uptime
    pane_pid=$(tmux list-panes -t worker-daemon -F '#{pane_pid}' 2>/dev/null | head -1)
    [[ -n "$pane_pid" ]] || return 0
    uptime=$(ps -o etimes= -p "$pane_pid" 2>/dev/null | tr -d ' ')
    [[ "$uptime" =~ ^[0-9]+$ ]] || return 0
    (( uptime > WORKER_IDLE_RESTART_SECS )) || return 0

    # Gate on task-db: only restart when fully idle
    local task_db="$HANDLER/task-db.py"
    [[ -f "$task_db" ]] || return 0
    local running queued
    running=$(python3 "$task_db" list running 2>/dev/null | grep -cE '^[[:space:]]*[a-z0-9]' || echo 0)
    queued=$(python3 "$task_db" list queued 2>/dev/null | grep -cE '^[[:space:]]*[a-z0-9]' || echo 0)
    (( running == 0 )) || return 0
    (( queued == 0 )) || return 0

    log "Worker-daemon uptime ${uptime}s exceeds ${WORKER_IDLE_RESTART_SECS}s and queue is idle — restarting"
    tmux kill-session -t worker-daemon 2>/dev/null
    # ensure_session on the next loop iteration will respawn it
}

while true; do
    idle_restart_worker_daemon

    ensure_session "worker-daemon" \
        "cd $HANDLER && ./worker-daemon.sh 2>&1 | tee -a $HOME/.claude-fleet/logs/worker-daemon.log"

    if [[ -f "$HANDLER/demo-healthcheck.sh" ]]; then
        ensure_session "demo-health" \
            "cd $HANDLER && ./demo-healthcheck.sh 2>&1 | tee -a $HOME/.claude-fleet/logs/demo-health.log"
    fi

    # Dashboard — only if api.py exists
    if [[ -f "$HANDLER/dashboard/api.py" ]]; then
        ensure_session "fleet-dashboard" \
            "cd $HANDLER/dashboard && python3 api.py 2>&1 | tee -a $HOME/.claude-fleet/logs/dashboard.log"

        # Auto-restart dashboard if claude-handler code changed
        check_and_restart "$HANDLER" "fleet-dashboard" \
            "cd $HANDLER/dashboard && python3 api.py 2>&1 | tee -a $HOME/.claude-fleet/logs/dashboard.log"
    fi

    sleep 30
done
