# claude-handler

Turn any Mac into an autonomous AI development fleet. Installs a Technical Co-Founder persona, smart onboarding, and fleet orchestration into Claude Code.

## First-Time Setup (Interactive Onboarding)

When someone clones this repo and opens Claude Code here for the first time, guide them through setup interactively. **Do not run install.sh silently** — walk them through it.

### Step 1: Welcome and gather info

Ask these questions conversationally (can be a single message):

1. **What's your name?** — For git config and personalisation.
2. **What projects do you work on?** — Collect project names and paths (or repo URLs) to populate `~/.claude-fleet/projects.json`.
3. **Do you have a second machine (Mac Mini, desktop, old laptop, cloud VM) to use as a Worker?**
   - If **yes**: What's the SSH hostname? Test the connection with `ssh -o ConnectTimeout=5 <host> "echo ok"`. Set up as Commander + Worker.
   - If **no**: Set up as Hybrid mode (Commander + Worker on same machine).
4. **Do you want email notifications when tasks complete?** — If yes, guide Gmail app password setup (link them to https://myaccount.google.com/apppasswords).
5. **Where do your projects live?** (default: ~/Developer)

### Step 2: Run install.sh with answers

After gathering info, run `./install.sh` and provide the answers interactively. Or generate the config files directly:

```bash
# Run the interactive installer
chmod +x install.sh && ./install.sh
```

### Step 3: Populate projects.json

Based on the projects they mentioned, write `~/.claude-fleet/projects.json`:

```json
[
  {"name": "project-name", "path": "/path/to/project", "repo": "git@github.com:user/repo.git"}
]
```

### Step 4: Verify everything works

1. Check symlinks: `ls -la ~/.claude/CLAUDE.md` should point to this repo
2. Check fleet dir: `ls ~/.claude-fleet/`
3. If Worker mode: check launchd with `launchctl list | grep fleet`
4. Suggest running `/cofounder` to personalise the experience

### Step 5: Explain what they get

After setup, briefly explain:
- `/dispatch "task description"` sends work to the Worker
- `/queue` shows Worker status
- `/worker-review` reviews completed PRs
- `/cofounder` personalises Claude's behaviour
- The Worker daemon runs tasks autonomously and opens PRs

## File Structure

```
claude-handler/
├── CLAUDE.md                          # This file — onboarding + repo docs
├── README.md                          # User-facing documentation
├── install.sh                         # Interactive installer (Commander/Worker/Hybrid)
├── uninstall.sh                       # Clean uninstall with launchd cleanup
├── worker-daemon.sh                   # Autonomous Worker daemon
├── fleet-supervisor.sh                # Process supervisor (keeps daemon alive)
├── fleet-startup.sh                   # Boot-time service starter
├── fleet-notify.sh                    # Email notifications via Gmail
├── fleet-brain.py                     # Intelligent queue manager
├── queue-manager.py                   # Task scheduling with affinity
├── fleet-rules.md                     # Operational rules for all agents
├── global/
│   ├── CLAUDE.md                      # Core — symlinked to ~/.claude/CLAUDE.md
│   └── commands/                      # Slash commands (symlinked to ~/.claude/commands/)
├── notion/
│   ├── commands/                      # 10 Notion slash commands
│   ├── templates/                     # Document format definitions
│   └── schemas/                       # Database schemas
├── dashboard/
│   ├── api.py                         # Fleet dashboard (FastAPI, :3003)
│   └── index.html                     # Dashboard frontend
├── templates/
│   ├── projects.json.example          # Project registry format
│   ├── machine-role.conf.example      # Role configuration reference
│   ├── gmail.conf.example             # Email notification setup
│   ├── com.fleet.supervisor.plist.template  # launchd template
│   ├── startup-hooks.sh.example       # User-defined boot services
│   └── project-claude-md.md           # CLAUDE.md generation template
├── launchd/
│   └── com.fleet.supervisor.plist     # launchd plist (template with placeholders)
└── handoff/
    ├── install-handoff.sh             # Sleep/wake hooks
    ├── on-sleep.sh                    # Runs on lid close
    └── on-wake.sh                     # Runs on lid open
```

## Dev Commands

```bash
./install.sh      # Interactive install (Commander/Worker/Hybrid)
./uninstall.sh    # Clean uninstall (stops services, removes symlinks)
```

## Key Concepts

- **Commander**: Your interactive machine (laptop). Dispatches tasks, reviews PRs.
- **Worker**: Autonomous machine. Runs tasks from queue, opens PRs.
- **Hybrid**: Single machine acting as both.
- `global/CLAUDE.md` is the core — symlinked to `~/.claude/CLAUDE.md`, loaded every session.
- All slash commands are `.md` files discovered dynamically by install.sh.
- Config templates in `templates/` have `.example` or `.template` suffix — never committed with real values.

## Conventions

- `global/CLAUDE.md` should stay under 400 lines (token efficiency — loaded every session).
- Symlinks allow editing in this repo and having changes apply globally immediately.
- No hardcoded paths — scripts use `$HOME`, config reads from `~/.claude-fleet/machine-role.conf`.
- Secrets go in `~/.claude-fleet/secrets/` (gitignored, chmod 600).
