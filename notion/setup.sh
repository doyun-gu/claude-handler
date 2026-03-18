#!/bin/bash
# notion/setup.sh — Notion MCP setup for Claude Code
# Usage: ./notion/setup.sh [user|local|project]

set -euo pipefail

SCOPE="${1:-user}"
URL="https://mcp.notion.com/mcp"

echo ""
echo "  Notion MCP Setup"
echo "  ─────────────────"
echo ""

# Check Node.js 18+
if ! command -v node &> /dev/null; then
    echo "  Node.js not found. Install 18+ from https://nodejs.org"
    exit 1
fi
NODE_V=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_V" -lt 18 ]; then
    echo "  Node.js $(node -v) too old. Need 18+."
    exit 1
fi
echo "  Node.js $(node -v) — ok"

# Check Claude CLI
if ! command -v claude &> /dev/null; then
    echo "  Claude Code CLI not found."
    echo "  Install: npm install -g @anthropic-ai/claude-code"
    exit 1
fi
echo "  Claude Code CLI — ok"

# Remove existing if present
if claude mcp list 2>/dev/null | grep -q "notion"; then
    echo ""
    read -p "  Notion MCP already configured. Reconfigure? (y/N): " R
    if [[ "$R" =~ ^[Yy]$ ]]; then
        claude mcp remove notion 2>/dev/null || true
    else
        echo "  Keeping existing config."
        exit 0
    fi
fi

# Register
echo ""
echo "  Registering (scope: $SCOPE)..."
claude mcp add --transport http --scope "$SCOPE" notion "$URL"

echo ""
echo "  Done. Next:"
echo "  1. Open Claude Code:  claude"
echo "  2. Authenticate:      /mcp"
echo "  3. Test:              Search my Notion for recent pages"
echo ""
