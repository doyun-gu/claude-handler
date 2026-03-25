# Dispatch and Daemon Architecture

How tasks flow from Commander to Worker, get claimed, executed, and reported back.

## Dispatch Flow

```mermaid
flowchart TB
    subgraph Commander["MacBook Pro (Commander)"]
        User([User]) -->|"/dispatch"| Parse["Parse task\n(project, slug, priority)"]
        Parse --> WritePrompt["Write .prompt file\n(plain text, no escaping)"]
        Parse --> WriteJSON["Write .json manifest\n(metadata only, no inline prompt)"]
        WritePrompt --> Validate["Validate\n- JSON parses\n- prompt_file field exists\n- .prompt non-empty"]
        WriteJSON --> Validate
        Validate --> RegLocal["python3 task-db.py add\n(local tasks.db)"]
        RegLocal --> Backup["Copy to dispatch-log/\n(immutable backup)"]
    end

    subgraph Sync["Network Sync"]
        Backup --> SCP1["scp .prompt FIRST"]
        SCP1 --> SCP2["scp .json manifest"]
        SCP2 --> RegRemote["ssh: task-db.py add\n(Mac Mini tasks.db)"]
    end

    subgraph Worker["Mac Mini (Worker Daemon)"]
        RegRemote -.->|"daemon polls"| Daemon
        Daemon["worker-daemon.sh\n(polls every 30s)"] --> Claim["task-db.py claim\n(atomic SQLite query)"]
        Claim -->|"resolves priority\n+ dependencies"| ReadPrompt["Read .prompt file"]
        ReadPrompt --> GitSetup["git checkout -b worker/...\nfrom base_branch"]
        GitSetup --> Claude["Claude Code\n(autonomous, --dangerously-skip-permissions)"]
        Claude -->|"commits frequently"| Push["git push + gh pr create"]
        Push --> ReviewQ["Write review-queue/*.md\n(completed/failed/blocked)"]
        ReviewQ --> StatusDB["task-db.py status completed"]
        StatusDB --> Heartbeat["Update heartbeat"]
        Heartbeat -->|"loop back"| Claim
    end

    style Commander fill:#1a1a2e,stroke:#e0e0e0,color:#e0e0e0
    style Sync fill:#16213e,stroke:#e0e0e0,color:#e0e0e0
    style Worker fill:#0f3460,stroke:#e0e0e0,color:#e0e0e0
```

## Data Layer

```mermaid
flowchart LR
    subgraph Primary["tasks.db (daemon primary)"]
        TaskDB["task-db.py CLI"]
        TaskDB --> Claim2["claim: atomic SELECT + UPDATE"]
        TaskDB --> Heartbeat2["heartbeat: pid, log size, alive"]
        TaskDB --> Status2["status: queued/running/completed/failed"]
        TaskDB --> Priority2["priority: 100+ user, 50+ high, 0 normal"]
        TaskDB --> Deps["depends_on: blocks until deps complete"]
    end

    subgraph Bridge["JSON Files (sync bridge)"]
        JSON["tasks/*.json"]
        Prompt["tasks/*.prompt"]
    end

    subgraph Legacy["fleet.db (dashboard read replica)"]
        DashDB["dashboard/db.py"]
        DashDB --> Sync2["sync_from_json() every 30s"]
        DashDB --> API["FastAPI :3003"]
    end

    TaskDB -->|"daemon writes"| JSON
    JSON -->|"dashboard reads"| DashDB

    style Primary fill:#1a1a2e,stroke:#e0e0e0,color:#e0e0e0
    style Bridge fill:#16213e,stroke:#e0e0e0,color:#e0e0e0
    style Legacy fill:#0f3460,stroke:#e0e0e0,color:#e0e0e0
```

## Task File Format

Each dispatched task consists of **two files** in `~/.claude-fleet/tasks/`:

### JSON Manifest (`<task-id>.json`)

```json
{
  "id": "20260325-143000-feature-slug",
  "slug": "feature-slug",
  "branch": "worker/feature-slug-20260325",
  "project_name": "DPSpice-com",
  "project_path": "/Users/doyungu/Developer/dynamic-phasors/DPSpice-com",
  "status": "queued",
  "base_branch": "main",
  "prompt_file": "20260325-143000-feature-slug.prompt",
  "budget_usd": 10,
  "max_turns": 200,
  "permission_mode": "dangerously-skip-permissions",
  "priority": 50,
  "depends_on": [],
  "group": "phase1-engine",
  "dispatched_at": "2026-03-25T14:30:00Z"
}
```

### Prompt File (`<task-id>.prompt`)

Plain text. Any length, any characters. No JSON escaping needed.

## Daemon Claiming Logic

```mermaid
sequenceDiagram
    participant D as Daemon (30s loop)
    participant DB as tasks.db (SQLite)
    participant FS as Filesystem
    participant C as Claude Code

    D->>DB: task-db.py claim
    Note over DB: Atomic query:<br/>1. Check daily cost < budget<br/>2. Filter status=queued<br/>3. Check depends_on all completed<br/>4. Order by priority DESC<br/>5. One-per-project limit<br/>6. UPDATE status=running

    DB-->>D: {id, project_name, ...}
    D->>FS: Read tasks/{id}.prompt
    FS-->>D: prompt text
    D->>FS: git checkout -b worker/...
    D->>C: Launch Claude (tmux session)

    loop Every 60s while running
        D->>DB: task-db.py heartbeat {id}
        Note over DB: Updates: pid, log_size,<br/>last_heartbeat, alive status
    end

    C-->>D: Exit (success or failure)
    D->>DB: task-db.py status {id} completed
    D->>FS: Write review-queue/{id}-completed.md
    D->>FS: git checkout main (cleanup)
    D->>D: Loop back to claim
```

## Priority System

| Priority | Level | When to use |
|----------|-------|-------------|
| `100+` | P0 | User-requested tasks (always run first) |
| `50-99` | P1 | High priority features |
| `10-49` | P2 | Normal queued tasks |
| `0-9` | P3 | Backlog, maintenance, auto-generated |

The daemon always picks the highest-priority queued task whose dependencies are met.

## Review Queue

When a task completes, the daemon writes to `~/.claude-fleet/review-queue/`:

| File | Meaning |
|------|---------|
| `{id}-completed.md` | PR ready for review |
| `{id}-failed.md` | Task crashed, check logs |
| `{id}-blocked.md` | Worker stuck, needs Commander |
| `{id}-decision.md` | Worker made a choice, wants confirmation |

Commander checks this on every session startup and surfaces items before the greeting.

## Common Mistakes

1. **Missing `task-db.py add`** -- daemon cannot claim tasks not registered in SQLite
2. **Inline prompt in JSON** -- special characters break JSON silently, daemon rejects
3. **Forgetting to sync `.prompt` file** -- JSON arrives, daemon claims, but prompt is empty
4. **Wrong sync order** -- must scp `.prompt` BEFORE `.json` (daemon triggers on JSON)
5. **Missing `priority` field** -- defaults to 0, task runs last even if urgent
6. **Stale `running` status** -- after daemon restart, clean up with `task-db.py stuck`
