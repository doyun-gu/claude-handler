#!/bin/bash
set -e

CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Uninstalling claude-handler..."
echo ""

# --- Remove CLAUDE.md symlink ---

if [ -L "$CLAUDE_DIR/CLAUDE.md" ]; then
    LINK_TARGET="$(readlink "$CLAUDE_DIR/CLAUDE.md")"
    if [ "$LINK_TARGET" = "$SCRIPT_DIR/global/CLAUDE.md" ]; then
        rm "$CLAUDE_DIR/CLAUDE.md"
        echo "[ok] Removed CLAUDE.md symlink"

        # Restore backup if exists
        if [ -f "$CLAUDE_DIR/CLAUDE.md.backup" ]; then
            mv "$CLAUDE_DIR/CLAUDE.md.backup" "$CLAUDE_DIR/CLAUDE.md"
            echo "[ok] Restored CLAUDE.md from backup"
        fi
    else
        echo "[skip] CLAUDE.md symlink points to something else, not removing"
    fi
elif [ -f "$CLAUDE_DIR/CLAUDE.md" ]; then
    echo "[skip] CLAUDE.md is not a symlink, not removing"
else
    echo "[skip] No CLAUDE.md found"
fi

# --- Remove command symlinks ---

for cmd in startup.md onboard.md; do
    TARGET="$COMMANDS_DIR/$cmd"

    if [ -L "$TARGET" ]; then
        LINK_TARGET="$(readlink "$TARGET")"
        if [ "$LINK_TARGET" = "$SCRIPT_DIR/global/commands/$cmd" ]; then
            rm "$TARGET"
            echo "[ok] Removed commands/$cmd symlink"

            # Restore backup if exists
            if [ -f "$TARGET.backup" ]; then
                mv "$TARGET.backup" "$TARGET"
                echo "[ok] Restored commands/$cmd from backup"
            fi
        else
            echo "[skip] commands/$cmd symlink points to something else, not removing"
        fi
    elif [ -f "$TARGET" ]; then
        echo "[skip] commands/$cmd is not a symlink, not removing"
    else
        echo "[skip] commands/$cmd not found"
    fi
done

echo ""
echo "Uninstall complete. Existing commands (ready2modify, workdone) were not touched."
