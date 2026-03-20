# /worker-review — Review and merge Worker output

You are Commander (MacBook Pro). Reviews completed Mac Mini Worker PRs.

## Steps

1. **Find Worker PRs**: `gh pr list --search "head:worker/" --state open --json number,title,headRefName,url,additions,deletions,changedFiles`. Also scan `~/.claude-fleet/tasks/*.json` for completed tasks without PRs.

2. **Read summary**: `ssh mac-mini "cat ~/.claude-fleet/logs/<TASK_ID>.summary.md"`. If none, read last 100 lines of log.

3. **Show diff**: `gh pr diff <NUMBER>` (if >500 lines, use `--stat`).

4. **Present**: Task dispatched, Worker result (from summary), changes (file-level stat), test status, merge recommendation.

5. **User decides**: A) Squash merge, B) Regular merge, C) Run /review first, D) Close without merge, E) Skip to next.

6. **After merge**: Pull updated main. Update task manifest status to `merged` with timestamp. Offer `/notion-progress`.

If multiple PRs: show numbered list, let user pick or "review all". After all reviews, offer cleanup: `git fetch --prune origin`, archive old manifests.
