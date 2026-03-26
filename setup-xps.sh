#!/bin/bash
# setup-xps.sh — One-shot setup for Dell XPS Worker (WSL2 Ubuntu)
#
# Prerequisites (you must do these manually first):
#   1. WSL2 Ubuntu installed (wsl --install -d Ubuntu-24.04)
#   2. Claude Code installed (curl -fsSL https://claude.ai/install.sh | sh)
#   3. GitHub CLI installed and authenticated (gh auth login)
#   4. Tailscale installed and connected (sudo tailscale up)
#   5. SSH key generated and added to GitHub (ssh-keygen + gh ssh-key add)
#
# Usage:
#   git clone git@github.com:<your-github-user>/claude-handler.git ~/Developer/claude-handler
#   cd ~/Developer/claude-handler
#   ./setup-xps.sh
#
# What this script does:
#   - Installs system packages (jq, tmux, htop, build-essential, python3-venv)
#   - Creates fleet directories
#   - Creates machine-role.conf (worker)
#   - Clones all project repos
#   - Sets up Python venv for DPSpice
#   - Installs claude-handler (symlinks commands, skills, CLAUDE.md)
#   - Copies memory from this repo
#   - Configures WSL settings (/etc/wsl.conf)
#   - Creates .wslconfig template on Windows side
#   - Verifies everything works

set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[ok]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; }
info() { echo -e "${BLUE}[info]${NC} $1"; }

# ─── Pre-checks ──────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Dell XPS Worker Setup"
echo "  claude-handler fleet system"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FAIL=0

# ─── Configuration (edit these before running) ──────────────────────────────
GITHUB_USER="${GITHUB_USER:-$(gh api user --jq '.login' 2>/dev/null || echo 'your-github-user')}"
GIT_NAME="${GIT_NAME:-$(git config --global user.name 2>/dev/null || echo '')}"
GIT_EMAIL="${GIT_EMAIL:-$(git config --global user.email 2>/dev/null || echo '')}"
CONTROLLER_HOST="${CONTROLLER_HOST:-mac-mini}"
MACHINE_HOSTNAME="${MACHINE_HOSTNAME:-dell-xps}"

# Check Claude Code
if command -v claude &>/dev/null; then
    ok "Claude Code: $(claude --version 2>/dev/null || echo 'installed')"
else
    err "Claude Code not found. Install: curl -fsSL https://claude.ai/install.sh | sh"
    FAIL=1
fi

# Check GitHub CLI
if command -v gh &>/dev/null; then
    if gh auth status &>/dev/null 2>&1; then
        ok "GitHub CLI: authenticated"
    else
        err "GitHub CLI installed but not authenticated. Run: gh auth login"
        FAIL=1
    fi
else
    err "GitHub CLI not found. Install first, then run: gh auth login"
    FAIL=1
fi

# Check SSH to GitHub
if ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    ok "SSH to GitHub: working"
else
    warn "SSH to GitHub: may not work. Ensure ssh key is added (gh ssh-key add ~/.ssh/id_ed25519.pub)"
fi

# Check Tailscale
if command -v tailscale &>/dev/null; then
    if tailscale status &>/dev/null 2>&1; then
        ok "Tailscale: connected"
    else
        warn "Tailscale installed but not connected. Run: sudo tailscale up"
    fi
else
    warn "Tailscale not found. Install: curl -fsSL https://tailscale.com/install.sh | sh"
    warn "Then run: sudo tailscale up --hostname=dell-xps"
fi

if [[ $FAIL -eq 1 ]]; then
    echo ""
    err "Fix the errors above before continuing."
    exit 1
fi

echo ""
info "Pre-checks passed. Starting setup..."
echo ""

# ─── Step 1: System packages ─────────────────────────────────────────────────

info "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    jq tmux htop \
    build-essential \
    python3 python3-pip python3-venv \
    curl wget unzip \
    2>/dev/null
ok "System packages installed"

# ─── Step 2: Fleet directories ───────────────────────────────────────────────

info "Creating fleet directories..."
mkdir -p ~/.claude-fleet/{tasks,logs,review-queue,task-status,eval,dispatch-log}
mkdir -p ~/.claude/{commands,skills,projects}
ok "Fleet directories created"

