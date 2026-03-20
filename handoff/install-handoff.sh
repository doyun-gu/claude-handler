#!/bin/bash
# Install sleep/wake handoff on any Commander machine
# Usage: ./install-handoff.sh

set -euo pipefail

echo "Installing fleet handoff (sleep/wake hooks)..."

# 1. Install sleepwatcher if not present
if ! command -v sleepwatcher &>/dev/null; then
    if command -v brew &>/dev/null; then
        echo "Installing sleepwatcher via Homebrew..."
        brew install sleepwatcher
    else
        echo "ERROR: sleepwatcher not found and Homebrew not available."
        echo "Install manually: brew install sleepwatcher"
        exit 1
    fi
fi

# 2. Copy scripts
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/on-sleep.sh" ~/.sleep
cp "$SCRIPT_DIR/on-wake.sh" ~/.wakeup
chmod +x ~/.sleep ~/.wakeup

# 3. Start sleepwatcher as a launchd service
if ! launchctl list | grep -q sleepwatcher 2>/dev/null; then
    brew services start sleepwatcher
fi

# 4. Verify
echo ""
echo "Installed:"
echo "  ~/.sleep   — runs on lid close (commit + push + signal Mac Mini)"
echo "  ~/.wakeup  — runs on lid open (pull + resume command)"
echo ""
echo "Test: close and reopen your laptop lid, then check:"
echo "  cat ~/.claude-fleet/logs/handoff.log"
echo ""
echo "Works on any Commander machine with sleepwatcher + fleet config."
