# claude-handler

A reusable framework that turns Claude Code into a Technical Co-Founder. Installs globally via symlinks so it activates automatically for every project.

## What It Does

- **Technical Co-Founder persona** — Claude pushes back on bad ideas, thinks product-first, and ships incrementally
- **Smart onboarding** — auto-detects existing projects (tech stack, git history, file structure) and only asks what it can't figure out
- **Personalisation** — `/cofounder` runs an adaptive interview and saves your profile to `~/.claude/user-profile.md` (never committed to the repo)
- **Project CLAUDE.md generation** — creates per-project context files so future sessions start instantly
- **Notion integration** — 10 slash commands for managing documentation in Notion
- **Session continuity** — returning projects get a one-line "ready to work" instead of re-scanning

## How It Works

Claude Code loads `~/.claude/CLAUDE.md` at the start of every session. This framework symlinks its configuration there.

**Session flow:**

| Project State | What Happens |
|--------------|-------------|
| New (empty dir) | Full onboarding: asks product idea, target user, tech preferences, priorities |
| Existing (has code, no CLAUDE.md) | Auto-scans project, asks only unknowable things, offers to generate CLAUDE.md |
| Returning (has CLAUDE.md) | Reads it, says "Ready to work", no questions |

## Install

```bash
git clone https://github.com/doyun-gu/claude-handler.git ~/claude-handler
cd ~/claude-handler
chmod +x install.sh uninstall.sh
./install.sh
```

This creates symlinks from `~/.claude/` to this repo. Edits here apply globally — no re-install needed.

If `~/.claude/CLAUDE.md` already exists, it's backed up to `~/.claude/CLAUDE.md.backup`.

### First Run

After installing, start Claude Code in any project. You'll see a one-line nudge:

> *Tip: run `/cofounder` to personalise how I work with you.*

Run `/cofounder` to start the adaptive interview. It asks 2–4 rounds of questions based on your role and experience, then saves your profile to `~/.claude/user-profile.md`.

On subsequent sessions, Claude reads the profile silently and applies your preferences (explanation depth, pushback level, tool choices, always/never rules) without asking again. Run `/cofounder` again any time to update your profile.

## Uninstall

```bash
./uninstall.sh
```

Removes symlinks and restores backups if they exist.

## Commands

### Core

| Command | When to Use |
|---------|------------|
| `/cofounder` | Adaptive interview → saves profile to `~/.claude/user-profile.md` |
| `/startup` | Re-run orientation. Refreshes context, flags outdated CLAUDE.md |
| `/onboard` | Force full onboarding from scratch (regenerate CLAUDE.md) |
| `/ready2modify` | Sync repo on a new machine (git pull, status check) |
| `/workdone` | Save and push before switching machines |

### Notion (optional — requires [Notion MCP setup](notion/README.md))

| Command | What it does |
|---------|-------------|
| `/notion-sync` | Sync Notion ↔ local dev markdown files |
| `/notion-progress` | Log today's git commits to Notion |
| `/notion-done` | End-of-session: log everything, sync files |
| `/notion-status` | Status report from Notion databases |
| `/notion-decision` | Log a technical decision |
| `/notion-milestone` | Add/update a milestone |
| `/notion-doc` | Create a styled documentation page |
| `/notion-search` | Search the workspace |
| `/notion-review` | Audit docs for quality |
| `/notion-lecture` | Create a lecture note |

**Typical session lifecycle:**

```
/ready2modify → /startup → work → /workdone
```

## Customising

### Edit the persona
Modify `global/CLAUDE.md` — changes apply immediately via symlink.

### Add commands
Create `.md` files in `global/commands/` and re-run `./install.sh`.

### Notion setup
See [notion/README.md](notion/README.md) for Notion MCP server setup and workspace initialisation.

### CLAUDE.md template
See `templates/project-claude-md.md` for the reference structure used when generating per-project CLAUDE.md files.