# ─── Step 3: Machine role config ─────────────────────────────────────────────

info "Writing machine-role.conf..."
cat > ~/.claude-fleet/machine-role.conf << EOF
MACHINE_ROLE=worker
MACHINE_NAME=$MACHINE_HOSTNAME
CONTROLLER=$CONTROLLER_HOST
CLAUDE_BIN=$HOME/.local/bin/claude
WORKER_CLAUDE_BIN=$HOME/.local/bin/claude
EOF
ok "Machine role: worker (controller: $CONTROLLER_HOST)"

# ─── Step 4: Clone project repos ─────────────────────────────────────────────

info "Cloning project repos..."
mkdir -p ~/Developer/dynamic-phasors

clone_if_missing() {
    local repo="$1"
    local dest="$2"
    local name="$3"
    if [[ -d "$dest/.git" ]]; then
        ok "  $name: already cloned"
        (cd "$dest" && git fetch origin -q && git pull --ff-only origin main -q 2>/dev/null) || true
    else
        info "  Cloning $name..."
        git clone -q "$repo" "$dest" 2>/dev/null && ok "  $name: cloned" || warn "  $name: clone failed"
    fi
}

# Core repos (needed for fleet)
clone_if_missing "git@github.com:$GITHUB_USER/DPSpice-com.git" \
    "$HOME/Developer/dynamic-phasors/DPSpice-com" "DPSpice-com"

clone_if_missing "git@github.com:$GITHUB_USER/claude-handler.git" \
    "$HOME/Developer/claude-handler" "claude-handler"

clone_if_missing "git@github.com:$GITHUB_USER/my-world.git" \
    "$HOME/Developer/my-world" "my-world"

# Secondary repos
clone_if_missing "git@github.com:$GITHUB_USER/faradaysim.git" \
    "$HOME/Developer/faradaysim" "faradaysim"

clone_if_missing "https://github.com/$GITHUB_USER/knoxur.git" \
    "$HOME/Developer/knoxur" "knoxur"

clone_if_missing "git@github.com:$GITHUB_USER/doyungu-com.git" \
    "$HOME/Developer/doyungu-com" "doyungu-com"

clone_if_missing "git@github.com:$GITHUB_USER/phixty-com.git" \
    "$HOME/Developer/phixty-com" "phixty-com"

clone_if_missing "git@github.com:$GITHUB_USER/study-with-claude.git" \
    "$HOME/Developer/study-with-claude" "study-with-claude"

clone_if_missing "git@github.com:$GITHUB_USER/project-JULY.git" \
    "$HOME/Developer/project-JULY" "project-JULY"

echo ""

# ─── Step 5: DPSpice Python environment ──────────────────────────────────────

DPSPICE_DIR="$HOME/Developer/dynamic-phasors/DPSpice-com"
if [[ -d "$DPSPICE_DIR" ]]; then
    info "Setting up DPSpice Python environment..."
    if [[ ! -d "$DPSPICE_DIR/.venv" ]]; then
        python3 -m venv "$DPSPICE_DIR/.venv"
        ok "Created .venv"
    fi
    if [[ -f "$DPSPICE_DIR/requirements.txt" ]]; then
        "$DPSPICE_DIR/.venv/bin/pip" install -q -r "$DPSPICE_DIR/requirements.txt" 2>/dev/null && \
            ok "Python dependencies installed" || \
            warn "Some Python dependencies failed to install"
    fi
fi

# ─── Step 6: Install claude-handler (symlinks) ───────────────────────────────

info "Installing claude-handler symlinks..."
HANDLER_DIR="$HOME/Developer/claude-handler"

# Global CLAUDE.md
if [[ -f "$HANDLER_DIR/global/CLAUDE.md" ]]; then
    ln -sf "$HANDLER_DIR/global/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
    ok "Global CLAUDE.md symlinked"
fi

