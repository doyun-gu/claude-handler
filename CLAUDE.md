# claude-handler

Framework that installs a Technical Co-Founder persona and smart onboarding into Claude Code globally. Symlinks into `~/.claude/` so it activates for every project.

## File Structure

```
claude-handler/
├── CLAUDE.md                          # This file — meta docs for the repo itself
├── README.md                          # User-facing documentation
├── install.sh                         # Symlinks global/ files into ~/.claude/
├── uninstall.sh                       # Removes symlinks, restores backups
├── global/
│   ├── CLAUDE.md                      # Core — symlinked to ~/.claude/CLAUDE.md
│   └── commands/
│       ├── startup.md                 # /startup command
│       └── onboard.md                 # /onboard command
└── templates/
    └── project-claude-md.md           # Reference template for generated CLAUDE.md files
```

## Key Files

| File | Purpose |
|------|---------|
| `global/CLAUDE.md` | Core deliverable. Loaded every Claude session. Contains persona, startup protocol, workflow phases, CLAUDE.md generation format. |
| `global/commands/startup.md` | Re-runs orientation. Detects project state, flags outdated CLAUDE.md. |
| `global/commands/onboard.md` | Forces full onboarding regardless of existing CLAUDE.md. |
| `templates/project-claude-md.md` | Human-readable reference for the CLAUDE.md structure. |
| `install.sh` | Creates symlinks, backs up existing files, preserves other commands. |
| `uninstall.sh` | Removes symlinks, restores backups. |

## Dev Commands

```bash
./install.sh      # Install (symlink into ~/.claude/)
./uninstall.sh    # Uninstall (remove symlinks, restore backups)
```

## Conventions

- `global/CLAUDE.md` should stay under 400 lines (loaded every session — token efficiency matters).
- Never modify or overwrite existing commands (`ready2modify.md`, `workdone.md`) during install.
- Symlinks allow editing in this repo and having changes apply globally immediately.
