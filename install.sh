#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  claude-handler installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check ~/.claude exists
if [ ! -d "$CLAUDE_DIR" ]; then
    echo "Error: $CLAUDE_DIR does not exist. Is Claude Code installed?"
    exit 1
fi

# Create commands directory if needed
mkdir -p "$COMMANDS_DIR"

# --- Helper: symlink with backup ---

symlink_file() {
    local SOURCE="$1"
    local TARGET="$2"
    local LABEL="$3"

    if [ -f "$TARGET" ]; then
        if [ -L "$TARGET" ]; then
            LINK_TARGET="$(readlink "$TARGET")"
            if [ "$LINK_TARGET" = "$SOURCE" ]; then
                echo "  [ok] $LABEL already symlinked"
                return
            else
                mv "$TARGET" "$TARGET.backup"
                echo "  [backup] $LABEL — old symlink backed up"
            fi
        else
            mv "$TARGET" "$TARGET.backup"
            echo "  [backup] $LABEL — existing file backed up"
        fi
    fi

    ln -s "$SOURCE" "$TARGET"
    echo "  [ok] $LABEL symlinked"
}

# --- Global CLAUDE.md ---

echo "Global instructions:"
symlink_file "$SCRIPT_DIR/global/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md" "CLAUDE.md"
echo ""

# --- Core commands (from global/commands/) ---

echo "Core commands:"
for cmd_file in "$SCRIPT_DIR"/global/commands/*.md; do
    cmd="$(basename "$cmd_file")"
    symlink_file "$cmd_file" "$COMMANDS_DIR/$cmd" "commands/$cmd"
done
echo ""

# --- Notion commands (from notion/commands/) ---

if [ -d "$SCRIPT_DIR/notion/commands" ]; then
    echo "Notion commands:"
    for cmd_file in "$SCRIPT_DIR"/notion/commands/*.md; do
        cmd="$(basename "$cmd_file")"
        symlink_file "$cmd_file" "$COMMANDS_DIR/$cmd" "commands/$cmd"
    done
    echo ""
fi

# --- Summary ---

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Installation complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Installed commands:"
for cmd in "$COMMANDS_DIR"/*.md; do
    if [ -f "$cmd" ]; then
        name="$(basename "$cmd" .md)"
        echo "  /$name"
    fi
done
echo ""
echo "Run /cofounder to personalise Claude for your workflow."
echo "Restart Claude Code for changes to take effect."
echo ""