## Fleet System (Mac Mini Worker)

The fleet system turns a Mac Mini into an autonomous worker that picks up tasks dispatched from your MacBook Pro (Commander), runs Claude sessions, and opens PRs — all unattended.

### Quick Start: New Mac Mini Setup

```bash
# 1. Clone the repo
git clone https://github.com/doyun-gu/claude-handler.git ~/Developer/claude-handler
cd ~/Developer/claude-handler

# 2. Install symlinks + fleet directories
chmod +x install.sh
./install.sh

# 3. Set machine role
mkdir -p ~/.claude-fleet
echo 'MACHINE_ROLE=worker' > ~/.claude-fleet/machine-role.conf

# 4. Ensure prerequisites
#    - Claude CLI: ~/.local/bin/claude
#    - GitHub CLI: gh auth login
#    - tmux: brew install tmux

# 5. Install the launchd plist (starts on boot, keeps everything alive)
cp launchd/com.fleet.supervisor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.fleet.supervisor.plist

# 6. Verify it's running
tmux ls
# Should show: worker-daemon, demo-health, fleet-dashboard
```

To stop the fleet: `launchctl unload ~/Library/LaunchAgents/com.fleet.supervisor.plist`

### Process Supervision Architecture

The fleet uses a three-layer supervision model:

```
launchd (macOS)
  └─ fleet-supervisor.sh          ← kept alive by launchd (KeepAlive + RunAtLoad)
       ├─ tmux: worker-daemon     ← picks tasks from queue, runs Claude sessions
       ├─ tmux: demo-health       ← health checks, log scanning, auto-heal
       └─ tmux: fleet-dashboard   ← web dashboard API (if api.py exists)
```

**launchd** (`com.fleet.supervisor.plist`) is the root. It starts `fleet-supervisor.sh` at login and restarts it if it crashes. The `ThrottleInterval` of 10 seconds prevents rapid restart loops.

**fleet-supervisor.sh** runs an infinite loop (every 30s) that checks whether each tmux session exists. If a session is dead, it recreates it with the correct startup command. This means individual tmux sessions can crash and recover without manual intervention.

**tmux sessions** run the actual services. Each session is independent — killing one doesn't affect the others.

| Session | Script | Purpose |
|---------|--------|---------|
| `worker-daemon` | `worker-daemon.sh` | Polls `~/.claude-fleet/tasks/` for queued tasks, runs Claude autonomously |
| `demo-health` | `demo-healthcheck.sh` | Health checks, error detection, auto-heal, bug tracking |
| `fleet-dashboard` | `dashboard/api.py` | REST API for the fleet web dashboard |

### Bug Database (`bug-db.json`)

The health checker maintains a JSON bug database at `~/.claude-fleet/bug-db.json` that tracks every error it detects across services.

**Structure:** Each bug is keyed by a slug (e.g., `api-TypeError-missing-arg`, `web-crash`):

```json
{
  "bugs": {
    "api-TypeError-missing-arg": {
      "severity": "high",
      "description": "Python error in API: TypeError missing arg",
      "first_seen": "2026-03-20T10:00:00Z",
      "last_seen": "2026-03-20T11:05:00Z",
      "occurrences": 3,
      "status": "new",
      "heal_count": 1,
      "heal_timestamps": [1742468700.0],
      "escalated": false,
      "last_error": "Traceback (most recent call last)..."
    }
  }
}
```

**Bug lifecycle:** `new` → auto-healed (`healed`) or dispatched to worker (`fixed`) or too many heals (`escalated`).

**Auto-heal with cooldown protection:**

1. When a bug is detected, the health checker first checks `~/.claude-fleet/bug-knowledge/*.md` for a known fix (bash commands in a fenced code block).
2. If no KB match, it tries built-in pattern matching (webpack cache, ENOENT, port conflicts, crashes).
3. **Cooldown** prevents heal loops: if a bug has been healed 3+ times in 300 seconds, auto-heal is skipped.
4. **Escalation** at 10 total heals: the bug is marked `escalated` and auto-heal stops permanently for that slug.
5. If 3+ new bugs or 1+ critical bug accumulates, the health checker auto-creates a worker task to investigate and fix them.

