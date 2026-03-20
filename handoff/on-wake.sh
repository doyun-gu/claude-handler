#!/bin/bash
# Runs when Commander machine wakes up (lid open, wake from sleep)
# Installed by sleepwatcher as ~/.wakeup

export PATH=/opt/homebrew/bin:$HOME/.local/bin:$PATH
source ~/.claude-fleet/machine-role.conf 2>/dev/null
[[ "$MACHINE_ROLE" != "commander" ]] && exit 0

LOG="$HOME/.claude-fleet/logs/handoff.log"
echo "[$(date)] WAKE — resuming command" >> "$LOG"

# 1. Signal Mac Mini: commander is back
ssh -o ConnectTimeout=3 ${SSH_TARGET:-mac-mini} \
  "rm -f ~/.claude-fleet/commander-away" 2>> "$LOG"

# 2. Pull latest on all projects
python3 -c "
import json, subprocess, os
projects = json.load(open(os.path.expanduser('~/.claude-fleet/projects.json')))['projects']
for p in projects:
    path = p['path']
    if not os.path.isdir(path + '/.git'):
        continue
    subprocess.run(['git', '-C', path, 'fetch', 'origin'], capture_output=True, timeout=10)
    subprocess.run(['git', '-C', path, 'pull', '--ff-only', 'origin', 'HEAD'], capture_output=True, timeout=10)
" >> "$LOG" 2>&1

echo "[$(date)] WAKE complete" >> "$LOG"
