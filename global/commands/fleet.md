# /fleet — Cross-project fleet dashboard

You are the Commander (MacBook Pro). This command shows a bird's-eye view of all projects, all Worker tasks, and the sync state across both machines.

## Steps

### Step 1: Read fleet config and project registry

```bash
cat ~/.claude-fleet/machine-role.conf
cat ~/.claude-fleet/projects.json
```

If either file is missing, tell the user: "Fleet not set up. Run `~/.claude/setup-fleet.sh` first."

### Step 2: Check sync state for each project

For each project in the registry, check both machines:

```bash
# Local (MacBook Pro)
for project in $(python3 -c "import json; [print(p['name']) for p in json.load(open('$HOME/.claude-fleet/projects.json'))['projects']]"); do
  PROJECT_DIR="$HOME/Developer/$project"
  if [ -d "$PROJECT_DIR/.git" ]; then
    cd "$PROJECT_DIR"
    LOCAL_HEAD=$(git rev-parse --short HEAD 2>/dev/null)
    LOCAL_BRANCH=$(git branch --show-current 2>/dev/null)
    LOCAL_DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    echo "$project|local|$LOCAL_BRANCH|$LOCAL_HEAD|dirty:$LOCAL_DIRTY"
  else
    echo "$project|local|NOT_CLONED|-|-"
  fi
done
```

```bash
# Remote (Mac Mini)
ssh mac-mini "
  for project in \$(python3 -c \"import json; [print(p['name']) for p in json.load(open('\$HOME/.claude-fleet/projects.json'))['projects']]\"); do
    PROJECT_DIR=\"\$HOME/Developer/\$project\"
    if [ -d \"\$PROJECT_DIR/.git\" ]; then
      cd \"\$PROJECT_DIR\"
      REMOTE_HEAD=\$(git rev-parse --short HEAD 2>/dev/null)
      REMOTE_BRANCH=\$(git branch --show-current 2>/dev/null)
      REMOTE_DIRTY=\$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
      echo \"\$project|remote|\$REMOTE_BRANCH|\$REMOTE_HEAD|dirty:\$REMOTE_DIRTY\"
    else
      echo \"\$project|remote|NOT_CLONED|-|-\"
    fi
  done
"
```

### Step 3: Check all Worker tasks

```bash
ls -t ~/.claude-fleet/tasks/*.json 2>/dev/null
```

Read each task manifest and group by project and status.

Also check Mac Mini for tasks the Commander doesn't know about:
```bash
ssh mac-mini "ls -t ~/.claude-fleet/tasks/*.json 2>/dev/null"
```

### Step 4: Check active tmux sessions on Worker

```bash
ssh mac-mini "tmux list-sessions 2>/dev/null | grep '^claude-' || echo 'No active sessions'"
```

### Step 5: Check open Worker PRs across all repos

```bash
for project in $(python3 -c "import json; [print(p['name']) for p in json.load(open('$HOME/.claude-fleet/projects.json'))['projects']]"); do
  cd "$HOME/Developer/$project" 2>/dev/null && gh pr list --search "head:worker/" --state open --json number,title,headRefName 2>/dev/null
done
```

### Step 6: Present the dashboard

Format output as:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FLEET DASHBOARD                             2026-03-19
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROJECTS
  Project          MacBook Pro          Mac Mini             Sync
  ───────          ───────────          ────────             ────
  faradaysim       main (989a466)       main (989a466)       IN SYNC
  claude-handler   main (f10a054)       main (f10a054)       IN SYNC
  phixty-com       main (abc1234)       main (abc1234)       IN SYNC
  your-project      main (def5678)       NOT CLONED           ---
  study-with-claude main (ghi9012)      main (ghi9012)       IN SYNC

WORKER TASKS
  Task                    Project         Status      Branch                    Age
  ────                    ───────         ──────      ──────                    ───
  qa-auth-flow            faradaysim      RUNNING     worker/qa-auth-20260319   42m
  rebuild-landing         phixty-com      COMPLETED   worker/rebuild-20260319   2h
  (no failed or blocked tasks)

ACTIVE SESSIONS (Mac Mini)
  claude-qa-auth-flow     (running)

OPEN WORKER PRs
  phixty-com  #12  "worker: rebuild landing page"   (worker/rebuild-20260319)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 7: Offer actions

Based on the dashboard state:

- **Out of sync projects**: "faradaysim is behind on Mac Mini. Pull? (y/n)"
- **NOT CLONED projects**: "your-project not on Mac Mini. Clone it? (y/n)"
- **Completed tasks with PRs**: "1 Worker PR ready for review. Run `/worker-review`?"
- **Running tasks**: "1 task running. Run `/worker-status qa-auth-flow` for details."
- **Blocked tasks**: Show blocker and offer to help unblock.

## Quick Commands

- `/fleet` — Full dashboard (default)
- `/fleet sync` — Pull all projects on both machines to latest
- `/fleet clone-all` — Clone any missing projects on Mac Mini
- `/fleet clean` — Archive completed tasks older than 7 days

### /fleet sync

For each project in the registry, on both machines:
```bash
git fetch origin && git pull origin main 2>/dev/null
```

For submodule projects:
```bash
git submodule update --init --recursive
```

### /fleet clone-all

For each project in the registry that doesn't exist on Mac Mini:
```bash
ssh mac-mini "git clone <repo_url> <project_path> && cd <project_path> && git submodule update --init"
```

## Managing Projects

To add a new project to the registry, edit `~/.claude-fleet/projects.json` and copy it to Mac Mini:
```bash
scp ~/.claude-fleet/projects.json mac-mini:~/.claude-fleet/projects.json
```

Or tell the user: "Add the project to `~/.claude-fleet/projects.json` and I'll sync it."
