# Dell XPS 15 — Worker Setup Guide

Set up the Dell XPS 15 (i7, 32GB) as a second fleet worker alongside the Mac Mini.

## Architecture

```
MacBook Pro (Commander)
    |
    └── SSH ──> Mac Mini (Controller + Worker 1)
                ├── Fleet DB (SQLite, single source of truth)
                ├── Task queue, review queue, logs
                ├── Runs DPSpice frontend/UI tasks locally
                └── SSH ──> Dell XPS (Worker 2)
                            ├── WSL2 Ubuntu 24.04
                            ├── Runs engine/backend/heavy tasks
                            └── Reports results back to Mac Mini
```

MacBook never talks to Dell directly. Mac Mini is the controller.

## Step 1: Windows Setup (5 min)

### Power Settings
Settings > System > Power > Screen and sleep:
- When plugged in, turn off screen: **Never** (or 30 min)
- When plugged in, put device to sleep: **Never**

### Install Windows Terminal (if not pre-installed)
Microsoft Store > search "Windows Terminal" > Install.

### Install WSL2
Open PowerShell as Administrator:
```powershell
wsl --install -d Ubuntu-24.04
```
Restart when prompted. Set username and password on first launch.

## Step 2: WSL2 Configuration (5 min)

### Windows side — create C:\Users\<username>\.wslconfig
```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
firewall=true
memory=24GB
processors=8
swap=8GB
```

This gives WSL2 24GB of the 32GB RAM, mirrored networking (no NAT headaches).

### Allow inbound connections (PowerShell admin)
```powershell
Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow
```

### Apply changes
```powershell
wsl --shutdown
wsl
```

### Linux side — edit /etc/wsl.conf
```ini
[boot]
systemd=true

[network]
hostname=dell-xps

[automount]
enabled=true
options="metadata"
```

Then restart WSL: exit, run `wsl --shutdown` from PowerShell, then `wsl` again.

## Step 3: Auto-Start WSL on Boot (5 min)

WSL2 doesn't auto-start after Windows reboots. Fix with Task Scheduler:

1. Open Task Scheduler (search in Start menu)
2. Create Task (not Basic Task)
3. General tab:
   - Name: "WSL2 Auto-Start"
   - Run whether user is logged in or not
   - Run with highest privileges
4. Triggers tab: Add > At startup
5. Actions tab: Add > Start a program
   - Program: `C:\Windows\System32\wsl.exe`
   - Arguments: `-u root -- bash -c "service ssh start && sleep infinity"`
6. Conditions: Uncheck "Start only if on AC power"
7. Settings: Check "Run task as soon as possible after a scheduled start is missed"

## Step 4: Install Dev Tools in Ubuntu (10 min)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Essential tools
sudo apt install -y \
  git curl wget unzip build-essential \
  python3 python3-pip python3-venv \
  nodejs npm \
  openssh-server \
  tmux htop jq

# Install Claude Code
curl -fsSL https://claude.ai/install.sh | sh

# Install GitHub CLI
(type -p wget >/dev/null || sudo apt-get install wget -y) \
  && sudo mkdir -p -m 755 /etc/apt/keyrings \
  && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
  && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
  && sudo apt update \
  && sudo apt install gh -y

# Authenticate GitHub
gh auth login

# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Disable IPv6 (required for Tailscale in WSL2)
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1
echo "net.ipv6.conf.all.disable_ipv6=1" | sudo tee -a /etc/sysctl.conf

# Start Tailscale (use pre-auth key from admin console)
sudo tailscaled &
sudo tailscale up --authkey=tskey-auth-XXXXX --hostname=dell-xps
```

## Step 5: SSH Setup (5 min)

```bash
# Enable SSH server
sudo systemctl enable ssh
sudo systemctl start ssh

# Generate SSH key for this machine
ssh-keygen -t ed25519 -C "dell-xps-worker"

# Add to GitHub
gh ssh-key add ~/.ssh/id_ed25519.pub --title "dell-xps-worker"

# Create fleet directories
mkdir -p ~/.claude-fleet/{tasks,logs,review-queue,task-status}
```

### On Mac Mini — add Dell as SSH target
```bash
# Add to ~/.ssh/config
cat >> ~/.ssh/config << 'EOF'

Host dell-xps
    HostName dell-xps  # Tailscale hostname
    User <your-username>
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking no
EOF