# Commands
if [[ -d "$HANDLER_DIR/global/commands" ]]; then
    for cmd in "$HANDLER_DIR/global/commands"/*.md; do
        name=$(basename "$cmd")
        ln -sf "$cmd" "$HOME/.claude/commands/$name"
    done
    ok "Commands symlinked ($(ls "$HANDLER_DIR/global/commands"/*.md 2>/dev/null | wc -l) files)"
fi

# Notion commands
if [[ -d "$HANDLER_DIR/notion/commands" ]]; then
    for cmd in "$HANDLER_DIR/notion/commands"/*.md; do
        name=$(basename "$cmd")
        ln -sf "$cmd" "$HOME/.claude/commands/$name"
    done
    ok "Notion commands symlinked"
fi

# Skills (gstack) -- copy instead of symlink (gstack has node_modules)
if [[ -d "$HOME/.claude/skills/gstack" ]]; then
    ok "gstack skills already installed"
else
    warn "gstack skills not found. Install manually: cd ~/.claude/skills && git clone <gstack-repo>"
fi

# ─── Step 7: Copy memory ─────────────────────────────────────────────────────

info "Setting up memory..."
MEMORY_DIR="$HOME/.claude/projects/-Users-$(whoami)/memory"
mkdir -p "$MEMORY_DIR"

# Copy from controller if accessible, otherwise create minimal
if [[ -f "$MEMORY_DIR/MEMORY.md" ]]; then
    ok "Memory already exists"
else
    warn "No memory found. Sync from controller: rsync -az $CONTROLLER_HOST:~/.claude/projects/-Users-\$(whoami)/memory/ $MEMORY_DIR/"
fi

# ─── Step 8: WSL configuration ───────────────────────────────────────────────

info "Checking WSL configuration..."

# /etc/wsl.conf
if grep -q "$MACHINE_HOSTNAME" /etc/wsl.conf 2>/dev/null; then
    ok "/etc/wsl.conf already configured"
else
    info "Writing /etc/wsl.conf (requires sudo)..."
    sudo tee /etc/wsl.conf > /dev/null << 'EOF'
[boot]
systemd=true

[network]
hostname=$MACHINE_HOSTNAME

[automount]
enabled=true
options="metadata"
EOF
    ok "/etc/wsl.conf written"
    warn "Run 'wsl --shutdown' from PowerShell and restart WSL for hostname change"
fi

# Generate .wslconfig for Windows side
WSLCONFIG_PATH="/mnt/c/Users"
WIN_USER=""
# Try to detect Windows username
for d in "$WSLCONFIG_PATH"/*/; do
    if [[ -d "$d/AppData" ]]; then
        WIN_USER=$(basename "$d")
        break
    fi
done

if [[ -n "$WIN_USER" ]]; then
    WSLCONFIG="/mnt/c/Users/$WIN_USER/.wslconfig"
    if [[ -f "$WSLCONFIG" ]]; then
        ok ".wslconfig already exists at $WSLCONFIG"
    else
        info "Writing .wslconfig for Windows..."
        cat > "$WSLCONFIG" << 'EOF'
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
firewall=true
memory=24GB
processors=8
swap=8GB
EOF
        ok ".wslconfig written at $WSLCONFIG"
        warn "Run 'wsl --shutdown' from PowerShell for this to take effect"
    fi
else
    warn "Could not detect Windows username. Create .wslconfig manually."
fi

# ─── Step 9: Git config ──────────────────────────────────────────────────────

info "Checking git config..."
if git config --global user.name &>/dev/null; then
    ok "Git user: $(git config --global user.name)"
else
    if [[ -n "$GIT_NAME" && -n "$GIT_EMAIL" ]]; then
        git config --global user.name "$GIT_NAME"
        git config --global user.email "$GIT_EMAIL"
        ok "Git user configured: $GIT_NAME <$GIT_EMAIL>"
    else
        warn "Git user not configured. Run: git config --global user.name 'Your Name' && git config --global user.email 'your@email.com'"
    fi
fi

# ─── Step 10: Projects registry ──────────────────────────────────────────────

