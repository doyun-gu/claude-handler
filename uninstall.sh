#!/bin/bash
set -e

CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"
FLEET_DIR="$HOME/.claude-fleet"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "  ${GREEN}[ok]${NC} $1"; }
warn()  { echo -e "  ${YELLOW}[!]${NC} $1"; }
ask()   { echo -en "  ${BLUE}?${NC} $1 "; }

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  claude-handler — Uninstaller${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── Helper: remove symlink if it points to our repo ──

remove_symlink() {
    local TARGET="$1"
    local EXPECTED_SOURCE="$2"
    local LABEL="$3"

    if [[ -L "$TARGET" ]]; then
        LINK_TARGET="$(readlink "$TARGET")"
        if [[ "$LINK_TARGET" == "$EXPECTED_SOURCE" ]]; then
            rm "$TARGET"
            # Restore backup if exists
            if [[ -f "$TARGET.backup" ]]; then
                mv "$TARGET.backup" "$TARGET"
                info "Restored $LABEL from backup"
            else
                info "Removed $LABEL"
            fi
        else
            warn "$LABEL points elsewhere, skipping"
        fi
    elif [[ -f "$TARGET" ]]; then
        warn "$LABEL is not a symlink, skipping"
    fi
}

# ── Step 1: Unload launchd plist ─────────────────

PLIST_PATH="$HOME/Library/LaunchAgents/com.fleet.supervisor.plist"
if [[ -f "$PLIST_PATH" ]]; then
    echo "  Stopping launchd supervisor..."
    launchctl unload "$PLIST_PATH" 2>/dev/null && info "Unloaded launchd supervisor" || warn "launchctl unload failed"
    rm -f "$PLIST_PATH"
    info "Removed $PLIST_PATH"
else
    info "No launchd plist found (skipping)"
fi
echo ""

# ── Step 2: Kill fleet tmux sessions ─────────────

echo "  Stopping fleet services..."
for session in worker-daemon fleet-dashboard fleet-dashboard-web; do
    if tmux has-session -t "$session" 2>/dev/null; then
        tmux kill-session -t "$session" 2>/dev/null
        info "Killed tmux session: $session"
    fi
done
echo ""

# ── Step 3: Remove symlinks ──────────────────────

echo "  Removing symlinks..."
remove_symlink "$CLAUDE_DIR/CLAUDE.md" "$SCRIPT_DIR/global/CLAUDE.md" "CLAUDE.md"

for cmd_file in "$SCRIPT_DIR"/global/commands/*.md; do
    [[ -f "$cmd_file" ]] || continue
    cmd="$(basename "$cmd_file")"
    remove_symlink "$COMMANDS_DIR/$cmd" "$cmd_file" "commands/$cmd"
done

if [[ -d "$SCRIPT_DIR/notion/commands" ]]; then
    for cmd_file in "$SCRIPT_DIR"/notion/commands/*.md; do
        [[ -f "$cmd_file" ]] || continue
        cmd="$(basename "$cmd_file")"
        remove_symlink "$COMMANDS_DIR/$cmd" "$cmd_file" "commands/$cmd"
    done
fi
echo ""

# ── Step 4: Optionally remove ~/.claude-fleet/ ───

if [[ -d "$FLEET_DIR" ]]; then
    ask "Remove ~/.claude-fleet/ directory? This deletes task history and logs. [y/N]:"
    read -r REMOVE_FLEET
    if [[ "${REMOVE_FLEET:-n}" =~ ^[Yy] ]]; then
        rm -rf "$FLEET_DIR"
        info "Removed ~/.claude-fleet/"
    else
        info "Kept ~/.claude-fleet/ (task history preserved)"
    fi
    echo ""
fi

# ── Done ─────────────────────────────────────────

echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Uninstall complete.${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Restart Claude Code for changes to take effect."
echo "  To reinstall: ./install.sh"
echo ""
