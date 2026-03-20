# /dispatch — Send a task to the Mac Mini Worker

Dispatch a long-running task to the Worker (Mac Mini). The Worker runs autonomously via `worker-daemon.sh` — no human input needed.

**Modes:**
- **Immediate** (default): SSH to Mac Mini, start Claude in tmux now.
- **Queue** (`queue:true` or multiple tasks): Write manifest with `status: queued`; daemon picks it up automatically.

Prefer queue mode if the daemon is running — it handles chaining, logging, and review-queue updates.

## Steps

### Step 0: Verify commander role

Read `~/.claude-fleet/machine-role.conf`. If missing or not `commander`, tell user: "Fleet not set up. Run `~/.claude/setup-fleet.sh` first."

### Step 1: Resolve project

Read `~/.claude-fleet/projects.json`. Determine target:
1. Explicit (`@project` or `project:name`) → use registry entry
2. cwd name matches registry → use that
3. Neither → ask user, show registry list

If project not on Mac Mini yet: `ssh mac-mini "test -d <path> || git clone <repo> <path>"`

### Step 2: Parse task args

From the user's message, extract:
- `task` — full description
- `project` — from Step 1
- `subdir` — if targeting a submodule
- `permission` — `dangerously-skip-permissions` (default) or `plan` if research/plan task
- `budget` — default `$5`
- `base_branch` — default `main`
- `queue` — `false` unless user says "queue" or dispatches multiple tasks

### Step 3: Generate IDs

```
TASK_SLUG = slugified 3-4 word summary
TASK_ID   = YYYYMMDD-HHMMSS-{TASK_SLUG}
BRANCH    = worker/{TASK_SLUG}-YYYYMMDD
TMUX_SESSION = claude-{TASK_SLUG}
```

### Step 4: Write task manifest

Write `~/.claude-fleet/tasks/${TASK_ID}.json` with fields: `id`, `slug`, `branch`, `project_name`, `project_path`, `subdir`, `dispatched_at`, `status` (`queued` or `dispatched`), `prompt`, `budget_usd`, `permission_mode`, `tmux_session`.

Status lifecycle: `queued` → `running` → `completed` / `failed` / `blocked`; `merged` after Commander review.

### Step 5: Copy manifest to Worker

`scp ~/.claude-fleet/tasks/${TASK_ID}.json mac-mini:~/.claude-fleet/tasks/`

### Step 6a: Queue mode

Set status `queued`, copy manifest (Step 5), confirm to user. Check daemon:

`ssh mac-mini "tmux has-session -t worker-daemon 2>/dev/null && echo RUNNING || echo STOPPED"`

If stopped, offer to start: `ssh mac-mini "tmux new-session -d -s worker-daemon 'cd ~/Developer/claude-handler && ./worker-daemon.sh 2>&1 | tee ~/.claude-fleet/logs/daemon.log'"`

### Step 6b: Immediate mode

Read `WORKER_CLAUDE_BIN` from `~/.claude-fleet/machine-role.conf` (default: `/Users/doyungu/.local/bin/claude`).

The worker system prompt rules are defined in `worker-daemon.sh` — use the same rules: autonomous operation, work on `${BRANCH}` only, commit frequently, push + open PR when done, write decision/blocked files to `~/.claude-fleet/review-queue/`, write summary to `logs/${TASK_ID}.summary.md`, update manifest status when done, use `/review` before pushing.

SSH to Mac Mini, set up PATH, `cd` to project (+ subdir if set), checkout branch (`-b ${BRANCH} origin/${base_branch}` or existing), run submodule update, then start tmux session running `${WORKER_CLAUDE_BIN} -p --dangerously-skip-permissions --max-turns 200 --append-system-prompt '<worker rules>' '<task prompt>' | tee ~/.claude-fleet/logs/${TASK_ID}.log`.

### Step 7: Confirm

Report to user:
```
Dispatched: <summary> | Branch: <branch> | Mode: <queue|immediate> | Budget: $<n>
Check: /worker-status | Review: /worker-review
```

## Multi-Task Dispatch

When user lists multiple tasks (numbered), create one manifest per task, all `status: queued`, with numbered slugs. Copy all to Mac Mini, ensure daemon is running. Daemon processes oldest-queued-first.

## Error Handling

- SSH fails → "Cannot reach Mac Mini. Check Tailscale."
- Branch exists → append counter (`-2`, `-3`)
- Claude CLI missing on Worker → tell user to install it