# Test connection
ssh dell-xps "echo 'Dell connected'"
```

## Step 6: Clone Projects (5 min)

```bash
# On Dell WSL2
mkdir -p ~/Developer
cd ~/Developer

# Clone all projects (same structure as Mac Mini)
git clone git@github.com:doyun-gu/DPSpice-com.git dynamic-phasors/DPSpice-com
git clone git@github.com:doyun-gu/claude-handler.git
git clone git@github.com:doyun-gu/knoxur.git
git clone git@github.com:doyun-gu/my-world.git

# Set up DPSpice Python env
cd ~/Developer/dynamic-phasors/DPSpice-com
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Step 7: Fleet Configuration (5 min)

```bash
# Create machine role config
cat > ~/.claude-fleet/machine-role.conf << 'EOF'
MACHINE_ROLE=worker
MACHINE_NAME=dell-xps
SSH_TARGET=mac-mini
CLAUDE_BIN=$HOME/.local/bin/claude
EOF
```

Note: The Dell does NOT run its own daemon. Mac Mini's daemon SSH's into Dell to start tasks.

## Step 8: Windows Terminal Theming

Open Windows Terminal > Settings (Ctrl+,) > Open JSON file. Add to "schemes":
```json
{
    "name": "Everforest Dark",
    "background": "#2D353B",
    "foreground": "#D3C6AA",
    "black": "#475258",
    "red": "#E67E80",
    "green": "#A7C080",
    "yellow": "#DBBC7F",
    "blue": "#7FBBB3",
    "purple": "#D699B6",
    "cyan": "#83C092",
    "white": "#D3C6AA",
    "brightBlack": "#475258",
    "brightRed": "#E67E80",
    "brightGreen": "#A7C080",
    "brightYellow": "#DBBC7F",
    "brightBlue": "#7FBBB3",
    "brightPurple": "#D699B6",
    "brightCyan": "#83C092",
    "brightWhite": "#D3C6AA",
    "cursorColor": "#D3C6AA",
    "selectionBackground": "#475258"
}
```

Set Ubuntu profile defaults:
```json
{
    "name": "Ubuntu-24.04",
    "colorScheme": "Everforest Dark",
    "font": { "face": "JetBrains Mono", "size": 11 },
    "opacity": 95,
    "useAcrylic": false
}
```

Download JetBrains Mono from https://www.jetbrains.com/lp/mono/ and install on Windows.

## Step 9: Verify Everything

```bash
# On Dell WSL2
claude --version          # Should show 2.x.x
gh auth status            # Should be authenticated
git clone --dry-run git@github.com:doyun-gu/DPSpice-com.git /dev/null  # SSH works
tailscale status          # Should show connected

# From Mac Mini
ssh dell-xps "claude --version"     # Should work via Tailscale
ssh dell-xps "python3 --version"    # Python available
ssh dell-xps "cd ~/Developer/dynamic-phasors/DPSpice-com && git status"
```

## Task Routing Strategy

Mac Mini daemon decides where to run each task:

| Task Type | Machine | Reason |
|-----------|---------|--------|
| Python engine (solvers, models, validation) | Dell XPS | CPU-heavy, 32GB RAM |
| Frontend/UI (React, Next.js, CSS) | Mac Mini | node/npm already set up, serves :3002 |
| Docs, architecture, design | Either | Light work |
| Tests (pytest, jest) | Dell XPS | Parallelizable, CPU-bound |
| API (FastAPI) | Mac Mini | Needs to serve locally |

## Maintenance

- **Dell goes offline**: Mac Mini keeps working, Dell tasks re-queue
- **Updates**: `ssh dell-xps "cd ~/Developer/claude-handler && git pull"`
- **Logs**: `ssh dell-xps "tail -50 ~/.claude-fleet/logs/worker-daemon.log"`
- **Diagnostics**: `ssh dell-xps "python3 ~/Developer/claude-handler/fleet-diagnose.py"`

## Research-Based Best Practices Applied

1. **Mirrored networking** — eliminates NAT issues between WSL2 and LAN
2. **Tailscale mesh** — persistent connectivity without port forwarding
3. **Systemd enabled** — SSH and services auto-start
4. **Task Scheduler auto-start** — WSL2 survives Windows reboots
5. **Linux filesystem only** — all repos under /home/, never /mnt/c/ (10x faster)
6. **Single controller** — Mac Mini owns the queue, Dell is compute-only
7. **Git worktree isolation** — each task gets its own branch, no conflicts
