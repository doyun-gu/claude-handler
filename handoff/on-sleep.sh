#!/bin/bash
# Runs when Commander machine goes to sleep (lid close, sleep command)
# Installed by sleepwatcher as ~/.sleep

export PATH=/opt/homebrew/bin:$HOME/.local/bin:$PATH
source ~/.claude-fleet/machine-role.conf 2>/dev/null
[[ "$MACHINE_ROLE" != "commander" ]] && exit 0

LOG="$HOME/.claude-fleet/logs/handoff.log"
echo "[$(date)] SLEEP — handing off to Worker" >> "$LOG"

# 1. Commit and push any uncommitted work across registered projects
python3 -c "
import json, subprocess, os
projects = json.load(open(os.path.expanduser('~/.claude-fleet/projects.json')))['projects']
for p in projects:
    path = p['path']
    if not os.path.isdir(path + '/.git'):
        continue
    # Check for uncommitted changes
    status = subprocess.run(['git', '-C', path, 'status', '--porcelain'], capture_output=True, text=True)
    if status.stdout.strip():
        subprocess.run(['git', '-C', path, 'add', '-A'], capture_output=True)
        subprocess.run(['git', '-C', path, 'commit', '-m', 'auto: save work before sleep'], capture_output=True)
        subprocess.run(['git', '-C', path, 'push', 'origin', 'HEAD'], capture_output=True, timeout=10)
        print(f'Saved: {p[\"name\"]}')
" >> "$LOG" 2>&1

# 2. Signal Mac Mini: commander is away
ssh -o ConnectTimeout=3 ${SSH_TARGET:-mac-mini} \
  "echo $(date -u +%Y-%m-%dT%H:%M:%SZ) > ~/.claude-fleet/commander-away" 2>> "$LOG"

echo "[$(date)] SLEEP complete" >> "$LOG"
