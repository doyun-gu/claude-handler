# Fleet Architecture

How the claude-handler fleet system orchestrates autonomous Claude Code sessions across multiple machines.

## Table of Contents

1. [System Overview](#system-overview)
2. [Task Lifecycle](#task-lifecycle)
3. [Data Architecture](#data-architecture)
4. [Security Model](#security-model)
5. [Failure Modes and Recovery](#failure-modes-and-recovery)
6. [Evaluator Pipeline](#evaluator-pipeline)
7. [Cost Model](#cost-model)

---

## System Overview

Star topology with single controller. Mac Mini is the hub — it owns the task queue, runs the daemon, and routes work to remote workers. Commander (MacBook) dispatches tasks and reviews PRs. Workers execute autonomously and never touch `main`.

```mermaid
flowchart TB
    subgraph Commander["MacBook Pro (Commander)"]
        User([User]) --> Dispatch["/dispatch"]
        Dispatch --> TaskDB1["task-db.py add\n(local tasks.db)"]
        Review["/worker-review"] --> Merge["gh pr merge"]
    end

    subgraph Controller["Mac Mini (Controller + Worker 1)"]
        Daemon["worker-daemon.sh\n(polls 30s)"] --> Brain["fleet-brain.py\n(scoring + routing)"]
        Brain --> Local["Local Claude\n(tmux session)"]
        Brain --> Route{"Route?"}
        Route -->|local| Local
        Route -->|remote| SSH["SSH to Dell XPS"]
        Local --> PR1["gh pr create"]
        Supervisor["fleet-supervisor.sh\n(launchd, 30s)"] -.->|restarts| Daemon
        Supervisor -.->|restarts| Health["demo-healthcheck.sh"]
        Supervisor -.->|restarts| Dashboard["Dashboard API\n(:3003)"]
        Backup["fleet-backup.sh"] -->|rsync| Commander
    end

    subgraph Remote["Dell XPS (Worker 2, WSL2)"]
        RemoteClaude["Claude Code\n(autonomous)"] --> PR2["gh pr create"]
    end

    Dispatch -->|"scp .prompt + .json\nssh task-db.py add"| Controller
    SSH -->|"Tailscale SSH"| Remote
    PR1 -->|GitHub| Review
    PR2 -->|GitHub| Review

    style Commander fill:#1a1a2e,stroke:#e0e0e0,color:#e0e0e0
    style Controller fill:#0f3460,stroke:#e0e0e0,color:#e0e0e0
    style Remote fill:#16213e,stroke:#e0e0e0,color:#e0e0e0
```

**Why star, not mesh:** One queue, one DB, one source of truth. Adding a machine = one SSH config line. The bottleneck is Claude API throughput, not local orchestration.

---

## Task Lifecycle

```mermaid
sequenceDiagram
    participant U as Commander
    participant MM as Mac Mini Daemon
    participant DB as tasks.db
    participant W as Worker (local or remote)
    participant GH as GitHub
    participant BK as MacBook Backup

    U->>MM: scp .prompt FIRST, then .json
    U->>DB: task-db.py add (local + remote)

    loop Every 30s
        MM->>DB: task-db.py claim (atomic)
        Note over DB: Filter: queued + deps met<br/>Order: priority DESC<br/>Limit: 1 per project<br/>Check: daily cost < budget
    end

    MM->>MM: route_task() — local or remote?
    alt Local execution
        MM->>W: Launch Claude in tmux
    else Remote execution
        MM->>W: SSH + launch Claude on Dell XPS
    end

    loop Every 60s while running
        MM->>DB: heartbeat (pid, log_size)
    end

    W->>GH: git push + gh pr create
    W->>MM: Exit code (0=success, !0=fail)
    MM->>DB: task-db.py status completed/failed
    MM->>MM: Write review-queue/{id}-completed.md
    MM->>BK: fleet-backup.sh (rsync to MacBook)

    U->>GH: /worker-review → gh pr merge --squash
```

**Status transitions:** `queued` → `running` → `completed`/`failed` → `merged` (after PR merge). Tasks can also be `blocked` (Worker writes to review queue) or `cancelled` (Commander intervention).

---

## Data Architecture

```mermaid
flowchart LR
    subgraph Primary["tasks.db (SQLite — source of truth)"]
        Tasks["tasks table\nid, slug, status, priority,\ndepends_on, cost_usd, route"]
        Cost["cost_log table\ntask_id, amount, timestamp"]
        HB["heartbeats table\npid, log_size, last_check"]
    end

    subgraph JSON["JSON Files (sync bridge)"]
        Manifest["tasks/*.json\n(metadata)"]
        Prompt["tasks/*.prompt\n(plain text)"]
        DispLog["dispatch-log/\n(immutable backup)"]
    end

    subgraph Dashboard["fleet.db (read replica)"]
        DashDB["sync_from_json()\nevery 30s"]
        API["FastAPI :3003"]
    end

    subgraph Backup["MacBook Backup"]
        BK["~/.claude-fleet/\nmac-mini-backup/"]
    end

    Primary -->|"daemon writes"| JSON
    JSON -->|"dashboard reads"| Dashboard
    Primary -->|"rsync daily"| Backup
    DispLog -->|"rsync"| Backup

    style Primary fill:#1a1a2e,stroke:#e0e0e0,color:#e0e0e0
    style JSON fill:#16213e,stroke:#e0e0e0,color:#e0e0e0
    style Dashboard fill:#0f3460,stroke:#e0e0e0,color:#e0e0e0
    style Backup fill:#1a1a2e,stroke:#e0e0e0,color:#e0e0e0
```

| Store | Location | Writer | Reader | Purpose |
|-------|----------|--------|--------|---------|
| `tasks.db` | Mac Mini | daemon, task-db.py | daemon, CLI | Source of truth for task state |
| `fleet.db` | Mac Mini | dashboard sync | FastAPI | Read-only replica for dashboard |
| `tasks/*.json` | Mac Mini | daemon, dispatch | dashboard, CLI | Human-readable manifests |
| `tasks/*.prompt` | Mac Mini | dispatch (scp) | daemon | Task instructions (plain text) |
| `dispatch-log/` | Both | dispatch | audit | Immutable backup of every dispatch |
| `review-queue/` | Mac Mini | daemon/worker | Commander startup | Async feedback channel |
| `bug-db.json` | Mac Mini | healthcheck | healthcheck | Recurring error tracker |

---

## Security Model

```mermaid
flowchart TB
    subgraph Trust1["Trust Boundary: User Machine"]
        MacBook["MacBook Pro\n(Commander)"]
    end

    subgraph Trust2["Trust Boundary: Fleet Network"]
        MiniCtrl["Mac Mini\n(Controller)"]
        DellWorker["Dell XPS\n(Worker)"]
    end

    subgraph External["External Services"]
        GitHub["GitHub\n(SSH keys per machine)"]
        Anthropic["Anthropic API\n(key in Claude config)"]
    end

    MacBook -->|"Tailscale SSH\n(identity-based)"| MiniCtrl
    MiniCtrl -->|"Tailscale SSH\n(ConnectTimeout=5s)"| DellWorker
    MacBook -.->|"no direct access"| DellWorker
    MiniCtrl -->|"SSH key"| GitHub
    DellWorker -->|"SSH key"| GitHub
    MacBook -->|"SSH key"| GitHub
    MiniCtrl -->|"API key"| Anthropic
    DellWorker -->|"API key"| Anthropic

    style Trust1 fill:#1a1a2e,stroke:#e0e0e0,color:#e0e0e0
    style Trust2 fill:#0f3460,stroke:#e0e0e0,color:#e0e0e0
    style External fill:#16213e,stroke:#e0e0e0,color:#e0e0e0
```

| Layer | Mechanism |
|-------|-----------|
| **Network** | Tailscale mesh VPN — all traffic encrypted, identity-based SSH (no password auth) |
| **Secrets** | `~/.claude-fleet/` never committed. API keys in Claude config, not fleet config. Gmail app password in `gmail.conf` (gitignored) |
| **Error masking** | All daemon errors logged as `[D-XXX]` codes. No stack traces in review queue. Sensitive output never logged |
| **Input validation** | Task JSON parsed and validated before dispatch. Prompt files checked non-empty. Branch names slugified. Project paths must exist |
| **Isolation** | Workers use `worker/*` branches only. No write access to `main`. One machine, one branch — no conflicts |
| **Least privilege** | Workers: SSH to GitHub + Anthropic API only. Controller: SSH to workers. Commander: SSH to controller only |

---

## Failure Modes and Recovery

| Failure | Detection | Recovery | Error Code |
|---------|-----------|----------|------------|
| **Mac Mini down** | MacBook SSH timeout | Tasks stay queued. Backup on MacBook has tasks.db copy. Restart supervisor via launchd | — |
| **Dell XPS unreachable** | `ssh -o ConnectTimeout=5s` fails | Task re-routes to local Mac Mini execution | D-040 |
| **Daemon crash** | Heartbeat file stale (<60s since last write) | `fleet-supervisor.sh` restarts tmux session within 30s | D-010 |
| **Crash loop** | 5 crashes in 5 minutes | Daemon writes `daemon-crash-loop-blocked.md` to review queue and stops | D-011 |
| **Task stuck** | Heartbeat stale, or exceeds 2h timeout (`TASK_TIMEOUT=7200`) | Daemon kills process, marks `failed`, retries up to `max_retries=3` | D-030 |
| **Task fails** | Claude exit code != 0 | Daemon marks `failed`, writes `{id}-failed.md` to review queue. Auto-retry if retries remaining | D-050 |
| **Disk full** | Write failures to tasks.db or log files | Daemon logs error, skips task. `fleet-backup.sh` prunes logs >7 days | D-060 |
| **GitHub unreachable** | `gh pr create` fails | PR creation retried next cycle. Task marked completed (code is on branch) | D-041 |
| **SQLite corrupt** | task-db.py errors | Falls back to JSON file scanning via fleet-brain.py | D-020 |
| **Service down** | `demo-healthcheck.sh` port checks (60s interval) | Auto-restart: clears cache, kills port, restarts process. 3 attempts then 5-cycle backoff | — |

---

## Evaluator Pipeline

Independent Claude session grades the generator's work, eliminating self-evaluation bias.

```mermaid
flowchart TB
    Claim["Daemon claims task"] --> PlanCheck{"planner: true\nor prompt < 200 chars?"}
    PlanCheck -->|yes| Planner["Planner Claude\n(20 turns, writes .spec.md)"]
    PlanCheck -->|no| Generator
    Planner --> Generator["Generator Claude\n(200 turns, autonomous)"]
    Generator --> Reset{"Context reset?\n(>60min or >500KB log)"}
    Reset -->|yes| Continue["Fresh session\n(reads handoff.md)"]
    Continue --> Reset
    Reset -->|no| EvalCheck{"evaluate: auto\nskip docs/infra?"}
    EvalCheck -->|skip| PR["Open PR"]
    EvalCheck -->|evaluate| Evaluator["Evaluator Claude\n(30 turns, read-heavy)"]
    Evaluator --> Verdict{"Verdict?"}
    Verdict -->|"PASS"| MergeCheck
    Verdict -->|"FAIL, round < max"| Retry["Fresh generator\n+ critique file"]
    Retry --> Evaluator
    Verdict -->|"FAIL, final round"| PR
    PR --> MergeCheck{"Auto-mergeable?\n(topic + <500 LOC)"}
    MergeCheck -->|yes| AutoMerge["gh pr merge --squash"]
    MergeCheck -->|no| ReviewQueue["review-queue/\n(with eval metadata)"]

    style Claim fill:#1a1a2e,stroke:#e0e0e0,color:#e0e0e0
    style Generator fill:#0f3460,stroke:#e0e0e0,color:#e0e0e0
    style Evaluator fill:#16213e,stroke:#e0e0e0,color:#e0e0e0
    style Planner fill:#16213e,stroke:#e0e0e0,color:#e0e0e0
```

| Stage | Turns | Purpose | Output |
|-------|-------|---------|--------|
| **Planner** | 20 max | Structured planning for short/vague prompts | `.spec.md` |
| **Generator** | 200 max | Full implementation with commits | Git branch + PR |
| **Evaluator** | 30 max | Independent review against `eval-criteria/{type}.md` | `{"verdict": "PASS"/"FAIL", "score": 0-100, "issues": [...]}` |
| **Retry** | 200 max | Fresh generator with critique from evaluator | Updated branch |

**Auto-merge policy:** Tasks with topics `docs`, `infra`, or `test` + diff under 500 lines merge automatically. Features, UI changes, and refactors always go to Commander review.

---

## Cost Model

```mermaid
flowchart LR
    Claim["Daemon claims task"] --> BudgetCheck{"cost_today\n< DAILY_BUDGET?"}
    BudgetCheck -->|yes| Run["Execute task"]
    BudgetCheck -->|no| Pause["Skip cycle\n(wait for tomorrow)"]
    Run --> Log["Log cost to\ncost_log table"]
    Log --> TaskBudget{"task cost\n< budget_usd?"}
    TaskBudget -->|yes| Continue["Continue execution"]
    TaskBudget -->|exceeded| Finish["Complete current turn\nthen stop"]

    style Claim fill:#1a1a2e,stroke:#e0e0e0,color:#e0e0e0
    style Run fill:#0f3460,stroke:#e0e0e0,color:#e0e0e0
    style Pause fill:#16213e,stroke:#e0e0e0,color:#e0e0e0
```

| Control | Default | Scope |
|---------|---------|-------|
| `DAILY_BUDGET` | $50/day | Per-machine |
| `budget_usd` | $5/task | Per-task (in manifest JSON) |
| Duration estimate | Weighted by topic affinity + project history | Per-task |
| Planner overhead | +5-10 min estimated | Added when `planner: true` |
| Evaluator overhead | +10-15 min per round | Added when `evaluate: auto` |

**Estimation algorithm** (fleet-brain.py): Completed tasks with timestamps → weighted average by topic affinity (0.2) + same project (0.3) + base (0.5). Combined tasks scale by sub-task count with diminishing returns (`count * 0.7`, capped at 3x).
