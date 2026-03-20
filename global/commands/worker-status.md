# /worker-status — Check Mac Mini Worker progress

You are Commander (MacBook Pro). Checks status of all dispatched Worker tasks.

## Steps

1. Read `~/.claude-fleet/machine-role.conf`. If missing: "Fleet not set up."

2. Read all `~/.claude-fleet/tasks/*.json` — note id, slug, status, branch, dispatched_at, tmux_session.

3. SSH to Mac Mini: list active `claude-*` tmux sessions. For each matching a known task, capture last 30 lines of output.

4. Check Worker task manifests via SSH for updated statuses.

5. Check GitHub: `gh pr list --search "head:worker/" --state open`.

6. **Present dashboard** — format as status table grouped by state (RUNNING with elapsed time + last output line, BLOCKED with reason, COMPLETED with duration + PR link, FAILED with error). Show open Worker PRs.

7. **Offer actions**: Completed → `/worker-review`. Blocked → show blocker, offer unblock/cancel. Failed → show log or re-dispatch. Running → "check back later."

**Quick peek**: If user specifies a slug, show only that task + last 50 lines of tmux output.