The bug database is rendered to `DEBUG_DETECTOR.md` (in the monitored project directory) after every update, capped at 50 bugs sorted by last seen.

### Troubleshooting

**Health checker crash loop**

Symptom: `demo-health` tmux session keeps dying and restarting.

```bash
# Check the log for the root cause
tail -100 ~/.claude-fleet/logs/demo-health.log

# Common cause: the monitored project directory doesn't exist
ls ~/Developer/dynamic-phasors/DPSpice-com

# Common cause: python3 not in PATH
which python3

# If the health checker isn't needed for your setup, just let it restart
# harmlessly — the supervisor will keep trying every 30s but it won't
# affect the worker daemon
```

**Dashboard shows all dashes**

Symptom: The fleet dashboard UI loads but shows `—` for all metrics.

```bash
# Check if the dashboard API is actually running
curl http://localhost:5111/health

# Check if the tmux session exists
tmux has-session -t fleet-dashboard 2>/dev/null && echo "running" || echo "dead"

# Check the dashboard log for Python errors
tail -50 ~/.claude-fleet/logs/dashboard.log

# Common cause: missing Python dependencies
cd ~/Developer/claude-handler/dashboard && pip3 install -r requirements.txt

# Common cause: fleet data files don't exist yet
ls ~/.claude-fleet/tasks/*.json  # needs at least one task to show data
```

**tmux sessions not restarting**

Symptom: A tmux session dies and doesn't come back.

```bash
# Verify the supervisor is running
pgrep -f fleet-supervisor.sh

# If not, check launchd
launchctl list | grep fleet

# If launchd shows it but supervisor isn't running, check logs
cat ~/.claude-fleet/logs/supervisor-stderr.log

# Manual restart
launchctl unload ~/Library/LaunchAgents/com.fleet.supervisor.plist
launchctl load ~/Library/LaunchAgents/com.fleet.supervisor.plist

# Nuclear option: start supervisor directly
tmux new-session -d -s fleet-supervisor \
  "cd ~/Developer/claude-handler && ./fleet-supervisor.sh"
```

## File Structure

```
claude-handler/
├── README.md                          # This file
├── CLAUDE.md                          # Meta: docs for this repo
├── install.sh                         # Symlinks into ~/.claude/
├── uninstall.sh                       # Removes symlinks
├── worker-daemon.sh                   # Task queue runner (Claude sessions)
├── fleet-supervisor.sh                # Process supervisor (restarts tmux sessions)
├── demo-healthcheck.sh                # Health checks + bug tracking + auto-heal
├── launchd/
│   └── com.fleet.supervisor.plist     # macOS launchd agent for boot persistence
├── dashboard/
│   └── api.py                         # Fleet dashboard REST API
├── global/
│   ├── CLAUDE.md                      # Core — the global instructions
│   └── commands/
│       ├── cofounder.md               # /cofounder — personalisation
│       ├── startup.md                 # /startup — session orientation
│       ├── onboard.md                 # /onboard — full onboarding
│       ├── ready2modify.md            # /ready2modify — machine sync
│       └── workdone.md               # /workdone — save & push
├── notion/                            # Notion integration
│   ├── README.md                      # Notion-specific docs
│   ├── setup.sh                       # MCP server registration
│   ├── commands/                      # 10 Notion slash commands
│   ├── templates/                     # Document format definitions
│   └── schemas/                       # Database schemas
└── templates/
    └── project-claude-md.md           # CLAUDE.md reference template
```

## Author

Created by [Doyun Gu](https://github.com/doyun-gu)

## License

MIT — see [LICENSE](LICENSE)
