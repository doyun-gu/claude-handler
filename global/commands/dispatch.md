# /dispatch — Send a task to the Mac Mini Worker

You are the Commander (MacBook Pro). This command dispatches a long-running task to the Mac Mini Worker.

## How It Works

The Worker is a separate Claude Code session running on the Mac Mini via `worker-daemon.sh`. The daemon watches a task queue and runs tasks automatically — no human needed. When a task finishes, the daemon immediately picks up the next queued task.

**Two modes:**
- **Immediate** (default): SSH to Mac Mini, start a Claude session in tmux right now.
- **Queue** (`queue:true` or multiple tasks): Write task manifests with status `queued`. The worker daemon picks them up automatically.

If the worker daemon is running, prefer queue mode — it handles task chaining, logging, and review-queue updates automatically.

## Steps

### Step 0: Read fleet config

```bash
cat ~/.claude-fleet/machine-role.conf
```

If the file doesn't exist or MACHINE_ROLE is not `commander`, tell the user: "Fleet not set up. Run `~/.claude/setup-fleet.sh` first."

### Step 1: Resolve the project

First, read the project registry:

```bash
cat ~/.claude-fleet/projects.json
```

Determine the target project:
1. **If the user specifies a project** (e.g., `/dispatch @faradaysim ...` or `/dispatch project:phixty-com ...`): use that project from the registry.
2. **If inside a project directory**: match the current working directory name against the registry.
3. **If neither**: ask the user which project. Show the list from the registry.

If the project is not on the Mac Mini yet, clone it first:
```bash
ssh mac-mini "test -d <project_path> || git clone <repo_url> <project_path>"
```

### Step 2: Parse the task

The user's message after `/dispatch` is the task description. Extract:
- **task**: What to do (the full description)
- **project**: Resolved from Step 1
- **subdir**: If the task targets a submodule (e.g., `faradaysim-frontend`), note it
- **permission**: Default `dangerously-skip-permissions` (Worker is autonomous). If user says "plan" or "research", use `plan`.
- **budget**: Default `$5`. If user specifies a budget, use that.
- **base_branch**: Default `main`. If user specifies a branch, use that.
- **queue**: Default `false`. If user says "queue" or dispatches multiple tasks, set to `true`.

### Step 3: Generate task ID and branch name

```bash
TASK_SLUG="<slugified-3-4-word-summary>"
TASK_ID="$(date +%Y%m%d-%H%M%S)-${TASK_SLUG}"
BRANCH="worker/${TASK_SLUG}-$(date +%Y%m%d)"
TMUX_SESSION="claude-${TASK_SLUG}"
```

### Step 4: Write local task manifest

```bash
mkdir -p ~/.claude-fleet/tasks
cat > ~/.claude-fleet/tasks/${TASK_ID}.json << EOF
{
  "id": "${TASK_ID}",
  "slug": "${TASK_SLUG}",
  "branch": "${BRANCH}",
  "project_name": "<project_name>",
  "project_path": "<project_dir>",
  "subdir": "<subdir_or_null>",
  "dispatched_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "status": "<queued_or_dispatched>",
  "prompt": "<the full task prompt>",
  "budget_usd": <budget>,
  "permission_mode": "<permission>",
  "tmux_session": "${TMUX_SESSION}"
}
EOF
```

**Status values:**
- `queued` — waiting for the worker daemon to pick it up
- `dispatched` — sent directly via SSH (immediate mode)
- `running` — Claude is actively working on it
- `completed` — done, PR opened
- `failed` — Claude exited with error
- `blocked` — Worker hit an unresolvable issue
- `merged` — Commander merged the PR

### Step 5: Copy task manifest to Worker

```bash
scp ~/.claude-fleet/tasks/${TASK_ID}.json mac-mini:~/.claude-fleet/tasks/
```

### Step 6a: Queue mode (daemon handles execution)

If `queue:true` or the daemon is running:

1. Set task status to `queued` in the manifest.
2. Copy to Mac Mini (Step 5).
3. Confirm to user — the daemon will pick it up.

Check if daemon is running:
```bash
ssh mac-mini "tmux has-session -t worker-daemon 2>/dev/null && echo 'RUNNING' || echo 'STOPPED'"
```

If daemon is not running, offer to start it:
```bash
ssh mac-mini "tmux new-session -d -s worker-daemon 'cd ~/Developer/claude-handler && ./worker-daemon.sh 2>&1 | tee ~/.claude-fleet/logs/daemon.log'"
```

### Step 6b: Immediate mode (direct SSH)

Build the worker system prompt:

