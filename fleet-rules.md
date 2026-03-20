# Fleet Rules — Source of Truth for All Agents

This file is read by fleet-brain.py, worker-daemon.sh, and any Claude agent
running on the fleet. It codifies the user's preferences and operational rules.
If a rule here conflicts with a default behavior, this file wins.

## Priority System

| Level | Source | priority value | When to run |
|---|---|---|---|
| **P0** | User-dispatched (prompt or /dispatch) | >= 0 | Always first, preempt backlog |
| **P1** | Auto-fix from bug detection | -1 | Immediately, don't block P0 |
| **P2** | Backlog/maintenance/reviews/audits | <= -2 | Only when no P0/P1 queued |

- User tasks ALWAYS win. If user dispatches while backlog runs, P0 goes next.
- Tasks with slug containing `maintenance`, `review`, `audit`, `optimization` default to P2.
- Bug auto-fix tasks default to P1.
- Never run P2 heavy tasks (reviews, audits) in parallel with P0 feature work.

## Scheduling Rules

- **Daytime (8am-11pm user local):** Only run user-dispatched tasks unless idle 30+ min.
- **Night/away time:** Run backlog freely.
- **User says "I'll be away":** Start backlog immediately, stop when they return.
- **User says "going to sleep":** Full autonomy — run everything, manage queue, merge PRs.

## Auto-Merge Policy

**Auto-merge (no human review needed):**
- Documentation, .context/, CLAUDE.md, README updates
- Architecture docs, file-maps, patterns
- Infrastructure (daemon, healthcheck, scripts, configs)
- Test additions/fixes
- Lint fixes, dependency updates (npm audit fix)
- Bug fixes with passing tests
- Any PR where change is clearly correct and reversible

**Needs human review (flag as ACTION REQUIRED):**
- UI/UX changes — user must see visually
- New features
- Large refactors (>500 lines changed in source code)
- User-facing content (personal website, marketing pages)
- Architecture decisions with tradeoffs
- Irreversible actions (data deletion, schema changes)

## Queue Management Autonomy

The fleet manager has full authority over operational decisions:
- Stuck task? Kill and auto-retry (max 3). Don't ask.
- Failed 3x? Write review-queue item, move on.
- Similar tasks queued? Merge if same group AND >60% topic overlap AND max 3.
- Queue idle? Check if maintenance is due (every 2-3 days, max 2x/week).
- Conflict on PR? Diagnose, create fix task at priority 10.
- Never merge retried tasks or combined tasks with other tasks.

## Bug Response

| Bug type | Response | Notify user? |
|---|---|---|
| Crash loop, cache corruption | Auto-fix (clear cache, restart) | No |
| Port conflict | Auto-fix (kill process, restart) | No |
| Build failure | Diagnose, dispatch fix task | No |
| Service down >5min | Restart, escalate if persists | Only if persists |
| Task failed 3x | Escalate | Yes (email) |
| Task blocked | Escalate | Yes (email) |
| Unknown error | Diagnose, dispatch fix, log to knowledge base | No |

## Demo Server Rules

| Port | Role | Stability |
|---|---|---|
| 3001 | Dev / unstable | Can break |
| 3002 | **Stable demo** (shown to people) | Must ALWAYS work |
| 3003 | Fleet dashboard | Should work |
| 8000 | API backend | Must ALWAYS work |

- Never deploy to :3002 without: build pass, all tests pass, 5-min smoke test on :3001.
- During meeting freeze windows: no merges, no deploys, no restarts on DPSpice services.
- Worker can run non-DPSpice tasks during freeze windows.

## Notification Rules

- **Email only for:** task FAILED (3x), task BLOCKED, critical alerts.
- **Hourly digest max** for completions — never individual emails per task.
- **Dashboard at :3003** is the primary notification channel, not email.
- **Suppress:** task completed, bug auto-fixed, merge confirmations, queue updates.

## Backup Rules

- **my-world** is the disaster recovery repo.
- After meaningful fleet changes, queue a my-world-backup-sync task.
- Batch syncs — one per session, not per change.
- Never commit secrets to my-world. Use templates with placeholders.

## Token Efficiency

- For large codebases (>10K LOC), .context/ directory is mandatory.
- Vendor/generated code: list in .claudeignore, never read.
- Worker system prompt: keep under 500 tokens. Every word is multiplied by every task.
- Prefer editing existing files over creating new ones.
- Combined tasks: max 3, same group, >60% overlap, max 4000 chars prompt.

## Idle Project Utilisation

When a project has no queued tasks but the daemon is running other projects:
- Don't let projects sit idle. Queue useful backlog work:
  - Health checks (run tests, verify build)
  - Code quality (lint, dead code removal)
  - Documentation freshness (.context/ files up to date?)
  - Stale branch cleanup
- Only queue P2 backlog — never auto-generate P0 work.
- Respect demo freeze windows (no DPSpice deploys during meetings).
- The goal: Mac Mini should always be working on something useful, never idle.

## Demo Freeze Windows

- Before meetings/demos: freeze DPSpice deploys 30 min before through 15 min after.
- During freeze: Worker can still run non-DPSpice tasks (claude-handler, my-world, JULY, etc.)
- DPSpice docs/research/non-deploy work is OK during freeze.
- If critical bug found on :3002 before meeting: fix and re-test immediately.

## Maintenance Cadence

- Every 2-3 days or weekly. Not nightly.
- Auto-idle detection OK but max 2x/week.
- Maintenance tasks run at P2 — only when queue is truly empty.
