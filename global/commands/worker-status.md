# /worker-status — Check Mac Mini Worker progress

You are the Commander (MacBook Pro). This command checks the status of all tasks dispatched to the Mac Mini Worker.

## Steps

### Step 1: Read fleet config

```bash
cat ~/.claude-fleet/machine-role.conf 2>/dev/null
```

If the file doesn't exist, tell the user: "Fleet not set up. Run `~/.claude/setup-fleet.sh` first."

### Step 2: Check local task manifests

```bash
ls -t ~/.claude-fleet/tasks/*.json 2>/dev/null
```

Read each JSON file. Note the `id`, `slug`, `status`, `branch`, `dispatched_at`, `tmux_session`.

### Step 3: SSH to Mac Mini for live status

```bash
# List active Claude tmux sessions
ssh mac-mini "tmux list-sessions 2>/dev/null | grep '^claude-' || echo 'No active sessions'"
```

For each active tmux session that matches a known task:

```bash
# Peek at last 30 lines of output
ssh mac-mini "tmux capture-pane -t <tmux_session> -p 2>/dev/null | tail -30"
```

### Step 4: Check Worker task manifests

```bash
ssh mac-mini "ls -t ~/.claude-fleet/tasks/*.json 2>/dev/null | head -10"
```

For each task, read the JSON to get the Worker's view of status (it may have updated to `running`, `completed`, `failed`, or `blocked`).

### Step 5: Check GitHub for Worker PRs

```bash
gh pr list --search "head:worker/" --state open --json number,title,headRefName,url,createdAt
```

### Step 6: Present the dashboard

Format the output as a clear status table:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WORKER STATUS DASHBOARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Active tasks:
  [RUNNING]   qa-auth-flow        | worker/qa-auth-flow-20260319    | 42m
              Last: "Running test 32/47..."

  [BLOCKED]   build-sim-engine    | worker/build-sim-20260319       | 1h 15m
              Reason: "Missing database config for integration tests"

Completed tasks:
  [DONE]      test-coverage       | worker/test-coverage-20260319   | 2h 3m
              PR #42: "worker: expand test coverage to 85%"

Failed tasks:
  [FAILED]    deploy-staging      | worker/deploy-staging-20260319  | 18m
              Error: "Docker build failed — missing Dockerfile"

Open PRs from Worker:
  #42  worker: expand test coverage to 85%  (worker/test-coverage-20260319)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 7: Offer actions

Based on the dashboard:
- If there are completed PRs: "Run `/worker-review` to review and merge."
- If there are blocked tasks: Show the blocker and ask if the user wants to unblock or cancel.
- If there are failed tasks: Offer to show the error log or re-dispatch.
- If there are running tasks: "Still working. Check back later or peek at the log."

## Quick Peek Mode

If the user says `/worker-status <task-slug>`, show only that task's status plus the last 50 lines of its tmux output.

```bash
ssh mac-mini "tmux capture-pane -t claude-<task-slug> -p 2>/dev/null | tail -50"
```
