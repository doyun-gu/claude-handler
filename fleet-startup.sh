#!/bin/bash
# fleet-startup.sh — Auto-start all fleet services on boot
# Installed as macOS LaunchAgent: runs on login
#
# Services are defined in ~/.claude-fleet/projects.json.
# Core fleet services (dashboard, worker daemon, health checker) always start.
# Project-specific services are loaded from the projects registry.

# ── Dynamic PATH detection ──────────────────────────
# Build PATH from common tool locations that exist on this machine
EXTRA_PATHS=""
for p in \
    "$HOME/.local/bin" \
    "$HOME/.bun/bin" \
    /opt/homebrew/bin \
    /opt/homebrew/sbin \
    /usr/local/bin \
    ; do
    [[ -d "$p" ]] && EXTRA_PATHS="$EXTRA_PATHS:$p"
done

# Detect nvm node if available
if [[ -d "$HOME/.nvm/versions/node" ]]; then
    NODE_DIR=$(ls -d "$HOME/.nvm/versions/node"/v* 2>/dev/null | sort -V | tail -1)
    [[ -n "$NODE_DIR" ]] && EXTRA_PATHS="$EXTRA_PATHS:$NODE_DIR/bin"
fi

# Detect Python framework if available
for py in /Library/Frameworks/Python.framework/Versions/*/bin; do
    [[ -d "$py" ]] && EXTRA_PATHS="$EXTRA_PATHS:$py"
done

export PATH="${EXTRA_PATHS#:}:$PATH"

# ── Resolve handler directory ───────────────────────
HANDLER_DIR="$(cd "$(dirname "$0")" && pwd)"
FLEET_DIR="$HOME/.claude-fleet"
LOG="$FLEET_DIR/logs/startup.log"
mkdir -p "$FLEET_DIR/logs"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(timestamp)] Fleet startup beginning..." >> "$LOG"

sleep 5  # Wait for network/disk

# ── Core fleet services ─────────────────────────────

# Fleet Dashboard (:3003)
if [[ -f "$HANDLER_DIR/dashboard/api.py" ]] && ! lsof -ti:3003 >/dev/null 2>&1; then
    tmux new-session -d -s fleet-dashboard-web \
        "cd $HANDLER_DIR/dashboard && python3 -m uvicorn api:app --host 0.0.0.0 --port 3003"
    echo "[$(timestamp)] Started: Fleet Dashboard :3003" >> "$LOG"
fi

# Worker Daemon
if ! tmux has-session -t worker-daemon 2>/dev/null; then
    tmux new-session -d -s worker-daemon \
        "cd $HANDLER_DIR && ./worker-daemon.sh 2>&1 | tee $FLEET_DIR/logs/daemon.log"
    echo "[$(timestamp)] Started: Worker Daemon" >> "$LOG"
fi

# Health Checker
if [[ -f "$HANDLER_DIR/demo-healthcheck.sh" ]] && ! tmux has-session -t demo-health 2>/dev/null; then
    tmux new-session -d -s demo-health \
        "cd $HANDLER_DIR && ./demo-healthcheck.sh 2>&1 | tee $FLEET_DIR/logs/demo-health.log"
    echo "[$(timestamp)] Started: Health Checker" >> "$LOG"
fi

# ── Project services from projects.json ─────────────
PROJECTS_FILE="$FLEET_DIR/projects.json"
if [[ -f "$PROJECTS_FILE" ]] && command -v python3 &>/dev/null; then
    python3 -c "
import json, subprocess, os

with open('$PROJECTS_FILE') as f:
    data = json.load(f)

for project in data.get('projects', []):
    for svc in project.get('services', []):
        name = svc.get('name', '')
        port = svc.get('port', 0)
        start_cmd = svc.get('start_cmd', '')
        project_path = os.path.expanduser(project.get('path', ''))

        if not name or not start_cmd or not project_path:
            continue
        if not os.path.isdir(project_path):
            continue

        # Check if port is already in use
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        in_use = sock.connect_ex(('localhost', port)) == 0
        sock.close()
        if in_use:
            continue

        # Check if tmux session exists
        result = subprocess.run(['tmux', 'has-session', '-t', name],
                                capture_output=True)
        if result.returncode == 0:
            continue

        # Start the service
        cmd = f'cd {project_path} && {start_cmd}'
        subprocess.run(['tmux', 'new-session', '-d', '-s', name, cmd])
        print(f'Started: {name} :{port}')
" 2>/dev/null | while read -r line; do
        echo "[$(timestamp)] $line" >> "$LOG"
    done
fi

echo "[$(timestamp)] Fleet startup complete." >> "$LOG"
