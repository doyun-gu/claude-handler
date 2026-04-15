# Session Startup Protocol

At the start of every session, run this decision tree:

## Pre-check: Machine Role
1. Check `~/.claude-fleet/machine-role.conf`. Note MACHINE_ROLE (commander/worker).
2. Commander = interactive. Worker = autonomous, worker/ branches only.
3. If not found, assume commander.

## Pre-check: User Profile
1. Read `~/.claude/user-profile.md` silently if it exists. Apply preferences.

## Pre-check: Handoff
1. Read `~/.claude-fleet/HANDOFF.md` or `~/Developer/my-world/HANDOFF.md`.
2. If from today/yesterday: surface actionable items. If older: mention briefly.

## Pre-check: Auto-Sync
```bash
git fetch origin 2>/dev/null && git pull --ff-only origin $(git branch --show-current) 2>/dev/null
```

## Pre-check: Review Queue (Commander only)
```bash
ls ~/.claude-fleet/review-queue/*.md 2>/dev/null
```
Categorise: blocked (surface immediately), failed (high priority), completed (actionable), decision_needed (informational).

## Greeting
- Returning project (has CLAUDE.md): one-line status
- Existing project (no CLAUDE.md): auto-scan, ask 5 questions
- New project: full onboarding