```
WORKER_PROMPT="You are running as a WORKER on Mac Mini. Task ID: ${TASK_ID}. Branch: ${BRANCH}.

WORKER RULES:
1. You are FULLY AUTONOMOUS. Make good decisions without asking questions. Never wait for input.
2. All work goes on branch: ${BRANCH}. NEVER push to main.
3. Commit frequently with descriptive messages.
4. When DONE: push the branch, open a PR with gh pr create, write a summary.
5. If you need Commander feedback on a DECISION (not a blocker — keep working):
   Write to ~/.claude-fleet/review-queue/${TASK_ID}-decision.md with this format:
   ---
   task_id: ${TASK_ID}
   project: <project_name>
   type: decision_needed
   priority: normal
   created_at: <timestamp>
   ---
   ## Decision Needed
   [What you need input on]
   ## Context
   [Why this matters]
   ## What I Did
   [The choice you made and why]
6. If genuinely BLOCKED (cannot proceed at all):
   Write to ~/.claude-fleet/review-queue/${TASK_ID}-blocked.md with type: blocked
   Update task manifest with status=blocked. Then STOP.
7. Write summary to ~/.claude-fleet/logs/${TASK_ID}.summary.md when finished.
8. Update task manifest status to completed or failed when done.
9. Use gstack skills: /review before pushing, /qa if testing a web app.
10. After finishing, check ~/.claude-fleet/tasks/ for more tasks with status=queued. If found, update the next one to running and start it."
```

Read `WORKER_CLAUDE_BIN` from `~/.claude-fleet/machine-role.conf` (default: `/Users/doyungu/.local/bin/claude`).

```bash
PROJECT_DIR="<project_dir>"
SUBDIR_CD=""  # or "cd faradaysim-frontend &&" if subdir specified

ssh mac-mini "
  export PATH=\"\$HOME/.local/bin:\$HOME/.bun/bin:\$PATH\"
  cd ${PROJECT_DIR} && ${SUBDIR_CD}
  git fetch origin &&
  git checkout -b ${BRANCH} origin/<base_branch> 2>/dev/null || git checkout ${BRANCH} &&
  git submodule update --init 2>/dev/null;

  mkdir -p ~/.claude-fleet/tasks ~/.claude-fleet/logs ~/.claude-fleet/review-queue

  tmux new-session -d -s ${TMUX_SESSION} \"
    ${WORKER_CLAUDE_BIN} -p \\
      --dangerously-skip-permissions \\
      --max-turns 200 \\
      --append-system-prompt '${WORKER_PROMPT}' \\
      '<the task prompt>' \\
      2>&1 | tee ~/.claude-fleet/logs/${TASK_ID}.log;
    echo TASK_COMPLETE
  \"
"
```

### Step 7: Confirm dispatch

After SSH succeeds, tell the user:

```
Dispatched to Mac Mini:
  Task:    <task description summary>
  Branch:  <branch>
  Mode:    <queue | immediate>
  Budget:  $<budget>

Worker will:
  ✓ Build autonomously (no permission prompts)
  ✓ Push branch + open PR when done
  ✓ Log decisions to review queue
  ✓ Pick up next queued task automatically

Check progress: /worker-status
Review when done: /worker-review
```

## Multi-Task Dispatch

The user can dispatch multiple tasks at once. Parse each task and create separate manifests:

```
/dispatch @faradaysim queue budget:20
1. Build power system engine with Y-bus, Newton-Raphson solver, IEEE 14-bus validation
2. Add REST API endpoints for power flow and dynamic phasor simulation
3. Write comprehensive Google Test suite for the power system engine
```

For multi-task dispatch:
- Create one manifest per task, all with status `queued`
- Number the slugs: `ieee-bus-engine`, `powerflow-api`, `powersys-tests`
- Copy all manifests to Mac Mini
- Ensure daemon is running
- The daemon processes them in order (oldest queued first)

## Error Handling

- If SSH fails: Tell the user "Cannot reach Mac Mini. Check Tailscale connection."
- If branch already exists: Append a counter (e.g., `worker/qa-auth-20260319-2`)
- If Claude CLI not found on Worker: Tell user to install it on Mac Mini
- If daemon is not running and user wants queue mode: Offer to start it via SSH

## Examples

User: `/dispatch full-perms budget:20 Build the IEEE 14-bus power system engine with Newton-Raphson solver`
- project: auto-detected from cwd (faradaysim)
- slug: `ieee-bus-engine`
- permission: `dangerously-skip-permissions`, budget: `$20`
- mode: immediate

User: `/dispatch @faradaysim queue budget:30` then lists 3 tasks
- Creates 3 queued task manifests, daemon runs them sequentially

User: `/dispatch @phixty-com Rebuild the landing page with new design system`
- project: phixty-com (explicit)
- slug: `rebuild-landing`
- mode: immediate (single task, no queue keyword)
