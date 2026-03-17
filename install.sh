#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"

echo "Installing claude-handler..."
echo ""

# Check ~/.claude exists
if [ ! -d "$CLAUDE_DIR" ]; then
    echo "Error: $CLAUDE_DIR does not exist. Is Claude Code installed?"
    exit 1
fi

# Create commands directory if needed
mkdir -p "$COMMANDS_DIR"

# --- Global CLAUDE.md ---

if [ -f "$CLAUDE_DIR/CLAUDE.md" ]; then
    # Check if it's already our symlink
    if [ -L "$CLAUDE_DIR/CLAUDE.md" ]; then
        LINK_TARGET="$(readlink "$CLAUDE_DIR/CLAUDE.md")"
        if [ "$LINK_TARGET" = "$SCRIPT_DIR/global/CLAUDE.md" ]; then
            echo "[ok] CLAUDE.md already symlinked"
        else
            echo "[backup] Existing CLAUDE.md symlink points elsewhere, backing up..."
            mv "$CLAUDE_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md.backup"
            ln -s "$SCRIPT_DIR/global/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
            echo "[ok] CLAUDE.md symlinked (old link backed up)"
        fi
    else
        echo "[backup] Backing up existing CLAUDE.md to CLAUDE.md.backup"
        mv "$CLAUDE_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md.backup"
        ln -s "$SCRIPT_DIR/global/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
        echo "[ok] CLAUDE.md symlinked"
    fi
else
    ln -s "$SCRIPT_DIR/global/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
    echo "[ok] CLAUDE.md symlinked"
fi

# --- Commands ---

# Only symlink our commands — never touch existing ones
for cmd in startup.md onboard.md; do
    SOURCE="$SCRIPT_DIR/global/commands/$cmd"
    TARGET="$COMMANDS_DIR/$cmd"

    if [ -f "$TARGET" ]; then
        if [ -L "$TARGET" ]; then
            LINK_TARGET="$(readlink "$TARGET")"
            if [ "$LINK_TARGET" = "$SOURCE" ]; then
                echo "[ok] commands/$cmd already symlinked"
            else
                echo "[backup] commands/$cmd symlink points elsewhere, backing up..."
                mv "$TARGET" "$TARGET.backup"
                ln -s "$SOURCE" "$TARGET"
                echo "[ok] commands/$cmd symlinked (old link backed up)"
            fi
        else
            echo "[backup] Backing up existing commands/$cmd"
            mv "$TARGET" "$TARGET.backup"
            ln -s "$SOURCE" "$TARGET"
            echo "[ok] commands/$cmd symlinked"
        fi
    else
        ln -s "$SOURCE" "$TARGET"
        echo "[ok] commands/$cmd symlinked"
    fi
done

# --- Verify existing commands are untouched ---

echo ""
echo "Existing commands preserved:"
for cmd in "$COMMANDS_DIR"/*.md; do
    if [ -f "$cmd" ]; then
        name="$(basename "$cmd")"
        if [ -L "$cmd" ]; then
            echo "  $name -> $(readlink "$cmd")"
        else
            echo "  $name (original file)"
        fi
    fi
done

echo ""
echo "Installation complete!"
echo ""
echo "Symlinks created:"
echo "  $CLAUDE_DIR/CLAUDE.md -> $SCRIPT_DIR/global/CLAUDE.md"
echo "  $COMMANDS_DIR/startup.md -> $SCRIPT_DIR/global/commands/startup.md"
echo "  $COMMANDS_DIR/onboard.md -> $SCRIPT_DIR/global/commands/onboard.md"
echo ""
echo "Commands available: /startup, /onboard, /ready2modify, /workdone"
