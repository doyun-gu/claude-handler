#!/bin/bash
set -e

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   claude-handler installer
#   Sets up Commander, Worker, or Hybrid fleet mode
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"
FLEET_DIR="$HOME/.claude-fleet"

# Colors
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "  ${GREEN}[ok]${NC} $1"; }
warn()  { echo -e "  ${YELLOW}[!]${NC} $1"; }
err()   { echo -e "  ${RED}[error]${NC} $1"; }
ask()   { echo -en "  ${BLUE}?${NC} $1 "; }

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  claude-handler — Fleet Installer${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── Pre-flight checks ────────────────────────────

# Check OS
OS="$(uname -s)"
if [[ "$OS" != "Darwin" ]]; then
    warn "macOS is required for launchd process supervision."
    warn "On Linux, you'll need to set up systemd services manually."
    warn "The Claude Code integration (symlinks + commands) will still work."
    echo ""
fi

# Check Claude Code is installed
if [[ ! -d "$CLAUDE_DIR" ]]; then
    err "$CLAUDE_DIR does not exist. Install Claude Code first:"
    echo "    https://docs.anthropic.com/en/docs/claude-code"
    exit 1
fi

# Check for claude CLI
CLAUDE_BIN=""
if command -v claude &>/dev/null; then
    CLAUDE_BIN="$(command -v claude)"
elif [[ -x "$HOME/.local/bin/claude" ]]; then
    CLAUDE_BIN="$HOME/.local/bin/claude"
fi

if [[ -z "$CLAUDE_BIN" ]]; then
    warn "Claude CLI not found in PATH. Worker mode requires it."
    warn "Install: https://docs.anthropic.com/en/docs/claude-code"
fi

# ── Role selection ────────────────────────────────

echo -e "${BOLD}  What role should this machine play?${NC}"
echo ""
echo "  1) Commander  — Your interactive laptop. Dispatches tasks to a Worker."
echo "  2) Worker     — Autonomous machine (Mac Mini, desktop, VM). Runs tasks."
echo "  3) Hybrid     — Single machine acts as both Commander and Worker."
echo ""
ask "Choose [1/2/3] (default: 3 — hybrid):"
read -r ROLE_CHOICE
echo ""

case "${ROLE_CHOICE:-3}" in
    1) MACHINE_ROLE="commander" ;;
    2) MACHINE_ROLE="worker" ;;
    *) MACHINE_ROLE="hybrid" ;;
esac

# ── Dev directory ─────────────────────────────────

ask "Where do your projects live? (default: ~/Developer):"
read -r DEV_DIR_INPUT
DEV_DIR="${DEV_DIR_INPUT:-$HOME/Developer}"
DEV_DIR="${DEV_DIR/#\~/$HOME}"
mkdir -p "$DEV_DIR"
echo ""

# ── Worker SSH setup (Commander only) ─────────────

SSH_TARGET=""
if [[ "$MACHINE_ROLE" == "commander" ]]; then
    echo -e "${BOLD}  Worker Machine Setup${NC}"
    echo ""
    ask "SSH hostname of your Worker machine (e.g., mac-mini, 192.168.1.100):"
    read -r SSH_TARGET
    echo ""

    if [[ -n "$SSH_TARGET" ]]; then
        echo -n "  Testing SSH connection..."
        if ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_TARGET" "echo ok" &>/dev/null; then
            info "SSH to $SSH_TARGET works"
        else
            warn "SSH to $SSH_TARGET failed. Check your SSH config."
            warn "You can set SSH_TARGET in ~/.claude-fleet/machine-role.conf later."
        fi
        echo ""
    fi
fi

# ── Email notifications (optional) ───────────────

GMAIL_USER=""
GMAIL_APP_PASSWORD=""
ask "Enable email notifications for task completion? [y/N]:"
read -r EMAIL_CHOICE
echo ""

if [[ "${EMAIL_CHOICE:-n}" =~ ^[Yy] ]]; then
    echo "  Gmail App Password setup:"
    echo "  1. Go to https://myaccount.google.com/apppasswords"
    echo "  2. Generate an app password for 'Mail'"
    echo ""
    ask "Gmail address:"
    read -r GMAIL_USER
    ask "App password (16 chars, won't be echoed):"
    read -rs GMAIL_APP_PASSWORD
    echo ""
    echo ""
fi

# ── Create directories ───────────────────────────

echo -e "${BOLD}  Installing...${NC}"
echo ""

mkdir -p "$COMMANDS_DIR"
mkdir -p "$FLEET_DIR"/{tasks,logs,review-queue,secrets,reply-actions}
info "Created ~/.claude-fleet/ directories"

# ── Symlink helper ───────────────────────────────

symlink_file() {
    local SOURCE="$1"
    local TARGET="$2"
    local LABEL="$3"

    if [[ -f "$TARGET" ]]; then
        if [[ -L "$TARGET" ]]; then
            LINK_TARGET="$(readlink "$TARGET")"
            if [[ "$LINK_TARGET" == "$SOURCE" ]]; then
                return  # Already correct
            else
                mv "$TARGET" "$TARGET.backup"
            fi
        else
            mv "$TARGET" "$TARGET.backup"
        fi
    fi

    ln -s "$SOURCE" "$TARGET"
}

