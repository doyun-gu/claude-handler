# claude-handler

Framework that turns Claude Code into a Technical Co-Founder with an optional dual-machine fleet system. Symlinks into `~/.claude/` so it activates for every project.

## File Structure

```
claude-handler/
├── CLAUDE.md                          # This file — meta docs for the repo itself
├── CHANGELOG.md                       # Release history (Keep a Changelog format)
├── VERSION                            # Current version (semver)
├── README.md                          # User-facing documentation
├── release.sh                         # Cut a versioned release (tag + GitHub release)
├── install.sh                         # Interactive installer (Commander/Worker role)
├── install-launchd.sh                 # Generate LaunchAgent from template
├── uninstall.sh                       # Removes symlinks, restores backups
├── worker-daemon.sh                   # Autonomous Worker daemon
├── fleet-startup.sh                   # Boot-time service launcher
├── fleet-supervisor.sh                # Process supervisor (keeps tmux alive)
├── demo-healthcheck.sh                # Health checks + log scanning + auto-heal
├── fleet-notify.sh                    # Gmail notifications + reply-to-action
├── fleet-brain.py                     # Task scheduling + PR management
├── queue-manager.py                   # Smart task queue with priorities
├── sync-to-macbook.sh                 # Sync to a second machine
├── config.example/                    # Example configs (safe to commit)
│   ├── projects.json.example
│   ├── machine-role.conf.example
│   └── gmail.conf.example
├── launchd/
│   └── com.fleet.supervisor.plist.template  # LaunchAgent template
├── dashboard/
│   ├── api.py                         # FastAPI fleet dashboard backend
│   └── index.html                     # Dashboard frontend
├── global/
│   ├── CLAUDE.md                      # Core — symlinked to ~/.claude/CLAUDE.md
│   └── commands/                      # Slash commands (symlinked to ~/.claude/commands/)
├── notion/
│   ├── commands/                      # 10 Notion slash commands
│   ├── templates/                     # Document format definitions
│   └── schemas/                       # Database schemas
├── handoff/                           # Sleep/wake sync between machines
└── templates/
    └── project-claude-md.md           # CLAUDE.md generation template
```

## Key Files

| File | Purpose |
|------|---------|
| `global/CLAUDE.md` | Core deliverable. Loaded every Claude session. Contains persona, startup protocol, workflow phases, CLAUDE.md generation format. |
| `install.sh` | Interactive installer — asks Commander/Worker role, creates fleet dirs, copies example configs. |
| `install-launchd.sh` | Generates LaunchAgent plist from template with current user's $HOME. |
| `worker-daemon.sh` | Runs on Worker. Watches task queue, runs Claude sessions back-to-back. |
| `fleet-supervisor.sh` | Managed by launchd. Ensures tmux sessions stay alive. |
| `fleet-startup.sh` | Runs on boot. Starts all services in tmux. Dynamic PATH detection. |
| `demo-healthcheck.sh` | Health checks, log scanning, bug DB, auto-heal. Dynamic IP detection. |
| `fleet-notify.sh` | Gmail notifications with reply-to-action (merge/fix/skip/queue). |
| `config.example/` | Example configs showing format without real credentials. |
| `release.sh` | Cut a versioned release — updates CHANGELOG, tags, pushes, creates GitHub release. |
| `CHANGELOG.md` | Full release history in Keep a Changelog format. |
| `VERSION` | Single-line semver string (e.g. `0.5.0`). |

## Dev Commands

```bash
./install.sh           # Install (interactive — choose Commander/Worker)
./install-launchd.sh   # Install LaunchAgent (Worker only)
./uninstall.sh         # Uninstall (remove symlinks, restore backups)
./release.sh           # Cut a release (reads VERSION, updates CHANGELOG, tags, pushes)
./release.sh --dry-run # Preview release without committing
./release.sh 0.6.0     # Release with explicit version override
```

## User Profile

The `/cofounder` command writes to `~/.claude/user-profile.md` — a standalone file outside this repo. This is intentional:
- **Privacy:** Personal info (role, preferences, rules) never gets committed to the public repo.
- **Separation:** The profile is per-machine, not per-project. It lives in `~/.claude/` alongside the symlinked global CLAUDE.md.
- **Session startup:** `global/CLAUDE.md` has a pre-check that reads `user-profile.md` silently at every session start. If the file doesn't exist, it nudges the user to run `/cofounder`.

The profile is NOT managed by `install.sh` / `uninstall.sh` — it persists independently.

## Conventions

- `global/CLAUDE.md` should stay under 400 lines (loaded every session — token efficiency matters).
- Symlinks allow editing in this repo and having changes apply globally immediately.
- The install script dynamically discovers all `.md` files in `global/commands/` and `notion/commands/` — no need to hardcode new command names.
- No hardcoded user paths in scripts. Use `$HOME`, `$(dirname "$0")`, or dynamic detection.
- Secrets and personal configs are in `~/.claude-fleet/` (gitignored). Example configs are in `config.example/`.
