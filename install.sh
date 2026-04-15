#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"
FLEET_DIR="$HOME/.claude-fleet"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  claude-handler installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Pre-checks ──────────────────────────────────────

if [ ! -d "$CLAUDE_DIR" ]; then
    echo "Error: $CLAUDE_DIR does not exist. Is Claude Code installed?"
    echo "  Install: https://docs.anthropic.com/en/docs/claude-code"
    exit 1
fi

# ── Helper: symlink with backup ─────────────────────

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

# ── Global CLAUDE.md ────────────────────────────────

echo "Global instructions:"
symlink_file "$SCRIPT_DIR/global/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md" "CLAUDE.md"
echo ""

# ── Core commands ───────────────────────────────────

mkdir -p "$COMMANDS_DIR"

echo "Core commands:"
for cmd_file in "$SCRIPT_DIR"/global/commands/*.md; do
    cmd="$(basename "$cmd_file")"
    symlink_file "$cmd_file" "$COMMANDS_DIR/$cmd" "commands/$cmd"
done
echo ""

# ── Role personas ──────────────────────────────────

ROLES_DIR="$CLAUDE_DIR/roles"

if [ -d "$SCRIPT_DIR/global/roles" ]; then
    echo "Role personas:"
    mkdir -p "$ROLES_DIR"
    for role_file in "$SCRIPT_DIR"/global/roles/*.md; do
        role="$(basename "$role_file")"
        symlink_file "$role_file" "$ROLES_DIR/$role" "roles/$role"
    done
    echo ""
fi

# ── Rules ──────────────────────────────────────────

RULES_DIR="$CLAUDE_DIR/rules"

if [ -d "$SCRIPT_DIR/global/rules" ]; then
    echo "Rules:"
    mkdir -p "$RULES_DIR"
    for rule_file in "$SCRIPT_DIR"/global/rules/*.md; do
        rule="$(basename "$rule_file")"
        symlink_file "$rule_file" "$RULES_DIR/$rule" "rules/$rule"
    done
    echo ""
fi

# ── Notion commands (optional) ──────────────────────

if [ -d "$SCRIPT_DIR/notion/commands" ]; then
    echo "Notion commands:"
    for cmd_file in "$SCRIPT_DIR"/notion/commands/*.md; do
        cmd="$(basename "$cmd_file")"
        symlink_file "$cmd_file" "$COMMANDS_DIR/$cmd" "commands/$cmd"
    done
    echo ""
fi

# ── Fleet directory structure ───────────────────────

echo "Fleet directories:"
mkdir -p "$FLEET_DIR/tasks" \
         "$FLEET_DIR/logs" \
         "$FLEET_DIR/review-queue" \
         "$FLEET_DIR/archive" \
         "$FLEET_DIR/secrets" \
         "$FLEET_DIR/reply-actions" \
         "$FLEET_DIR/bug-knowledge"
echo "  [ok] ~/.claude-fleet/ structure created"
echo ""

# ── Copy example configs if missing ─────────────────

if [ ! -f "$FLEET_DIR/projects.json" ] && [ -f "$SCRIPT_DIR/config.example/projects.json.example" ]; then
    cp "$SCRIPT_DIR/config.example/projects.json.example" "$FLEET_DIR/projects.json"
    echo "  [new] ~/.claude-fleet/projects.json (from example — edit with your projects)"
fi

if [ ! -f "$FLEET_DIR/secrets/gmail.conf" ] && [ -f "$SCRIPT_DIR/config.example/gmail.conf.example" ]; then
    cp "$SCRIPT_DIR/config.example/gmail.conf.example" "$FLEET_DIR/secrets/gmail.conf"
    echo "  [new] ~/.claude-fleet/secrets/gmail.conf (edit with your credentials)"
fi
echo ""

# ── Machine role selection ──────────────────────────

if [ -f "$FLEET_DIR/machine-role.conf" ]; then
    CURRENT_ROLE=$(grep "^MACHINE_ROLE=" "$FLEET_DIR/machine-role.conf" 2>/dev/null | cut -d= -f2)
    echo "Machine role: $CURRENT_ROLE (already configured)"
    echo ""
    ROLE="$CURRENT_ROLE"
else
    echo "What role should this machine have?"
    echo ""
    echo "  1) Commander — Interactive machine (laptop/desktop)."
    echo "     You talk to Claude, plan, dispatch tasks, review PRs."
    echo ""
    echo "  2) Worker — Autonomous machine (server/desktop)."
    echo "     Runs a daemon that picks up tasks and executes them."
    echo "     Opens PRs for review. Never pushes to main."
    echo ""
    printf "Choose [1/2] (default: 1): "
    read -r ROLE_CHOICE

    case "$ROLE_CHOICE" in
        2) ROLE="worker" ;;
        *) ROLE="commander" ;;
    esac

    echo "MACHINE_ROLE=$ROLE" > "$FLEET_DIR/machine-role.conf"
    echo "  [ok] Machine role set to: $ROLE"
    echo ""
fi

# ── Role-specific setup ────────────────────────────

if [ "$ROLE" = "worker" ]; then
    echo "Worker setup:"

    # Make fleet scripts executable
    chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

    # Install launchd plist
    if [ -f "$SCRIPT_DIR/install-launchd.sh" ]; then
        printf "  Install LaunchAgent for auto-start on boot? [Y/n]: "
        read -r INSTALL_LAUNCHD
        case "$INSTALL_LAUNCHD" in
            [nN]*) echo "  Skipped LaunchAgent install." ;;
            *)
                "$SCRIPT_DIR/install-launchd.sh"
                echo "  [ok] LaunchAgent installed"
                ;;
        esac
    fi

    echo ""
    echo "  Worker is ready. Start the daemon manually with:"
    echo "    tmux new-session -d -s worker-daemon '$SCRIPT_DIR/worker-daemon.sh'"
    echo ""
    echo "  Or reboot — the LaunchAgent will start it automatically."

elif [ "$ROLE" = "commander" ]; then
    echo "Commander setup:"

    # Check if user has a Worker machine
    printf "  Do you have a server/desktop to use as a Worker? [y/N]: "
    read -r HAS_WORKER

    case "$HAS_WORKER" in
        [yY]*)
            echo ""
            echo "  To set up the Worker:"
            echo "  1. Clone this repo on the Worker machine"
            echo "  2. Run ./install.sh and choose 'Worker'"
            echo "  3. Set up SSH access from this machine:"
            echo ""
            echo "     # Add to ~/.ssh/config:"
            echo "     Host worker"
            echo "       HostName <worker-ip-or-hostname>"
            echo "       User <username>"
            echo ""
            echo "     # Test: ssh worker 'echo connected'"
            echo ""
            echo "  After setup, use /dispatch to send tasks."
            ;;
        *)
            echo "  No Worker configured. You can add one later."
            echo "  Claude Code works standalone with all commands."
            ;;
    esac
fi

echo ""

# ── Summary ─────────────────────────────────────────

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
echo "Machine role: $ROLE"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code for changes to take effect"
echo "  2. Run /cofounder to personalise Claude for your workflow"
if [ "$ROLE" = "worker" ]; then
    echo "  3. Edit ~/.claude-fleet/projects.json with your projects"
    echo "  4. Edit ~/.claude-fleet/secrets/gmail.conf for notifications"
fi
echo ""
