# claude-handler

Framework that installs a Technical Co-Founder persona, smart onboarding, and Notion integration into Claude Code globally. Symlinks into `~/.claude/` so it activates for every project.

## File Structure

```
claude-handler/
├── CLAUDE.md                          # This file — meta docs for the repo itself
├── README.md                          # User-facing documentation
├── install.sh                         # Symlinks global/ + notion/ into ~/.claude/
├── uninstall.sh                       # Removes symlinks, restores backups
├── global/
│   ├── CLAUDE.md                      # Core — symlinked to ~/.claude/CLAUDE.md
│   └── commands/
│       ├── cofounder.md               # /cofounder — personalisation interview
│       ├── startup.md                 # /startup command
│       ├── onboard.md                 # /onboard command
│       ├── ready2modify.md            # /ready2modify command
│       └── workdone.md               # /workdone command
├── notion/
│   ├── commands/                      # 10 Notion slash commands
│   ├── templates/                     # Document format definitions
│   ├── schemas/                       # Database schemas
│   └── ...
└── templates/
    └── project-claude-md.md           # Reference template for generated CLAUDE.md files
```

## Key Files

| File | Purpose |
|------|---------|
| `global/CLAUDE.md` | Core deliverable. Loaded every Claude session. Contains persona, startup protocol, workflow phases, CLAUDE.md generation format. |
| `global/commands/cofounder.md` | Personalisation interview. Gathers user's role, expertise, preferences and appends to global CLAUDE.md. |
| `global/commands/startup.md` | Re-runs orientation. Detects project state, flags outdated CLAUDE.md. |
| `global/commands/onboard.md` | Forces full onboarding regardless of existing CLAUDE.md. |
| `global/commands/ready2modify.md` | Pulls latest changes when switching machines. |
| `global/commands/workdone.md` | Commits and pushes before switching machines. |
| `notion/commands/notion-*.md` | 10 Notion workspace management commands. |
| `templates/project-claude-md.md` | Human-readable reference for the CLAUDE.md structure. |
| `install.sh` | Creates symlinks, backs up existing files. |
| `uninstall.sh` | Removes symlinks, restores backups. |

## Dev Commands

```bash
./install.sh      # Install (symlink into ~/.claude/)
./uninstall.sh    # Uninstall (remove symlinks, restore backups)
```

## Conventions

- `global/CLAUDE.md` should stay under 400 lines (loaded every session — token efficiency matters).
- Symlinks allow editing in this repo and having changes apply globally immediately.
- The install script dynamically discovers all `.md` files in `global/commands/` and `notion/commands/` — no need to hardcode new command names.
