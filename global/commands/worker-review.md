# /worker-review — Review and merge Worker output

You are the Commander (MacBook Pro). This command reviews completed work from the Mac Mini Worker and helps merge it.

## Steps

### Step 1: Find completed Worker PRs

```bash
gh pr list --search "head:worker/" --state open --json number,title,headRefName,url,additions,deletions,changedFiles
```

Also check local task manifests for completed tasks that may not have PRs yet:

```bash
for f in ~/.claude-fleet/tasks/*.json; do
  python3 -c "
import json, sys
d = json.load(open('$f'))
if d.get('status') == 'completed':
    print(f\"{d['id']}  {d['branch']}  {d.get('pr_url', 'NO PR')}  {d.get('result_summary', '')[:80]}\")
" 2>/dev/null
done
```

### Step 2: Read the Worker's summary

For the selected task, check if a summary exists on the Worker:

```bash
ssh mac-mini "cat ~/.claude-fleet/logs/<TASK_ID>.summary.md 2>/dev/null"
```

If no summary, read the last 100 lines of the log:

```bash
ssh mac-mini "tail -100 ~/.claude-fleet/logs/<TASK_ID>.log 2>/dev/null"
```

### Step 3: Show the PR diff

```bash
gh pr diff <PR_NUMBER>
```

If the diff is large (>500 lines), summarise the changes by file:

```bash
gh pr diff <PR_NUMBER> --stat
```

### Step 4: Present review summary

Show the user:
1. **Task**: What was dispatched
2. **Result**: What the Worker did (from summary)
3. **Changes**: File-level diff stat
4. **Tests**: Whether tests pass (check PR status checks)
5. **Recommendation**: Merge, request changes, or close

### Step 5: User decides

Offer these options:

- **A) Merge (squash)**: `gh pr merge <NUMBER> --squash --delete-branch`
- **B) Merge (regular)**: `gh pr merge <NUMBER> --merge --delete-branch`
- **C) Run /review first**: Checkout the worker branch locally, run gstack `/review` for a deeper code review, then decide
- **D) Close without merging**: `gh pr close <NUMBER>` and optionally delete the branch
- **E) Skip**: Move to the next completed task

### Step 6: After merge

After merging:

1. Pull the updated main:
```bash
git pull origin main
```

2. Update the task manifest status to `merged`:
```bash
# Update local manifest
python3 -c "
import json
f = open('$HOME/.claude-fleet/tasks/<TASK_ID>.json', 'r+')
d = json.load(f)
d['status'] = 'merged'
d['merged_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
f.seek(0); json.dump(d, f, indent=2); f.truncate()
"
```

3. Optionally log to Notion:
Ask: "Log this to Notion? (runs /notion-progress)"

### Multiple PRs

If there are multiple completed Worker PRs, iterate through them one at a time. Show a numbered list first, let the user pick which to review, or offer "review all."

## Cleanup

After reviewing all tasks, offer to clean up:

```bash
# Remove merged worker branches from remote
git fetch --prune origin

# Archive old task manifests (>7 days, status=merged)
mkdir -p ~/.claude-fleet/archive
```
