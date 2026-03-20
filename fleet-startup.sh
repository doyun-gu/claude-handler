#!/bin/bash
# fleet-startup.sh — Auto-start all fleet services on boot
# Installed as macOS LaunchAgent: runs on login
#
# This script starts:
#   1. Fleet Dashboard (web UI at :3003)
#   2. Worker Daemon (autonomous task runner)
#
# To add your own services, create ~/.claude-fleet/startup-hooks.sh
# with any additional tmux sessions you want started.

export PATH=/opt/homebrew/bin:$HOME/.local/bin:$HOME/.bun/bin:/usr/local/bin:$PATH
LOG="$HOME/.claude-fleet/logs/startup.log"
mkdir -p "$HOME/.claude-fleet/logs"
HANDLER_DIR="$(cd "$(dirname "$0")" && pwd)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

log "Fleet startup beginning..."

sleep 5  # Wait for network/disk

# 1. Fleet Dashboard (:3003)
if [[ -f "$HANDLER_DIR/dashboard/api.py" ]] && ! lsof -ti:3003 >/dev/null 2>&1; then
    tmux new-session -d -s fleet-dashboard "cd $HANDLER_DIR/dashboard && python3 -m uvicorn api:app --host 0.0.0.0 --port 3003"
    log "Started: Fleet Dashboard :3003"
fi

# 2. Worker Daemon
if ! tmux has-session -t worker-daemon 2>/dev/null; then
    tmux new-session -d -s worker-daemon "cd $HANDLER_DIR && ./worker-daemon.sh 2>&1 | tee -a $HOME/.claude-fleet/logs/daemon.log"
    log "Started: Worker Daemon"
fi

# 3. User-defined startup hooks
if [[ -f "$HOME/.claude-fleet/startup-hooks.sh" ]]; then
    log "Running user startup hooks..."
    bash "$HOME/.claude-fleet/startup-hooks.sh"
    log "User startup hooks complete"
fi

log "Fleet startup complete."
