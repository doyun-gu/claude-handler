# Dual-Machine Fleet Workflow

## Commands
| Command | What it does |
|---------|-------------|
| `/dispatch` | Send task to Mac Mini Worker |
| `/worker-status` | Check Worker progress |
| `/worker-review` | Review and merge Worker PRs |

## Git Branch Strategy
- Commander: `main`, `feature/*`, `fix/*`
- Worker: `worker/<task>-<date>` (never pushes to main)

## Dispatch Workflow
See `~/.claude/projects/-Users-doyungu/memory/reference_dispatch_workflow.md` for step-by-step.

## Review Queue
Workers log to `~/.claude-fleet/review-queue/`:
- `*-completed.md`: PR ready for review
- `*-failed.md`: task crashed
- `*-blocked.md`: needs Commander help
- `*-decision.md`: wants confirmation

## When to Dispatch vs Do Locally
| Dispatch | Local |
|----------|-------|
| Feature (>30 min) | Quick fixes |
| Full QA | Code review |
| Large refactors | Planning |
| Overnight work | Git/PR management |
