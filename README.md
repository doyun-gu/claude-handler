# claude-handler

A framework that turns [Claude Code](https://docs.anthropic.com/en/docs/claude-code) into a Technical Co-Founder — and optionally runs a fleet of autonomous AI workers across multiple machines.

**Single machine:** Install in 30 seconds. Claude gets a product-focused persona, smart project onboarding, and session continuity across every project.

**Two machines:** Add a Worker (Mac Mini, server, any always-on machine). Dispatch heavy tasks from your laptop. The Worker runs Claude autonomously, opens PRs, sends email notifications, and auto-heals crashed services — while you sleep.

## What You Get

| Feature | Description |
|---------|-------------|
| **Technical Co-Founder persona** | Claude pushes back on bad ideas, thinks product-first, ships incrementally |
| **Smart onboarding** | Auto-detects tech stack, git history, file structure — only asks what it can't figure out |
| **Personalisation** | `/cofounder` runs an interview, saves your profile. Claude remembers your preferences |
| **CLAUDE.md generation** | Creates per-project context files so future sessions start instantly |
| **Dual-machine fleet** | Commander dispatches tasks, Worker executes autonomously |
| **Process supervision** | LaunchAgent keeps services alive across reboots |
| **Health checking** | Auto-detects crashes, scans logs, creates bug database, auto-heals known issues |
| **Email notifications** | Gmail alerts for task completion/failure with reply-to-action |
| **Notion integration** | 10 slash commands for documentation management |

## Architecture

```mermaid
graph TB
    subgraph Commander["Commander (Laptop)"]
        User([You]) --> Claude[Claude Code]
        Claude --> Dispatch["/dispatch"]
        Claude --> Review["/worker-review"]
        Claude --> Fleet["/fleet"]
    end

    subgraph Worker["Worker (Server / Mac Mini)"]
        Supervisor[Fleet Supervisor<br/>launchd] --> Daemon[Worker Daemon]
        Supervisor --> Health[Health Checker]
        Supervisor --> Dashboard[Fleet Dashboard<br/>:3003]
        Daemon --> |picks up tasks| Queue[(Task Queue<br/>~/.claude-fleet/tasks/)]
        Daemon --> |runs| WorkerClaude[Claude Code<br/>autonomous]
        WorkerClaude --> |opens| PR[GitHub PR]
        Health --> |auto-heals| Services[Project Services]
        Health --> |logs| BugDB[(Bug Database)]
    end

    Dispatch --> |SSH + JSON| Queue
    PR --> |review| Review
    Queue --> |status| Fleet

    style Commander fill:#f0f9ff,stroke:#3b82f6
    style Worker fill:#f0fdf4,stroke:#22c55e
```

## Process Supervision

The Worker machine uses macOS LaunchAgent to keep everything running:

```mermaid
graph LR
    launchd[launchd<br/>on boot] --> Supervisor[fleet-supervisor.sh<br/>every 30s]
    Supervisor --> |ensures alive| WD[worker-daemon<br/>tmux session]
    Supervisor --> |ensures alive| HC[demo-health<br/>tmux session]
    Supervisor --> |ensures alive| DB[fleet-dashboard<br/>tmux session]
    WD --> |runs tasks| Claude[Claude Code]
    HC --> |monitors| Services[Your Services]
    HC --> |auto-heals| Services

    style launchd fill:#fef3c7,stroke:#f59e0b
    style Supervisor fill:#dbeafe,stroke:#3b82f6
```

## Task Lifecycle

From dispatch to merged PR:

```mermaid
stateDiagram-v2
    [*] --> Queued: /dispatch
    Queued --> Running: daemon picks up
    Running --> Completed: Claude finishes
    Running --> Failed: error/timeout
    Completed --> PR_Open: git push + gh pr create
    PR_Open --> Reviewed: /worker-review
    Reviewed --> Merged: approve
    Reviewed --> Fix: request changes
    Fix --> Queued: new task
    Failed --> Queued: retry
    Merged --> [*]
```

## Worker Daemon Architecture

The Worker Daemon is the autonomous engine that processes tasks without human intervention. It manages parallel execution, freeze windows, and async computation.

### Task Processing Flow

```mermaid
flowchart TB
    subgraph Daemon["worker-daemon.sh (main loop)"]
        Poll["Poll ~/.claude-fleet/tasks/<br/>every 5-30s"] --> Scan{Scan for<br/>queued tasks}
        Scan --> |found| Freeze{Project<br/>frozen?}
        Freeze --> |yes| Skip["Skip — wait for<br/>freeze window to end"]
        Freeze --> |no| Running{Project already<br/>has running task?}
        Running --> |yes| Skip2["Skip — 1 task<br/>per project"]
        Running --> |no| Launch["Launch task<br/>in background"]
        Scan --> |none| Idle{Idle timer<br/>started?}
        Idle --> |"> 30 min"| Backlog["Check backlog<br/>for maintenance tasks"]
        Idle --> |"< 30 min"| Wait["Sleep and re-poll"]
    end

    Launch --> TaskFlow

    subgraph TaskFlow["Task Execution (per task)"]
        Checkout["git checkout -b worker/task-name"] --> ReadPrompt["Read task prompt<br/>from manifest JSON"]
        ReadPrompt --> RunClaude["Run Claude Code<br/>--dangerously-skip-permissions<br/>--max-turns 200"]
        RunClaude --> Done{Exit code?}
        Done --> |0| Success["status: completed<br/>Push branch + open PR"]
        Done --> |non-0| Failure["status: failed<br/>Write error to review queue"]
        Success --> AutoMerge{Slug contains<br/>bug/fix/docs?}
        AutoMerge --> |yes| Merge["Auto-merge PR"]
        AutoMerge --> |no| ReviewQueue["Add to review queue<br/>for Commander"]
    end

    style Daemon fill:#f0fdf4,stroke:#22c55e
    style TaskFlow fill:#f0f9ff,stroke:#3b82f6
```

### Parallel Execution Model

The daemon runs **one task per project** in parallel. Multiple projects can execute simultaneously, but tasks for the same project queue behind each other.

```mermaid
gantt
    title Parallel Task Execution (example)
    dateFormat HH:mm
    axisFormat %H:%M

    section DPSpice
        N-1 contingency + exports    :active, dp1, 16:25, 60min
        Unified editor + AI panel    :dp2, after dp1, 45min
        Control blocks               :dp3, after dp2, 60min

    section claude-handler
        Dashboard polish             :ch1, 16:25, 20min
        Public-ready docs            :ch2, after ch1, 15min

    section example-project
        Design system                :dy1, 16:25, 15min
```

### Async Computation (Rule 11)

Worker Claude uses `run_in_background` for long-running computations instead of blocking. This dramatically reduces idle time during test suites and simulations.

```mermaid
sequenceDiagram
    participant C as Claude Worker
    participant BG as Background Process
    participant FS as Filesystem

    Note over C: ❌ Old behavior (blocking)
    C->>C: Write solver code
    C->>C: pytest (wait 5 min...)
    C->>C: Read results
    C->>C: Write next feature

    Note over C,BG: ✅ New behavior (async)
    C->>C: Write solver code
    C->>BG: run_in_background: pytest
    C->>C: Write next feature (no wait)
    C->>C: Write docs
    BG-->>FS: Results ready
    C->>FS: Check test results
    C->>C: Fix failures if any
    C->>C: Commit all
```

### Freeze Windows

Events in `~/.claude-fleet/events.json` can freeze specific projects during critical periods (demos, deployments):

```json
[{
  "title": "Supervisor Meeting",
  "freeze_projects": ["DPSpice-com"],
  "freeze_from": "2026-03-20T11:00:00Z",
  "freeze_until": "2026-03-20T12:15:00Z"
}]
```

During a freeze, the daemon skips queued tasks for that project. Tasks for other projects continue normally.

### Task Manifest Format

Each task is a JSON file in `~/.claude-fleet/tasks/`:

```json
{
  "id": "20260320-154351-unified-editor-ai-panel",
  "slug": "unified-editor-ai-panel",
  "branch": "worker/unified-editor-ai-panel-20260320",
  "project_name": "DPSpice-com",
  "project_path": "/Users/you/Developer/my-project",
  "status": "queued",
  "prompt": "Implement feature X...",
  "budget_usd": 20,
  "permission_mode": "dangerously-skip-permissions",
  "dispatched_at": "2026-03-20T15:43:51Z"
}
```

**Status lifecycle:** `queued` → `running` → `completed` / `failed` / `blocked` → `merged`

### Review Queue

When tasks complete, the daemon writes to `~/.claude-fleet/review-queue/`:

| File Pattern | Meaning | Commander Action |
|---|---|---|
| `*-completed.md` | PR ready for review | `/worker-review` |
| `*-failed.md` | Task crashed | Check logs, retry |
| `*-blocked.md` | Worker stuck | Investigate, unblock |
| `*-decision.md` | Worker made a choice, wants confirmation | Review and confirm |

Auto-mergeable tasks (slugs containing `bug`, `fix`, `docs`, `sync`, etc.) skip the review queue and merge directly.

## Preview Isolation (Worktree)

If your Worker runs a preview server, use a **git worktree** so the daemon can't overwrite it by switching branches:

```bash
# Create isolated worktree for preview
cd ~/Developer/my-project
git worktree add ~/Developer/my-project-preview <branch>
cd ~/Developer/my-project-preview && npm run dev -- -p 3002
```

The daemon freely switches branches in the main repo. The worktree is a separate directory with its own checkout — completely isolated.

## PR Merge Ordering

When multiple worker PRs exist, merge them **one at a time** and rebase each onto updated main before merging. Never merge multiple PRs simultaneously — later PRs can overwrite earlier ones if they branch from the same base.

```mermaid
flowchart LR
    A["Merge PR #1"] --> R["Rebase PR #2"] --> B["Merge PR #2"] --> R2["Rebase PR #3"] --> C["Merge PR #3"]
```

## Post-Push Sync Protocol

Every `git push` from the Commander must sync the Worker immediately. The Worker runs live services from local repos — stale code means a broken dashboard, preview, or API.

```mermaid
sequenceDiagram
    participant CMD as Commander
    participant GH as GitHub
    participant WRK as Worker

    CMD->>GH: git push origin main
    CMD->>WRK: ssh worker "cd ~/Developer/<repo> && git pull"

    alt Service runs from this repo
        CMD->>WRK: Restart affected tmux session
    end

    Note over CMD,WRK: Never leave the Worker behind GitHub
```

If your Worker runs services from the repo (dashboard, preview, API), restart the relevant tmux session after syncing.

## Quick Start

### Single Machine (Commander only)

```bash
git clone https://github.com/doyun-gu/claude-handler.git ~/claude-handler
cd ~/claude-handler
./install.sh    # Choose "Commander" when prompted
```

Restart Claude Code. You'll see:

> *Tip: run `/cofounder` to personalise how I work with you.*

Run `/cofounder` for a 2-minute interview that configures Claude's explanation depth, pushback level, and tool preferences.

### Two Machines (Commander + Worker)

```mermaid
graph LR
    A[1. Clone on both machines] --> B[2. Run install.sh]
    B --> C{Choose role}
    C --> |Laptop| D[Commander]
    C --> |Server| E[Worker]
    D --> F[3. Set up SSH to Worker]
    E --> G[3. Install LaunchAgent]
    F --> H[4. /dispatch from Claude]
    G --> H

    style D fill:#f0f9ff,stroke:#3b82f6
    style E fill:#f0fdf4,stroke:#22c55e
```

**On your laptop (Commander):**
```bash
git clone https://github.com/doyun-gu/claude-handler.git ~/claude-handler
cd ~/claude-handler
./install.sh    # Choose "Commander"
```

**On your server (Worker):**
```bash
git clone https://github.com/doyun-gu/claude-handler.git ~/claude-handler
cd ~/claude-handler
./install.sh    # Choose "Worker", install LaunchAgent
```

**Connect them** — add to `~/.ssh/config` on Commander:
```
Host worker
  HostName <worker-ip>
  User <username>
```

**Dispatch your first task:**
```
> /dispatch
"Add comprehensive tests for the auth module"
```

The Worker picks it up, runs Claude autonomously, opens a PR, and notifies you by email.

## Setup Flow

```
                              clone repo
                                  │
                            ./install.sh
                                  │
                        ┌─────────┴─────────┐
                        │                     │
                   Commander              Worker
                        │                     │
                  Claude Code           LaunchAgent
                  /cofounder            fleet-supervisor
                  /dispatch ──────────► worker-daemon
                  /worker-review ◄──── health-checker
                        │             fleet-dashboard
                     SSH setup
                        │
                   Ready to go
```

## Commands

### Core

| Command | Description |
|---------|------------|
| `/cofounder` | Personalisation interview — saves to `~/.claude/user-profile.md` |
| `/startup` | Re-run session orientation. Refreshes context |
| `/onboard` | Force full onboarding (regenerate CLAUDE.md) |
| `/ready2modify` | Sync repo on a new machine |
| `/workdone` | Save and push before switching machines |

### Fleet (Commander)

| Command | Description |
|---------|------------|
| `/fleet` | Cross-project dashboard — tasks, PRs, sync state |
| `/dispatch` | Send a task to the Worker |
| `/dispatch @project` | Target a specific project |
| `/worker-status` | Check Worker task progress |
| `/worker-review` | Review and merge completed Worker PRs |

### Notion (optional)

| Command | Description |
|---------|------------|
| `/notion-sync` | Sync Notion ↔ local markdown |
| `/notion-progress` | Log git commits to Notion |
| `/notion-done` | End-of-session handoff |
| `/notion-status` | Status report from Notion |
| `/notion-decision` | Log a technical decision |
| `/notion-milestone` | Add/update a milestone |
| `/notion-doc` | Create a documentation page |
| `/notion-search` | Search the workspace |
| `/notion-review` | Audit docs for quality |
| `/notion-lecture` | Create a lecture note |

## Configuration

All config lives in `~/.claude-fleet/`. See `config.example/` for format reference.

| File | Purpose |
|------|---------|
| `machine-role.conf` | Commander or Worker role |
| `projects.json` | Registered projects and their services |
| `secrets/gmail.conf` | Gmail credentials for notifications |

### Email Notifications

The Worker sends styled HTML emails for task completions and failures. Reply to take action:

| Reply | Action |
|-------|--------|
| `merge` | Squash merge the PR |
| `fix: [description]` | Create a fix task |
| `skip` | Close PR, move on |
| `queue: [task]` | Queue a new task |

Setup: copy `config.example/gmail.conf.example` to `~/.claude-fleet/secrets/gmail.conf` and add your [Gmail App Password](https://myaccount.google.com/apppasswords).

### Projects Registry

Edit `~/.claude-fleet/projects.json` to register your projects. Each project can define services that the health checker monitors and auto-restarts:

```json
{
  "projects": [{
    "name": "my-app",
    "path": "~/Developer/my-app",
    "repo": "https://github.com/you/my-app.git",
    "services": [{
      "name": "api",
      "port": 8000,
      "start_cmd": "python -m uvicorn main:app --port 8000",
      "health_url": "http://localhost:8000/health"
    }]
  }]
}
```

## File Structure

```
claude-handler/
├── install.sh                 # Interactive installer (Commander/Worker)
├── install-launchd.sh         # Generate and install LaunchAgent
├── uninstall.sh               # Remove symlinks, restore backups
├── worker-daemon.sh           # Autonomous task runner
├── fleet-startup.sh           # Boot-time service launcher
├── fleet-supervisor.sh        # Process supervisor (keeps tmux alive)
├── demo-healthcheck.sh        # Service health + log scanning + auto-heal
├── fleet-notify.sh            # Gmail notifications + reply-to-action
├── fleet-brain.py             # Task scheduling + PR management
├── queue-manager.py           # Smart task queue with priorities
├── sync-to-macbook.sh         # Sync to a second machine
├── config.example/            # Example configs (safe to commit)
│   ├── projects.json.example
│   ├── machine-role.conf.example
│   └── gmail.conf.example
├── launchd/
│   ├── com.fleet.supervisor.plist           # Generated (gitignored)
│   └── com.fleet.supervisor.plist.template  # Template with __HOME__ markers
├── dashboard/
│   ├── api.py                 # FastAPI fleet dashboard backend
│   └── index.html             # Dashboard frontend
├── global/
│   ├── CLAUDE.md              # Core persona + startup protocol
│   └── commands/              # Slash commands (symlinked to ~/.claude/)
├── notion/                    # Notion integration (optional)
│   ├── commands/              # 10 Notion slash commands
│   ├── templates/             # Document format definitions
│   └── schemas/               # Database schemas
├── handoff/                   # Sleep/wake sync between machines
└── templates/
    └── project-claude-md.md   # CLAUDE.md generation template
```

## How It Works

Claude Code loads `~/.claude/CLAUDE.md` at the start of every session. This framework symlinks its own `CLAUDE.md` there, giving Claude a product-focused persona and smart onboarding protocol.

**Session flow:**

| Project State | What Happens |
|--------------|-------------|
| New (empty dir) | Full onboarding: asks product idea, target user, tech preferences |
| Existing (has code, no CLAUDE.md) | Auto-scans project, asks only unknowable things |
| Returning (has CLAUDE.md) | Reads it, says "Ready to work" |

**Worker flow:**

1. Commander runs `/dispatch "build feature X"`
2. Task JSON is created in `~/.claude-fleet/tasks/`
3. Worker daemon picks it up, creates a `worker/` branch
4. Claude runs autonomously (up to 200 turns)
5. Worker pushes branch, opens PR, writes summary
6. Commander gets notified, runs `/worker-review` to merge

## Customising

**Edit the persona:** Modify `global/CLAUDE.md` — changes apply instantly via symlink.

**Add commands:** Create `.md` files in `global/commands/` and re-run `./install.sh`.

**Notion setup:** See [notion/README.md](notion/README.md) for MCP server setup.

## Uninstall

```bash
./uninstall.sh
```

Removes symlinks and restores backups. Fleet data in `~/.claude-fleet/` is preserved.

## Author

Created by [Doyun Gu](https://github.com/doyun-gu)

## License

MIT — see [LICENSE](LICENSE)
