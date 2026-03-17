# claude-handler

A reusable framework that turns Claude Code into a Technical Co-Founder. Installs globally via symlinks so it activates automatically for every project.

## What It Does

- **Technical Co-Founder persona** — Claude pushes back on bad ideas, thinks product-first, and ships incrementally
- **Smart onboarding** — auto-detects existing projects (tech stack, git history, file structure) and only asks what it can't figure out
- **Project CLAUDE.md generation** — creates per-project context files so future sessions start instantly
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
git clone <this-repo> ~/Developer/claude-handler
cd ~/Developer/claude-handler
chmod +x install.sh uninstall.sh
./install.sh
```

This creates symlinks:
- `~/.claude/CLAUDE.md` → `global/CLAUDE.md`
- `~/.claude/commands/startup.md` → `global/commands/startup.md`
- `~/.claude/commands/onboard.md` → `global/commands/onboard.md`

Existing commands (`ready2modify.md`, `workdone.md`) are never touched.

If `~/.claude/CLAUDE.md` already exists, it's backed up to `~/.claude/CLAUDE.md.backup`.

## Uninstall

```bash
./uninstall.sh
```

Removes symlinks and restores backups if they exist.

## Commands

| Command | When to Use |
|---------|------------|
| `/startup` | Re-run orientation. Refreshes context, flags outdated CLAUDE.md |
| `/onboard` | Force full onboarding from scratch (regenerate CLAUDE.md) |
| `/ready2modify` | Sync repo on a new machine (git pull, status check) |
| `/workdone` | Save and push before switching machines |

**Typical session lifecycle:**

```
/ready2modify → /startup → work → /workdone
```

## Customizing

### Edit the persona
Modify `global/CLAUDE.md` — changes apply immediately via symlink (no re-install needed).

### Add commands
Create `.md` files in `global/commands/` and re-run `./install.sh`, or place them directly in `~/.claude/commands/`.

### CLAUDE.md template
See `templates/project-claude-md.md` for the reference structure used when generating per-project CLAUDE.md files.

## File Structure

```
claude-handler/
├── CLAUDE.md                          # Meta: docs for this repo
├── README.md                          # This file
├── install.sh                         # Symlinks into ~/.claude/
├── uninstall.sh                       # Removes symlinks
├── global/
│   ├── CLAUDE.md                      # Core — the global instructions
│   └── commands/
│       ├── startup.md                 # /startup command
│       └── onboard.md                 # /onboard command
└── templates/
    └── project-claude-md.md           # CLAUDE.md reference template
```
