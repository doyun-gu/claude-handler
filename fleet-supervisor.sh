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
#
# Guardrails (in order of evaluation):
#   1. WORKER_MIN_UPTIME_SECS — hard floor. A fresh daemon is never killed
#      before this uptime, regardless of how WORKER_IDLE_RESTART_SECS is set.
#      Prevents misconfig or test-value overrides from flapping the daemon.
#   2. WORKER_IDLE_RESTART_SECS — normal threshold (default 24h).
#   3. RESTART_COOLDOWN_SECS — minimum wall-clock between two idle-restarts.
#      Persisted to IDLE_RESTART_STATE_FILE so survives supervisor restarts.
WORKER_IDLE_RESTART_SECS="${WORKER_IDLE_RESTART_SECS:-86400}"  # 24h
WORKER_MIN_UPTIME_SECS="${WORKER_MIN_UPTIME_SECS:-900}"        # 15 min hard floor
RESTART_COOLDOWN_SECS="${RESTART_COOLDOWN_SECS:-14400}"        # 4h cooldown
IDLE_RESTART_STATE_FILE="$HOME/.claude-fleet/.idle-restart-last"

idle_restart_worker_daemon() {
    tmux has-session -t worker-daemon 2>/dev/null || return 0

    local pane_pid
    pane_pid=$(tmux list-panes -t worker-daemon -F '#{pane_pid}' 2>/dev/null | head -1)
    [[ -n "$pane_pid" ]] || return 0

    # Parse ps etime — portable across macOS and Linux.
    # Formats: MM:SS | HH:MM:SS | DD-HH:MM:SS
    local etime d=0 h=0 m=0 s=0 uptime
    etime=$(ps -o etime= -p "$pane_pid" 2>/dev/null | tr -d ' ')
    [[ -n "$etime" ]] || return 0
    if [[ "$etime" == *-* ]]; then
        d="${etime%%-*}"
        etime="${etime#*-}"
    fi
    case "$etime" in
        *:*:*) IFS=: read -r h m s <<<"$etime" ;;
        *:*)   IFS=: read -r m s <<<"$etime" ;;
        *) return 0 ;;
    esac
    uptime=$(( 10#$d * 86400 + 10#$h * 3600 + 10#$m * 60 + 10#$s ))

    # Guardrail 1: hard minimum-uptime floor — never restart a fresh daemon.
    (( uptime >= WORKER_MIN_UPTIME_SECS )) || return 0

    # Guardrail 2: normal idle-restart threshold.
    (( uptime > WORKER_IDLE_RESTART_SECS )) || return 0

    # Guardrail 3: cooldown since last idle-restart.
    if [[ -f "$IDLE_RESTART_STATE_FILE" ]]; then
        local last_restart now_ts since_last
        last_restart=$(cat "$IDLE_RESTART_STATE_FILE" 2>/dev/null)
        now_ts=$(date +%s)
        since_last=$(( now_ts - ${last_restart:-0} ))
        if (( since_last < RESTART_COOLDOWN_SECS )); then
            return 0
        fi
    fi

    # Gate on task-db: only restart when fully idle.
    # grep -c always prints a number (including 0) so don't chain `|| echo 0` —
    # that would append a second "0" and break the arithmetic test below.
    local task_db="$HANDLER/task-db.py"
    [[ -f "$task_db" ]] || return 0
    local running queued
    running=$(python3 "$task_db" list running 2>/dev/null | grep -cE '^[[:space:]]*[a-z0-9]' || true)
    queued=$(python3 "$task_db" list queued 2>/dev/null | grep -cE '^[[:space:]]*[a-z0-9]' || true)
    running=${running:-0}
    queued=${queued:-0}
    (( running == 0 )) || return 0
    (( queued == 0 )) || return 0

    log "Worker-daemon uptime ${uptime}s exceeds ${WORKER_IDLE_RESTART_SECS}s and queue is idle — restarting"
    date +%s > "$IDLE_RESTART_STATE_FILE"
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
