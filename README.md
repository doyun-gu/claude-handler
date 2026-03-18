# claude-handler

A reusable framework that turns Claude Code into a Technical Co-Founder. Installs globally via symlinks so it activates automatically for every project.

## What It Does

- **Technical Co-Founder persona** — Claude pushes back on bad ideas, thinks product-first, and ships incrementally
- **Smart onboarding** — auto-detects existing projects (tech stack, git history, file structure) and only asks what it can't figure out
- **Personalisation** — `/cofounder` command tailors Claude to your role, expertise, and preferences
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

After installing, start Claude Code and run:

```
/cofounder
```

This walks you through a short interview to personalise the co-founder to your role, experience, and preferences.

## Uninstall

```bash
./uninstall.sh
```

Removes symlinks and restores backups if they exist.

## Commands

### Core

| Command | When to Use |
|---------|------------|
| `/cofounder` | Personalise Claude to your role, expertise, and work style |
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

## File Structure

```
claude-handler/
├── README.md                          # This file
├── CLAUDE.md                          # Meta: docs for this repo
├── install.sh                         # Symlinks into ~/.claude/
├── uninstall.sh                       # Removes symlinks
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
