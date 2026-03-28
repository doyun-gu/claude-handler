# claude-handler

Framework that turns Claude Code into a Technical Co-Founder with an optional dual-machine fleet system. Symlinks into `~/.claude/` so it activates for every project.

## File Structure

```
claude-handler/
├── CLAUDE.md                          # This file — meta docs for the repo itself
├── CHANGELOG.md                       # Release history (Keep a Changelog format)
├── VERSION                            # Current version (semver)
├── README.md                          # User-facing documentation
│
├── install.sh                         # Interactive installer (Commander/Worker role)
├── install-launchd.sh                 # Generate LaunchAgent from template
├── uninstall.sh                       # Removes symlinks, restores backups
├── release.sh                         # Cut a versioned release (tag + GitHub release)
│
├── worker-daemon.sh                   # Autonomous Worker daemon (task queue processor)
├── fleet-brain.py                     # Task scheduling, scoring, PR management
├── task-db.py                         # SQLite task database (atomic claiming, heartbeats)
├── file-lock.py                       # Prevents parallel tasks editing same files
├── bug-db.py                          # Bug tracking database (extracted from healthcheck)
│
├── fleet-startup.sh                   # Boot-time service launcher (LaunchAgent)
├── fleet-supervisor.sh                # Process supervisor (keeps tmux alive)
├── fleet-backup.sh                    # Fleet state backup
├── fleet-diagnose.py                  # Diagnostic utility (health, errors, stuck tasks)
├── fleet-notify.sh                    # Gmail notifications + reply-to-action
├── fleet-status-server.sh             # Lightweight status endpoint
├── health-monitor.py                  # Service health checks + auto-fix
├── demo-healthcheck.sh                # Project health checks + auto-heal
│
├── sync-to-macbook.sh                 # Sync fleet state to second machine
├── memory-sync.sh                     # Cross-machine memory synchronization
├── setup-xps.sh                       # Dell XPS worker setup script
│
├── dashboard/
│   ├── api.py                         # FastAPI fleet dashboard backend
│   ├── db.py                          # SQLite database layer (WAL mode)
│   ├── index.html                     # Dashboard frontend (Kanban view)
│   ├── requirements-test.txt          # Test dependencies
│   └── tests/
│       ├── conftest.py                # Shared fixtures (temp DB, test client)
│       ├── test_db.py                 # Database layer tests
│       └── test_api.py                # API endpoint tests
│
├── tests/
│   ├── conftest.py                    # Shared fixtures
│   ├── test_task_db.py                # Task database tests
│   └── test_brain.py                  # Scheduler scoring/logic tests
│
├── config.example/                    # Example configs (safe to commit)
│   ├── projects.json.example
│   ├── machine-role.conf.example
│   └── gmail.conf.example
├── launchd/
│   └── com.fleet.supervisor.plist.template
├── docs/
│   ├── ARCHITECTURE.md                # System architecture overview
│   └── ERROR-CODES.md                 # Daemon error code reference (D-001..D-050)
│
├── global/
│   ├── CLAUDE.md                      # Core — symlinked to ~/.claude/CLAUDE.md
│   └── commands/                      # Slash commands (symlinked to ~/.claude/commands/)
├── notion/
│   ├── commands/                       # Notion slash commands
│   ├── templates/                     # Document format definitions
│   └── schemas/                       # Database schemas
├── handoff/                           # Sleep/wake sync between machines
└── templates/
    └── project-claude-md.md           # CLAUDE.md generation template
```

## Key Files

### Core daemon
| File | Purpose |
|------|---------|
| `worker-daemon.sh` | Main worker loop. Polls task queue, runs Claude sessions, manages process lifecycle. 50+ error codes. |
| `fleet-brain.py` | Task scheduler — scoring, priority ordering, dependency chains, topic affinity, PR management. |
| `task-db.py` | SQLite task database — atomic claiming, heartbeat tracking, dependency validation. |
| `file-lock.py` | Prevents parallel tasks from editing the same files. Keyword-to-path heuristics. |
| `bug-db.py` | Bug tracking — occurrence counts, escalation thresholds. CLI + importable module. |

### Dashboard
| File | Purpose |
|------|---------|
| `dashboard/api.py` | FastAPI backend — task CRUD, review queue, analytics, machine status. |
| `dashboard/db.py` | SQLite layer with WAL mode. Schema migrations, parameterized queries. |
| `dashboard/index.html` | Frontend — Kanban task queue, completed table, project filters, service health. |

### Infrastructure
| File | Purpose |
|------|---------|
| `fleet-startup.sh` | Boot-time launcher. Starts all services in tmux. Dynamic PATH detection. |
| `fleet-supervisor.sh` | Keepalive daemon. Restarts dead tmux sessions every 30s. |
| `health-monitor.py` | Service health checks (port probing, HTTP checks) + auto-fix with backoff. |
| `fleet-diagnose.py` | Diagnostic utility — scans logs, counts errors by type, finds stuck tasks. |

### Setup & release
| File | Purpose |
|------|---------|
| `install.sh` | Interactive installer — Commander/Worker role, fleet dirs, example configs. |
| `release.sh` | Cut versioned release — updates CHANGELOG, tags, pushes, creates GitHub release. |
| `global/CLAUDE.md` | Core persona. Symlinked to `~/.claude/CLAUDE.md`. Loaded every session. |

## Dev Commands

```bash
# Setup
./install.sh           # Install (interactive — choose Commander/Worker)
./install-launchd.sh   # Install LaunchAgent (Worker only)
./uninstall.sh         # Uninstall (remove symlinks, restore backups)

# Release
./release.sh           # Cut a release (reads VERSION, updates CHANGELOG, tags, pushes)
./release.sh --dry-run # Preview release without committing
./release.sh 0.6.0     # Release with explicit version override

# Tests
cd dashboard && python3 -m pytest tests/ -v     # Dashboard DB + API tests
python3 -m pytest tests/ -v                      # Daemon task-db + brain tests

# Diagnostics
python3 fleet-diagnose.py                        # Fleet health report
python3 task-db.py list                           # List all tasks
python3 task-db.py list --status running          # Filter by status
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
