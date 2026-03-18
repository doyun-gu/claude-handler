#!/bin/bash
set -e

CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  claude-handler uninstaller"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# --- Helper: remove symlink if it points to our repo ---

remove_symlink() {
    local TARGET="$1"
    local EXPECTED_SOURCE="$2"
    local LABEL="$3"

    if [ -L "$TARGET" ]; then
        LINK_TARGET="$(readlink "$TARGET")"
        if [ "$LINK_TARGET" = "$EXPECTED_SOURCE" ]; then
            rm "$TARGET"
            echo "  [ok] Removed $LABEL"

            # Restore backup if exists
            if [ -f "$TARGET.backup" ]; then
                mv "$TARGET.backup" "$TARGET"
                echo "  [ok] Restored $LABEL from backup"
            fi
        else
            echo "  [skip] $LABEL points elsewhere, not removing"
        fi
    elif [ -f "$TARGET" ]; then
        echo "  [skip] $LABEL is not a symlink, not removing"
    else
        echo "  [skip] $LABEL not found"
    fi
}

# --- Global CLAUDE.md ---

echo "Global instructions:"
remove_symlink "$CLAUDE_DIR/CLAUDE.md" "$SCRIPT_DIR/global/CLAUDE.md" "CLAUDE.md"
echo ""

# --- Core commands ---

echo "Core commands:"
for cmd_file in "$SCRIPT_DIR"/global/commands/*.md; do
    cmd="$(basename "$cmd_file")"
    remove_symlink "$COMMANDS_DIR/$cmd" "$cmd_file" "commands/$cmd"
done
echo ""

# --- Notion commands ---

if [ -d "$SCRIPT_DIR/notion/commands" ]; then
    echo "Notion commands:"
    for cmd_file in "$SCRIPT_DIR"/notion/commands/*.md; do
        cmd="$(basename "$cmd_file")"
        remove_symlink "$COMMANDS_DIR/$cmd" "$cmd_file" "commands/$cmd"
    done
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Uninstall complete."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
