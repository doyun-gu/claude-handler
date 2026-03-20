# /fleet — Cross-project fleet dashboard

Commander role. Shows bird's-eye view of all projects, Worker tasks, and sync state.

## Steps

**1. Read config.** Load `~/.claude-fleet/machine-role.conf` and `~/.claude-fleet/projects.json`. If either is missing, stop: "Fleet not set up. Run `~/.claude/setup-fleet.sh` first."

**2. Check sync state.** For each project, run `git rev-parse --short HEAD`, `git branch --show-current`, and `git status --porcelain | wc -l` locally and via `ssh mac-mini`. Note: NOT_CLONED if the directory doesn't exist.

**3. Check tasks.** Read `~/.claude-fleet/tasks/*.json` locally and on Mac Mini. Group by project and status.

**4. Check active sessions.** `ssh mac-mini "tmux list-sessions 2>/dev/null | grep '^claude-'"`.

**5. Check open Worker PRs.** For each project dir: `gh pr list --search "head:worker/" --state open --json number,title,headRefName`.

**6. Present dashboard.**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FLEET DASHBOARD                    <date>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROJECTS
  Name        MacBook Pro        Mac Mini           Sync
  ─────────── ────────────────── ────────────────── ────────
  <project>   <branch> (<sha>)   <branch> (<sha>)   IN SYNC / DIVERGED / NOT CLONED

WORKER TASKS
  Task        Project   Status    Branch             Age
  ─────────── ───────── ───────── ────────────────── ────
  <task-id>   <project> RUNNING   worker/<task>-...  <age>

ACTIVE SESSIONS (Mac Mini)
  <tmux-session>  (running)

OPEN WORKER PRs
  <project>  #<n>  "<title>"  (<branch>)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Omit sections with no data.

**7. Offer actions** based on state:
- Diverged/behind project → offer to pull
- NOT CLONED on Mac Mini → offer to clone
- Completed tasks with PRs → "Run `/worker-review`?"
- Running tasks → "Run `/worker-status <task>` for details."
- Blocked tasks → show blocker, offer to help

## Subcommands

- `/fleet sync` — For each project on both machines: `git fetch origin && git pull origin main`. Run submodule update if applicable.
- `/fleet clone-all` — For each NOT CLONED project on Mac Mini: `ssh mac-mini "git clone <url> <path> && cd <path> && git submodule update --init"`.
- `/fleet clean` — Archive completed task manifests older than 7 days.

To add a project: edit `~/.claude-fleet/projects.json` then `scp` it to Mac Mini.
