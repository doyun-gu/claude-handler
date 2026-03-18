#!/bin/bash
# notion/install-commands.sh
# Installs Notion slash commands into Claude Code's global commands directory
# so they're available across all projects.
#
# Usage:
#   chmod +x notion/install-commands.sh
#   ./notion/install-commands.sh

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")/commands" && pwd)"
TARGET_DIR="$HOME/.claude/commands"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Notion Slash Commands Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create target directory
mkdir -p "$TARGET_DIR"

# Count commands
COUNT=$(ls "$SOURCE_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
echo "Found $COUNT commands to install"
echo ""

# Copy each command
for file in "$SOURCE_DIR"/*.md; do
    filename=$(basename "$file")
    cp "$file" "$TARGET_DIR/$filename"
    echo "  ✓ /$( echo "$filename" | sed 's/\.md$//' )"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Installed to: $TARGET_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Available commands in Claude Code:"
echo ""
echo "  /notion-sync [project|all]     Sync Notion ↔ dev markdown files"
echo "  /notion-progress [project]     Log today's work to Notion"
echo "  /notion-done [project]         End-of-session handoff to Notion"
echo "  /notion-status [project|all]   Quick status report from Notion"
echo "  /notion-decision [project] [summary]   Log a technical decision"
echo "  /notion-milestone [project] [desc] [date]   Add/update milestone"
echo "  /notion-doc [project] [topic]  Create a new documentation page"
echo "  /notion-search [query]         Search the workspace"
echo "  /notion-review [project]       Audit docs for quality issues"
echo ""
echo "  Restart Claude Code for commands to take effect."
echo ""
