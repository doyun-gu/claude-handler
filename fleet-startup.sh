#!/bin/bash
# fleet-startup.sh — Auto-start all fleet services on boot
# Installed as macOS LaunchAgent: runs on login

export PATH=/opt/homebrew/bin:/Users/doyungu/.local/bin:/Users/doyungu/.bun/bin:/Users/doyungu/.antigravity/antigravity/bin:/Users/doyungu/.local/bin:/Users/doyungu/.nvm/versions/node/v22.16.0/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/System/Cryptexes/App/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/local/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/appleinternal/bin:/opt/pmk/env/global/bin:/Applications/iTerm.app/Contents/Resources/utilities:/Applications/ArmGNUToolchain/13.3.rel1/arm-none-eabi/bin
LOG="/Users/doyungu/.claude-fleet/logs/startup.log"
mkdir -p /Users/doyungu/.claude-fleet/logs

echo "[Fri 20 Mar 2026 02:31:04 GMT] Fleet startup beginning..." >> "$LOG"

sleep 5  # Wait for network/disk

# 1. DPSpice API server
if ! lsof -ti:8000 >/dev/null 2>&1; then
    tmux new-session -d -s dpspice-api "cd ~/Developer/dynamic-phasors/DPSpice-com && PYTHONPATH=src/python .venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000"
    echo "[Fri 20 Mar 2026 02:31:04 GMT] Started: DPSpice API :8000" >> "$LOG"
fi

# 2. DPSpice Web (stable demo :3001)
if ! lsof -ti:3001 >/dev/null 2>&1; then
    tmux new-session -d -s dpspice-web "cd ~/Developer/dynamic-phasors/DPSpice-com/web && PORT=3001 npm run dev"
    echo "[Fri 20 Mar 2026 02:31:04 GMT] Started: DPSpice Web :3001" >> "$LOG"
fi

# 3. DPSpice Preview/Demo (:3002)
if ! lsof -ti:3002 >/dev/null 2>&1; then
    tmux new-session -d -s dpspice-preview "cd ~/Developer/dynamic-phasors/DPSpice-com/web && PORT=3002 npm run dev"
    echo "[Fri 20 Mar 2026 02:31:04 GMT] Started: DPSpice Demo :3002" >> "$LOG"
fi

# 4. Fleet Dashboard (:3003)
if ! lsof -ti:3003 >/dev/null 2>&1; then
    tmux new-session -d -s fleet-dashboard-web "cd ~/Developer/claude-handler/dashboard && python3 -m uvicorn api:app --host 0.0.0.0 --port 3003"
    echo "[Fri 20 Mar 2026 02:31:04 GMT] Started: Fleet Dashboard :3003" >> "$LOG"
fi

# 5. Worker Daemon
if ! tmux has-session -t worker-daemon 2>/dev/null; then
    tmux new-session -d -s worker-daemon "cd ~/Developer/claude-handler && ./worker-daemon.sh 2>&1 | tee ~/.claude-fleet/logs/daemon.log"
    echo "[Fri 20 Mar 2026 02:31:04 GMT] Started: Worker Daemon" >> "$LOG"
fi

# 6. Health Checker
if ! tmux has-session -t demo-health 2>/dev/null; then
    tmux new-session -d -s demo-health "cd ~/Developer/claude-handler && ./demo-healthcheck.sh 2>&1 | tee ~/.claude-fleet/logs/demo-health.log"
    echo "[Fri 20 Mar 2026 02:31:04 GMT] Started: Health Checker" >> "$LOG"
fi

echo "[Fri 20 Mar 2026 02:31:04 GMT] Fleet startup complete." >> "$LOG"