# ── Symlink global CLAUDE.md ─────────────────────

symlink_file "$SCRIPT_DIR/global/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md" "CLAUDE.md"
info "Symlinked global CLAUDE.md"

# ── Symlink all commands ─────────────────────────

CMD_COUNT=0
for cmd_file in "$SCRIPT_DIR"/global/commands/*.md; do
    [[ -f "$cmd_file" ]] || continue
    cmd="$(basename "$cmd_file")"
    symlink_file "$cmd_file" "$COMMANDS_DIR/$cmd" "$cmd"
    CMD_COUNT=$((CMD_COUNT + 1))
done

if [[ -d "$SCRIPT_DIR/notion/commands" ]]; then
    for cmd_file in "$SCRIPT_DIR"/notion/commands/*.md; do
        [[ -f "$cmd_file" ]] || continue
        cmd="$(basename "$cmd_file")"
        symlink_file "$cmd_file" "$COMMANDS_DIR/$cmd" "$cmd"
        CMD_COUNT=$((CMD_COUNT + 1))
    done
fi
info "Symlinked $CMD_COUNT slash commands"

# ── Write machine-role.conf ──────────────────────

cat > "$FLEET_DIR/machine-role.conf" << CONF
# Generated by install.sh — $(date '+%Y-%m-%d %H:%M')
MACHINE_ROLE=$MACHINE_ROLE
SSH_TARGET=${SSH_TARGET:-}
DEV_DIR=$DEV_DIR
WORKER_CLAUDE_BIN=${CLAUDE_BIN:-\$HOME/.local/bin/claude}
CONF
info "Wrote machine-role.conf (role: $MACHINE_ROLE)"

# ── Write projects.json (if doesn't exist) ───────

if [[ ! -f "$FLEET_DIR/projects.json" ]]; then
    echo "[]" > "$FLEET_DIR/projects.json"
    info "Created empty projects.json"
fi

# ── Write gmail.conf (if provided) ──────────────

if [[ -n "$GMAIL_USER" && -n "$GMAIL_APP_PASSWORD" ]]; then
    cat > "$FLEET_DIR/secrets/gmail.conf" << GMAIL
GMAIL_USER=$GMAIL_USER
GMAIL_APP_PASSWORD=$GMAIL_APP_PASSWORD
GMAIL_TO=$GMAIL_USER
GMAIL
    chmod 600 "$FLEET_DIR/secrets/gmail.conf"
    info "Wrote gmail.conf (credentials secured)"
fi

# ── Install launchd plist (Worker/Hybrid on macOS) ──

if [[ "$OS" == "Darwin" && "$MACHINE_ROLE" != "commander" ]]; then
    PLIST_DIR="$HOME/Library/LaunchAgents"
    PLIST_NAME="com.fleet.supervisor.plist"
    PLIST_PATH="$PLIST_DIR/$PLIST_NAME"
    mkdir -p "$PLIST_DIR"

    # Unload existing if present
    if launchctl list | grep -q "com.fleet.supervisor" 2>/dev/null; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
    fi

    # Generate plist from template
    sed -e "s|__HANDLER_DIR__|$SCRIPT_DIR|g" \
        -e "s|__HOME__|$HOME|g" \
        "$SCRIPT_DIR/templates/com.fleet.supervisor.plist.template" \
        > "$PLIST_PATH"

    # Load it
    launchctl load "$PLIST_PATH" 2>/dev/null && \
        info "Installed and loaded launchd supervisor" || \
        warn "launchctl load failed — you may need to load it manually"
fi

# ── Make scripts executable ──────────────────────

chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true
info "Made scripts executable"

# ── Verification ─────────────────────────────────

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Installation complete!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Role:     $MACHINE_ROLE"
echo "  Dev dir:  $DEV_DIR"
[[ -n "$SSH_TARGET" ]] && echo "  Worker:   $SSH_TARGET"
[[ -n "$GMAIL_USER" ]] && echo "  Email:    $GMAIL_USER"
echo ""
echo "  Installed commands:"
for cmd in "$COMMANDS_DIR"/*.md; do
    [[ -f "$cmd" ]] || continue
    name="$(basename "$cmd" .md)"
    echo "    /$name"
done
echo ""

if [[ "$MACHINE_ROLE" == "commander" || "$MACHINE_ROLE" == "hybrid" ]]; then
    echo "  Next steps:"
    echo "    1. Open Claude Code in any project directory"
    echo "    2. Run /cofounder to personalise your experience"
    echo "    3. Run /dispatch to send a task to the Worker"
    echo ""
fi

if [[ "$MACHINE_ROLE" == "worker" || "$MACHINE_ROLE" == "hybrid" ]]; then
    echo "  Worker daemon:"
    if tmux has-session -t worker-daemon 2>/dev/null; then
        info "worker-daemon tmux session is running"
    else
        echo "    Start with: tmux new-session -d -s worker-daemon '$SCRIPT_DIR/worker-daemon.sh'"
    fi
    echo ""
fi

echo "  Add projects with: /dispatch or edit ~/.claude-fleet/projects.json"
echo "  Restart Claude Code for changes to take effect."
echo ""
