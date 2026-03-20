#!/bin/bash
# install-launchd.sh — Generate and install the fleet supervisor LaunchAgent
# Replaces template markers with the current user's paths.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$SCRIPT_DIR/launchd/com.fleet.supervisor.plist.template"
PLIST_NAME="com.fleet.supervisor.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
DEST="$LAUNCH_AGENTS_DIR/$PLIST_NAME"

if [[ ! -f "$TEMPLATE" ]]; then
    echo "Error: Template not found at $TEMPLATE"
    exit 1
fi

# Ensure log directory exists
mkdir -p "$HOME/.claude-fleet/logs"

# Generate plist from template
mkdir -p "$LAUNCH_AGENTS_DIR"
sed \
    -e "s|__HANDLER_DIR__|$SCRIPT_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    "$TEMPLATE" > "$DEST"

echo "Generated $DEST"

# Unload old version if running
launchctl unload "$DEST" 2>/dev/null || true

# Load the new plist
launchctl load "$DEST"
echo "LaunchAgent loaded. Fleet supervisor will start on login."
echo ""
echo "Commands:"
echo "  launchctl unload $DEST   # Stop"
echo "  launchctl load $DEST     # Start"
echo "  launchctl list | grep fleet  # Check status"
