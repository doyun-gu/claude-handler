# /dispatch — Send a task to the Mac Mini Worker

You are the Commander (MacBook Pro). This command dispatches a long-running task to the Mac Mini Worker.

## How It Works

The Worker is a separate Claude Code session running headless on the Mac Mini. It works autonomously on a dedicated branch, pushes results, and opens a PR when done.

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
- **permission**: Default `auto`. If user says "full-perms" or "overnight", use `dangerously-skip-permissions`. If user says "plan" or "research", use `plan`.
- **budget**: Default `$5`. If user specifies a budget, use that.
- **base_branch**: Default `main`. If user specifies a branch, use that.

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
  "status": "dispatched",
  "prompt": "<the full task prompt>",
  "budget_usd": <budget>,
  "permission_mode": "<permission>",
  "tmux_session": "${TMUX_SESSION}"
}
EOF
```

### Step 5: Prepare the Worker system prompt

Build this string (do NOT include backticks inside it — escape properly):

```
WORKER_PROMPT="You are running as a WORKER on Mac Mini. Task ID: ${TASK_ID}. Branch: ${BRANCH}.

WORKER RULES:
1. You are autonomous. Make good decisions without asking questions.
2. All work goes on branch: ${BRANCH}. NEVER push to main.
3. Commit frequently with descriptive messages.
4. When DONE: push the branch, open a PR with gh pr create, write a summary.
5. If BLOCKED: update ~/.claude-fleet/tasks/${TASK_ID}.json with status=blocked and describe why.
6. Write a completion summary to ~/.claude-fleet/logs/${TASK_ID}.summary.md when finished.
7. Update ~/.claude-fleet/tasks/${TASK_ID}.json status to completed or failed when done.
8. Use gstack skills as appropriate: /review before pushing, /qa if testing needed."
```

### Step 6: Dispatch via SSH

Read `WORKER_CLAUDE_BIN` from `~/.claude-fleet/machine-role.conf` (default: `/Users/doyungu/.local/bin/claude`).

```bash
# Determine project path and optional subdir cd
PROJECT_DIR="<project_dir>"
SUBDIR_CD=""  # or "cd faradaysim-frontend &&" if subdir specified

ssh mac-mini "
  export PATH=\"\$HOME/.local/bin:\$HOME/.bun/bin:\$PATH\"
  cd ${PROJECT_DIR} && ${SUBDIR_CD}
  git fetch origin &&
  git checkout -b ${BRANCH} origin/<base_branch> &&
  git submodule update --init 2>/dev/null;

  mkdir -p ~/.claude-fleet/tasks ~/.claude-fleet/logs

  tmux new-session -d -s ${TMUX_SESSION} \"
    ${WORKER_CLAUDE_BIN} -p \\
      --permission-mode <permission> \\
      --max-turns 200 \\
      --append-system-prompt '${WORKER_PROMPT}' \\
      '<the task prompt>' \\
      2>&1 | tee ~/.claude-fleet/logs/${TASK_ID}.log;
    echo TASK_COMPLETE
  \"
"
```

**Important:** If `--permission-mode` is `dangerously-skip-permissions`, use the flag `--dangerously-skip-permissions` instead.

### Step 7: Confirm dispatch

After SSH succeeds, tell the user:

```
Dispatched to Mac Mini:
  Task:    <task description summary>
  Branch:  <branch>
  Session: <tmux_session>
  Budget:  $<budget>
  Mode:    <permission>

Check progress: /worker-status
Review when done: /worker-review
```

### Step 8: Copy task manifest to Worker

```bash
scp ~/.claude-fleet/tasks/${TASK_ID}.json mac-mini:~/.claude-fleet/tasks/
```

## Error Handling

- If SSH fails: Tell the user "Cannot reach Mac Mini. Check Tailscale connection."
- If branch already exists: Append a counter (e.g., `worker/qa-auth-20260319-2`)
- If Claude CLI not found on Worker: Tell user to install it on Mac Mini

## Examples

User: `/dispatch Run /qa on the frontend auth flow. Test login, signup, password reset.`
- project: auto-detected from cwd (faradaysim)
- slug: `qa-auth-flow`
- subdir: `faradaysim-frontend`
- permission: `auto`, budget: `$5`

User: `/dispatch @phixty-com full-perms budget:10 Rebuild the landing page with new design system`
- project: phixty-com (explicit)
- slug: `rebuild-landing`
- permission: `dangerously-skip-permissions`, budget: `$10`

User: `/dispatch full-perms budget:20 Build the power flow visualization module with Newton-Raphson solver`
- project: auto-detected from cwd
- slug: `powerflow-viz`
- permission: `dangerously-skip-permissions`, budget: `$20`

User: `/dispatch @faradaysim plan Research how PSCAD handles transient simulation and document the approach`
- project: faradaysim (explicit, can dispatch from any directory)
- slug: `research-pscad`
- permission: `plan`, budget: `$3`
