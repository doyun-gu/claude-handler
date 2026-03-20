#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   claude-handler sync script
#   Run on a second machine to match the primary setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -e

# Detect the repo URL from the primary machine's config, or use the default
REPO_URL="${CLAUDE_HANDLER_REPO:-https://github.com/doyun-gu/claude-handler.git}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  claude-handler sync"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 1: Clone or pull claude-handler
HANDLER_DIR="$HOME/Developer/claude-handler"
if [ -d "$HANDLER_DIR" ]; then
    echo "[1/3] claude-handler already exists — pulling latest..."
    cd "$HANDLER_DIR" && git pull
else
    echo "[1/3] Cloning claude-handler..."
    mkdir -p "$HOME/Developer"
    git clone "$REPO_URL" "$HANDLER_DIR"
fi
echo ""

# Step 2: Run install.sh (symlinks global CLAUDE.md + all commands)
echo "[2/3] Running install.sh..."
cd "$HANDLER_DIR"
chmod +x install.sh
./install.sh
echo ""

# Step 3: User profile
echo "[3/3] User profile..."
if [ -f "$HOME/.claude/user-profile.md" ]; then
    echo "  User profile already exists — skipping."
    echo "  Run /cofounder to update it."
else
    echo "  No user profile found."
    echo "  Run /cofounder in Claude Code to create one."
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Sync complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Restart Claude Code for changes to take effect."
