I just switched to this machine and need to pick up where I left off. Please do the following:

## Step 1: Read the handoff

Check for `~/.claude-fleet/HANDOFF.md` or `~/Developer/my-world/HANDOFF.md`. If it exists, read it — this is the session summary from the last machine/session. Present the key info:
- What was completed
- What's still pending
- Any decisions or blockers
- What to pick up first

If no HANDOFF.md exists, skip this step silently.

## Step 2: Sync code

1. Run `git fetch --all` and `git pull --ff-only` to get the latest changes.
2. Run `git status` to show the current state.
3. Run `git log --oneline -10` to show recent commits.

## Step 3: Check fleet state (if applicable)

```bash
# Check for pending review items
ls ~/.claude-fleet/review-queue/*.md 2>/dev/null
# Check for running/queued tasks
ls ~/.claude-fleet/tasks/*.json 2>/dev/null | head -5
```

## Step 4: Brief summary

Give me a concise status:
- What the handoff says (if it exists)
- Current git state
- Any pending worker tasks or review items
- Suggested next action

Keep it short — I want to start working, not read a report.