info "Writing projects.json..."
cat > ~/.claude-fleet/projects.json << JSONEOF
{
  "projects": [
    {
      "name": "DPSpice-com",
      "path": "$HOME/Developer/dynamic-phasors/DPSpice-com",
      "repo": "git@github.com:$GITHUB_USER/DPSpice-com.git",
      "primary": true
    },
    {
      "name": "faradaysim",
      "path": "$HOME/Developer/faradaysim",
      "repo": "git@github.com:$GITHUB_USER/faradaysim.git",
      "primary": false
    },
    {
      "name": "claude-handler",
      "path": "$HOME/Developer/claude-handler",
      "repo": "git@github.com:$GITHUB_USER/claude-handler.git",
      "primary": false
    },
    {
      "name": "knoxur",
      "path": "$HOME/Developer/knoxur",
      "repo": "https://github.com/$GITHUB_USER/knoxur.git",
      "primary": false
    },
    {
      "name": "my-world",
      "path": "$HOME/Developer/my-world",
      "repo": "git@github.com:$GITHUB_USER/my-world.git",
      "primary": false
    },
    {
      "name": "doyungu-com",
      "path": "$HOME/Developer/doyungu-com",
      "repo": "git@github.com:$GITHUB_USER/doyungu-com.git",
      "primary": false
    },
    {
      "name": "phixty-com",
      "path": "$HOME/Developer/phixty-com",
      "repo": "git@github.com:$GITHUB_USER/phixty-com.git",
      "primary": false
    },
    {
      "name": "study-with-claude",
      "path": "$HOME/Developer/study-with-claude",
      "repo": "git@github.com:$GITHUB_USER/study-with-claude.git",
      "primary": false
    },
    {
      "name": "project-JULY",
      "path": "$HOME/Developer/project-JULY",
      "repo": "git@github.com:$GITHUB_USER/project-JULY.git",
      "primary": false
    }
  ]
}
JSONEOF
ok "Projects registry written"

# ─── Step 11: Initialize task DB ─────────────────────────────────────────────

info "Initializing task database..."
python3 "$HANDLER_DIR/task-db.py" init 2>/dev/null && ok "tasks.db initialized" || warn "task-db.py init failed"

# ─── Step 12: SSH server (for Mac Mini to connect) ───────────────────────────

info "Checking SSH server..."
if systemctl is-active --quiet ssh 2>/dev/null; then
    ok "SSH server running"
else
    sudo systemctl enable ssh 2>/dev/null
    sudo systemctl start ssh 2>/dev/null
    ok "SSH server started and enabled"
fi

# ─── Verification ─────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

PASS=0
TOTAL=0

check() {
    TOTAL=$((TOTAL + 1))
    if eval "$1" &>/dev/null 2>&1; then
        ok "$2"
        PASS=$((PASS + 1))
    else
        err "$2"
    fi
}

check "command -v claude"                         "Claude Code installed"
check "gh auth status"                            "GitHub CLI authenticated"
check "test -f ~/.claude-fleet/machine-role.conf" "Machine role configured"
check "test -f ~/.claude-fleet/projects.json"     "Projects registry exists"
check "test -f ~/.claude-fleet/tasks.db"          "Task database initialized"
check "test -d ~/Developer/dynamic-phasors/DPSpice-com/.git" "DPSpice-com cloned"
check "test -d ~/Developer/claude-handler/.git"   "claude-handler cloned"
check "test -f ~/.claude/CLAUDE.md"               "Global CLAUDE.md symlinked"
check "test -d ~/.claude/commands"                "Commands directory exists"
check "test -f /etc/wsl.conf"                     "WSL configuration exists"
check "systemctl is-active --quiet ssh"           "SSH server running"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Result: ${GREEN}${PASS}/${TOTAL}${NC} checks passed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [[ $PASS -eq $TOTAL ]]; then
    ok "Setup complete."
else
    warn "Some checks failed. Review the output above."
fi

echo ""
echo "Next steps:"
echo "  1. From PowerShell: wsl --shutdown  (apply WSL config changes)"
echo "  2. Restart WSL"
echo "  3. From controller: add $MACHINE_HOSTNAME to ~/.ssh/config:"
echo ""
echo "     Host $MACHINE_HOSTNAME"
echo "         HostName $MACHINE_HOSTNAME"
echo "         User $(whoami)"
echo "         IdentityFile ~/.ssh/id_ed25519"
echo ""
echo "  4. From controller: ssh $MACHINE_HOSTNAME 'echo connected'"
echo "  5. From controller: sync memory:"
echo "     rsync -az ~/.claude/projects/-Users-\$(whoami)/memory/ $MACHINE_HOSTNAME:$MEMORY_DIR/"
echo "  6. Test dispatch: /dispatch @DPSpice-com route:$MACHINE_HOSTNAME <task>"
echo ""
