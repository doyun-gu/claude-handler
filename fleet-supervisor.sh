#!/bin/bash
# fleet-supervisor.sh — Ensures all fleet tmux sessions are alive.
# Managed by launchd. Checks every 30s, restarts dead sessions.

set -uo pipefail

# Dynamic PATH — include common tool directories that exist
for p in /opt/homebrew/bin "$HOME/.local/bin" /usr/local/bin; do
    [[ -d "$p" ]] && export PATH="$p:$PATH"
done

# Resolve handler directory from script location
HANDLER="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$HOME/.claude-fleet/logs/supervisor.log"
mkdir -p "$(dirname "$LOG_FILE")"

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

log "Fleet supervisor started (PID $$)"

while true; do
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
    fi

    sleep 30
done
