# Multi-Machine Fleet Architecture

Complete guide to scaling the Claude Code fleet from 1 machine to N machines. Covers current setup (2 machines), near-term (3-5), and future scaling (5-10+).

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Current: 2 Machines](#current-2-machines)
3. [Near-Term: 3-5 Machines](#near-term-3-5-machines)
4. [Future: 5-10+ Machines](#future-5-10-machines)
5. [Networking](#networking)
6. [Task Distribution](#task-distribution)
7. [Monitoring & Diagnostics](#monitoring--diagnostics)
8. [Data & Storage](#data--storage)
9. [Security](#security)
10. [Cost Optimization](#cost-optimization)
11. [Error Code Reference](#error-code-reference)
12. [Migration Playbook](#migration-playbook)

---

## Architecture Overview

### Core Principle: Star Topology with Single Controller

```
                    ┌─────────────┐
                    │  MacBook Pro │
                    │  (Commander) │
                    └──────┬──────┘
                           │ SSH
                    ┌──────┴──────┐
                    │  Mac Mini   │
                    │  Controller │
                    │  + Worker 1 │
                    └──┬──────┬───┘
                 SSH   │      │   SSH
            ┌──────────┘      └──────────┐
      ┌─────┴─────┐              ┌───────┴──────┐
      │ Dell XPS  │              │  Future      │
      │ Worker 2  │              │  Worker N    │
      └───────────┘              └──────────────┘
```

**Why star, not mesh:**
- One queue, one DB, one source of truth
- Adding a machine = one SSH config line
- Removing a machine = tasks re-route automatically
- No distributed consensus needed
- Debugging: check one place (Mac Mini)

**Why NOT distributed:**
- 2-10 machines don't need Kubernetes
- Distributed DBs add complexity with no benefit at this scale
- Network partitions between home machines are rare (same LAN/Tailscale)
- The bottleneck is Claude API throughput, not local orchestration

---

## Current: 2 Machines

### Machines

| Machine | Spec | Role | OS |
|---------|------|------|----|
| Mac Mini M4 | 10-core, 32GB | Controller + Worker 1 | macOS |
| Dell XPS 15 | i7, 32GB, NVIDIA GPU | Worker 2 | Windows + WSL2 Ubuntu |

### Communication

```
Mac Mini ←──Tailscale──→ Dell XPS (WSL2)
    │                         │
    ├── Task queue (SQLite)   ├── Claude sessions
    ├── Review queue          ├── Git push/pull
    ├── Health monitoring     └── Results back via git
    └── Dashboard (:3003)
```

### Task Flow

1. MacBook dispatches task → Mac Mini task queue
2. Mac Mini daemon claims task
3. Daemon checks routing: local or Dell?
4. If Dell: `ssh dell-xps "cd $project && claude -p ..."`
5. Task runs, commits, pushes branch, opens PR
6. Mac Mini collects result (git fetch, check PR)
7. Dashboard updates

### What you need

- Tailscale on both machines (free tier, up to 100 devices)
- SSH keys configured
- Same repos cloned on both machines
- `fleet-diagnose.py` for health checks

### Setup guide

See [DELL-XPS-WORKER-SETUP.md](DELL-XPS-WORKER-SETUP.md)

---

## Near-Term: 3-5 Machines

When you add a 3rd machine (maybe another laptop, a Raspberry Pi, or a cloud VM).

### What changes

| Component | 2 machines | 3-5 machines |
|-----------|-----------|--------------|
| Networking | Tailscale | Tailscale (still works perfectly) |
| Task queue | SQLite on Mac Mini | SQLite on Mac Mini (still works) |
| SSH config | 1 host entry | 2-4 host entries |
| Health checks | FD-200 series | FD-200 series per machine |
| Routing | if/else by slug | Routing table in config |
| Dashboard | 2 machine cards | N machine cards (loop) |

### What to add

**1. Machine Registry (projects.json extension)**

```json
{
  "machines": [
    {
      "name": "mac-mini",
      "role": "controller+worker",
      "ssh": "localhost",
      "capabilities": ["frontend", "api", "docker"],
      "max_parallel": 3
    },
    {
      "name": "dell-xps",
      "role": "worker",
      "ssh": "dell-xps",
      "capabilities": ["engine", "cuda", "ml", "tests"],
      "max_parallel": 2
    },
    {
      "name": "cloud-vm",
      "role": "worker",
      "ssh": "cloud-vm",
      "capabilities": ["frontend", "api", "tests"],
      "max_parallel": 1
    }
  ]
}
```

**2. Capability-Based Routing**

Instead of hardcoded slug matching, tag tasks with required capabilities:

```json
{
  "id": "kron-reduction",
  "requires": ["engine", "python"],
  "prefers": ["cuda"]
}
```

Daemon matches task requirements to machine capabilities:
- `requires` = must have all of these
- `prefers` = pick the machine that has the most of these
- Fallback = any available machine

**3. Health-Gated Load Balancing**

```
For each queued task:
  1. Find machines with required capabilities
  2. Filter out unhealthy machines (FD-200 checks)
  3. Filter out machines at max_parallel
  4. Pick the machine with lowest current load
  5. SSH and start task
```

**4. Periodic Fleet Sync**

Every 30 minutes, Mac Mini runs:
```bash
for machine in $(list_workers); do
  ssh $machine "cd ~/Developer/*/ && git fetch origin" &
done
wait
```

### What you DON'T need yet

- Kubernetes (massive overkill for <10 machines)
- Message queues (SSH + SQLite is fine)
- Shared filesystem (git is the sync layer)
- Database replication (single SQLite handles thousands of tasks)
- Load balancer (routing logic in the daemon is enough)

---

## Future: 5-10+ Machines

When you start hitting limits of the simple SSH approach.

### Signals that you need to upgrade

| Signal | Current approach limit | Upgrade to |
|--------|----------------------|------------|
| SSH to 10+ machines is slow | Sequential SSH | Parallel SSH (pssh) or async |
| SQLite write contention | ~100 writes/sec | PostgreSQL |
| Task queue grows to 1000+ | SQLite claim is fine | Still fine, but add archival |
| Dashboard is slow | File-based health | Prometheus + push gateway |
| Machines on different networks | Tailscale (100 devices free) | Tailscale (still works) or WireGuard |
| Need auto-scaling | Manual machine addition | Cloud VMs with auto-start |

### Task Queue: SQLite → PostgreSQL

**When to migrate:** When you have 5+ machines writing to the queue simultaneously and experiencing lock contention (SQLite's WAL mode handles most cases, but >10 concurrent writers can stall).

**Migration path:**
1. Install PostgreSQL on Mac Mini (or use Supabase/Neon hosted)
2. `task-db.py` already uses standard SQL — change `sqlite3.connect()` to `psycopg2.connect()`
3. Keep JSON files as backup/fallback
4. Atomic claiming: use `SELECT ... FOR UPDATE SKIP LOCKED` (PostgreSQL's built-in job queue pattern)

**Alternative: Litestream**
Keep SQLite but replicate it to S3/R2 for backup and read replicas:
```bash
litestream replicate /path/to/tasks.db s3://bucket/tasks.db
```
Workers can read from a replicated copy. Only the controller writes.

### Monitoring: Files → Prometheus + Grafana

**When to migrate:** When checking health by SSHing into each machine becomes tedious (>5 machines).

**Setup:**
1. Each worker runs a tiny HTTP health endpoint (Python, 20 lines)
2. Prometheus on Mac Mini scrapes all workers every 15s
3. Grafana dashboard replaces the HTML dashboard
4. AlertManager sends notifications for failures

**Lighter alternative: Victoria Metrics**
Single binary, lower resource usage than Prometheus. Better for home setups.

**Lightest alternative: Uptime Kuma**
Self-hosted monitoring with a nice UI. Docker one-liner. Supports SSH checks natively.

### Shared Filesystem

**When needed:** When multiple machines need to read the same large files (model weights, dataset files, case libraries) and git is too slow.

**Options by scale:**

| Scale | Solution | Complexity |
|-------|----------|------------|
| 2-3 machines | rsync/Syncthing | Minimal |
| 3-5 machines | SSHFS (mount remote dirs) | Low |
| 5-10 machines | NFS server on Mac Mini | Medium |
| 10+ machines | MinIO (S3-compatible object store) | Medium-high |
| Cloud | S3/R2 bucket | Low (managed) |

**Recommendation:** Start with Syncthing for the `cases/` directory (MATPOWER files). It's peer-to-peer, encrypted, auto-syncs. No server needed.

### Service Discovery

**When needed:** When you're adding/removing machines frequently and don't want to manually update SSH configs.

**Options:**

| Scale | Solution |
|-------|----------|
| 2-5 machines | Tailscale MagicDNS (already have it) |
| 5-10 machines | Tailscale MagicDNS + machine registry JSON |
| 10+ machines | Consul (proper service discovery) |
| Cloud | Cloud provider's service discovery |

Tailscale's MagicDNS gives you `machine-name.tailnet-name.ts.net` hostnames automatically. At 5+ machines this is all you need.

### Container Orchestration

**When Kubernetes makes sense:**
- 10+ machines
- Machines on different networks/cloud providers
- Need auto-scaling (spin up VMs when queue is long)
- Need rolling updates to the daemon across all workers
- Need resource limits and isolation between tasks

**Before Kubernetes, consider:**
- **Docker Compose on each machine** — containerize Claude sessions for isolation
- **Nomad** (HashiCorp) — simpler than K8s, designed for small fleets
- **Kamal** (from Basecamp/37signals) — deploy Docker containers over SSH, no orchestrator needed

**The honest answer:** You probably won't need Kubernetes unless you're running 20+ machines or mixing cloud providers. SSH + Tailscale + SQLite scales surprisingly far.

### Auto-Scaling with Cloud VMs

For burst capacity (big overnight queues):

```
Normal:   Mac Mini + Dell XPS (always on)
Burst:    + 2-3 cloud VMs (spin up when queue > 10, shut down when empty)
```

**Cheapest options:**
- Hetzner Cloud CX32 (4 vCPU, 16GB): ~$15/month
- Oracle Cloud free tier: 4 ARM cores, 24GB RAM (actually free forever)
- AWS Spot instances: ~$0.03/hr for 4 vCPU (can be terminated)

**Auto-scaling daemon logic:**
```python
if queued_tasks > 10 and no_cloud_vms_running:
    spin_up_cloud_vm()
    add_to_machine_registry()
elif queued_tasks == 0 and cloud_vm_idle > 30min:
    spin_down_cloud_vm()
    remove_from_registry()
```

---

## Networking

### Tailscale (recommended for all scales)

| Feature | Benefit |
|---------|---------|
| Mesh VPN | All machines see each other, no port forwarding |
| MagicDNS | `dell-xps` resolves automatically |
| Tailscale SSH | No SSH key management, identity-based auth |
| ACLs | Control who can access what |
| Free tier | 100 devices, 3 users |
| Exit nodes | Route traffic through specific machines |

### Network Topology

```
Home network (192.168.x.x)
├── Mac Mini (Tailscale: 100.x.x.1)
├── Dell XPS/WSL2 (Tailscale: 100.x.x.2)
└── Router (port forwarding NOT needed with Tailscale)

Coffee shop / university:
├── MacBook Pro (Tailscale: 100.x.x.3)
└── Connected to Mac Mini + Dell via Tailscale mesh
```

### Firewall Rules

Only Tailscale traffic needs to flow. No public ports exposed:
- Workers: accept SSH from Tailscale IPs only
- Controller: accept SSH + HTTP (:3003 dashboard) from Tailscale
- All: outbound HTTPS to GitHub, Anthropic API, npm, pip

---

## Task Distribution

### Routing Strategy

```
┌──────────────────────────────────────────────┐
│                TASK ROUTER                    │
│                                              │
│  1. Parse task requirements + preferences    │
│  2. Filter machines by capabilities          │
│  3. Filter by health (FD-200 checks)         │
│  4. Filter by capacity (< max_parallel)      │
│  5. Score remaining machines:                │
│     - Has "prefers" capabilities? +10        │
│     - Lower current load? +5                 │
│     - Faster CPU? +2                         │
│  6. Pick highest score                       │
│  7. Fallback: run on controller              │
└──────────────────────────────────────────────┘
```

### Task Tags

| Tag | Machines | Why |
|-----|----------|-----|
| `engine` | Dell (CUDA), Mac Mini | Python heavy compute |
| `frontend` | Mac Mini | Serves :3002, has node setup |
| `api` | Mac Mini | Serves :8000 locally |
| `cuda` | Dell only | NVIDIA GPU required |
| `tests` | Any | CPU-bound, parallelizable |
| `docs` | Any | Light work |
| `docker` | Mac Mini | Docker Desktop installed |
| `ml` | Dell | GPU + 32GB RAM |

### Dependency-Aware Scheduling

Tasks with `depends_on` only run after dependencies complete:

```
Phase 1: [kron-reduction] → [gast-governor]
                                    │
Phase 2: [flow-animation] → [alarm-hmi] → [voltage-filter]
                                                   │
Phase 3: [contingency-overlay] → [breaker-toggle] → [bus-search]
```

Cross-machine dependencies work because git is the sync layer:
1. Task A completes on Dell, pushes branch + opens PR
2. Task B (depends on A) starts on Mac Mini
3. Mac Mini does `git fetch origin` and sees A's work
4. B builds on A's branch or main (if A was merged)

---

## Monitoring & Diagnostics

### Health Check Architecture

```
Mac Mini (every 60s):
├── Check local health (FD-100 series)
├── SSH dell-xps: check remote health (FD-200 series)
├── SSH worker-3: check remote health (FD-200 series)
├── Write combined health to dashboard
└── Alert if any machine critical
```

### Error Codes by Machine Type

#### Local (FD-100 series) — already implemented

See [ERROR-CODES.md](ERROR-CODES.md) for full reference.

#### Remote Worker (FD-200 series) — to implement

| Code | Check | Severity | Auto-fix |
|------|-------|----------|----------|
| FD-200 | SSH reachable | Critical | Re-route tasks locally |
| FD-201 | Claude CLI version match | Warning | `ssh worker "claude --update"` |
| FD-202 | Disk space > 1GB | Warning | Alert user |
| FD-203 | Git repos in sync | Warning | `ssh worker "git fetch origin"` |
| FD-204 | WSL2 uptime (Dell) | Info | Detect restarts |
| FD-205 | Task completion rate > 70% | Warning | Stop routing if too many failures |
| FD-206 | CPU load < 90% | Warning | Delay routing |
| FD-207 | RAM available > 2GB | Warning | Delay routing |
| FD-210 | Tailscale mesh connected | Critical | Restart Tailscale |
| FD-211 | SSH latency < 500ms | Warning | Delay routing |
| FD-212 | Clock skew < 30s | Warning | `ssh worker "sudo ntpdate pool.ntp.org"` |

### Dashboard Views

#### Fleet Overview (default)
All machines with status cards, active tasks, queue depth, phase progress.

#### Machine Detail (click a card)
Single machine: CPU/RAM history, task history, error log, uptime.

#### Task Timeline (history view)
Gantt-style chart showing which tasks ran where, how long, dependencies.

---

## Data & Storage

### Current: Git + SQLite

| Data | Storage | Sync |
|------|---------|------|
| Source code | Git repos on each machine | `git fetch/pull` |
| Task queue | SQLite on Mac Mini | SSH commands read/write |
| Task manifests | JSON files in `~/.claude-fleet/tasks/` | Part of fleet dir |
| Logs | Text files in `~/.claude-fleet/logs/` | Stay on the machine that ran the task |
| Results | Git branches + PRs | GitHub is the sync layer |

### At 5+ Machines: Consider These Upgrades

| Upgrade | When | How |
|---------|------|-----|
| Litestream | Want SQLite backup | Replicate to S3/R2 in real-time |
| PostgreSQL | Write contention from 5+ workers | Replace SQLite connection string |
| Syncthing | Large shared data (case files) | Peer-to-peer folder sync |
| MinIO | Need S3 API for artifacts | Self-hosted object store |

### Log Aggregation

At 2 machines, SSH + tail is fine. At 5+:

| Scale | Solution |
|-------|----------|
| 2-3 | `ssh worker "tail -100 ~/.claude-fleet/logs/latest.log"` |
| 3-5 | rsync logs to Mac Mini nightly |
| 5-10 | Loki + Grafana (lightweight log aggregation) |
| 10+ | ELK stack or Grafana Cloud |

---

## Security

### SSH Key Management

| Scale | Approach |
|-------|----------|
| 2-3 machines | Manual `ssh-keygen` + `authorized_keys` |
| 3-5 machines | Tailscale SSH (identity-based, no keys) |
| 5-10 machines | Tailscale SSH + ACLs |
| 10+ machines | HashiCorp Vault for SSH certificates |

### Secrets Distribution

| Secret | Current | At scale |
|--------|---------|----------|
| GitHub SSH keys | Per-machine | Per-machine (fine) |
| Anthropic API key | In Claude config | Environment variable, rotated monthly |
| Tailscale auth keys | One-time setup | Pre-auth keys with expiry |
| Fleet config | `~/.claude-fleet/` | Synced from controller via SSH |

### Principle of Least Privilege

- Workers: can only SSH to GitHub (push/pull) and Anthropic API
- Workers: cannot SSH to other workers or controller
- Controller: can SSH to all workers (one-directional)
- Commander (MacBook): can SSH to controller only
- Dashboard: read-only, no write access to queue

---

## Cost Optimization

### Power Management

| Machine | Strategy |
|---------|----------|
| Mac Mini | Always on (low power, ~15W idle) |
| Dell XPS | On during overnight queues, sleep otherwise |
| Cloud VMs | Auto-scale: spin up when queue > 10, down when empty |

### Dell XPS Power Schedule

```
Weekdays:
  6 PM: Wake (Windows Task Scheduler)
  6 AM: Sleep (if queue empty for 30 min)

Weekends:
  Always on (user sets manually for big queues)
```

### Claude API Cost Control

The daemon already has daily budget checks:
```bash
DAILY_BUDGET=50  # $50/day default
```

Per-machine budgets for cost isolation:
```json
{
  "mac-mini": {"daily_budget": 30},
  "dell-xps": {"daily_budget": 20}
}
```

### Cloud VM Cost (future)

| Provider | Spec | Cost | Best for |
|----------|------|------|----------|
| Oracle Cloud | 4 ARM, 24GB | Free forever | Light tasks |
| Hetzner CX32 | 4 vCPU, 16GB | ~$15/mo | Burst capacity |
| AWS Spot t3.xlarge | 4 vCPU, 16GB | ~$0.03/hr | Short bursts |
| Fly.io | 4 vCPU, 8GB | ~$0.04/hr | Easy deploy |

---

## Migration Playbook

### Level 0 → Level 1: Add Second Machine (you are here)

```
Prerequisites: Tailscale installed on both machines
Time: ~1 hour

1. Set up Dell WSL2 (see DELL-XPS-WORKER-SETUP.md)
2. Test SSH from Mac Mini to Dell
3. Add remote execution to daemon (should_run_remote + run_task_remote)
4. Add FD-200 health checks to fleet-diagnose.py
5. Add machine column to task DB
6. Update dashboard for 2 machines
7. Test: dispatch a task, verify it runs on Dell
```

### Level 1 → Level 2: Add Machine Registry (3-5 machines)

```
Prerequisites: Level 1 working reliably for 2+ weeks
Time: ~2 days

1. Add "machines" section to projects.json
2. Add capability tags to task manifests
3. Replace hardcoded routing with capability matching
4. Add per-machine health collection loop
5. Dashboard: dynamic machine cards from registry
6. Test: add a 3rd machine, verify auto-discovery
```

### Level 2 → Level 3: Production Monitoring (5-10 machines)

```
Prerequisites: Level 2, experiencing monitoring pain
Time: ~4 hours

1. Add health HTTP endpoint to each worker (tiny FastAPI, 20 lines)
2. Install Uptime Kuma or Prometheus on controller
3. Set up alerting (email or Slack)
4. Replace file-based health with push metrics
5. Add Grafana dashboard (or keep HTML dashboard with API)
6. Optional: Litestream for SQLite backup
```

### Level 3 → Level 4: Enterprise Scale (10+ machines)

```
Prerequisites: Level 3, adding cloud VMs frequently
Time: ~1 week

1. Migrate SQLite → PostgreSQL
2. Add auto-scaling logic (cloud VMs for burst)
3. Containerize worker with Docker
4. Consider Nomad or Kamal for deployment
5. Add Tailscale ACLs for security
6. Add log aggregation (Loki)
7. Add cost tracking per machine per project
```

---

## Quick Reference

### Commands

```bash
# Fleet diagnostics (all machines)
python3 fleet-diagnose.py

# Check specific remote worker
python3 fleet-diagnose.py --check remote --machine dell-xps

# List all machines
cat ~/.claude-fleet/projects.json | jq '.machines'

# Task queue status
python3 task-db.py stats

# Remote worker health
ssh dell-xps "python3 ~/Developer/claude-handler/fleet-diagnose.py"

# Sync all workers
for m in dell-xps worker-3; do ssh $m "cd ~/Developer/*/ && git fetch origin"; done
```

### Files

| File | Purpose |
|------|---------|
| `~/.claude-fleet/projects.json` | Machine registry + project registry |
| `~/.claude-fleet/tasks.db` | Task queue (SQLite, controller only) |
| `~/.claude-fleet/remote-health/` | Cached health from remote workers |
| `~/.claude-fleet/machine-role.conf` | This machine's role |
| `worker-daemon.sh` | Main daemon (runs on controller) |
| `task-db.py` | Task database CLI |
| `fleet-diagnose.py` | Health checks |

### Architecture Decision Records

| Decision | Chosen | Alternatives considered | Why |
|----------|--------|------------------------|-----|
| Topology | Star (controller + workers) | Mesh, P2P | Single source of truth, simpler debugging |
| Networking | Tailscale | Plain SSH, WireGuard, ZeroTier | MagicDNS, SSH integration, free |
| Task queue | SQLite | PostgreSQL, Redis, RabbitMQ | Good enough for <10 machines, zero ops |
| Sync | Git | NFS, Syncthing, rsync | Already using git, branches isolate work |
| Monitoring | File-based + SSH | Prometheus, Datadog | Proportional to fleet size |
| Deployment | SSH + bash | Docker, K8s, Nomad | Minimal overhead, works everywhere |

---

## Scaling Research: What Breaks at Each Level

Based on real-world fleet scaling patterns and enterprise multi-agent deployments (2024-2026).

### Task Queue Upgrade Path

| System | Best at | Breaks at | Migration effort |
|--------|---------|-----------|-----------------|
| **SQLite + WAL** (current) | 1-3 workers, single writer | Multi-writer contention | -- |
| **SQLite + Litestream** | 1-3 workers + backup | Still single writer | 30 min (add Litestream binary) |
| **PostgreSQL SKIP LOCKED** | 3-10 workers | 50+ workers polling | 1 day (swap driver in task-db.py) |
| **NATS JetStream** | 5-50 workers + pub/sub | New paradigm to learn | 2-3 days |
| **RabbitMQ** | 10-100 workers + routing | Operational complexity | 1 week |

**PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED`** is the strongest next step. Same SQL, atomic claiming, zero race conditions, plus `LISTEN/NOTIFY` for instant dispatch (no more 30s polling).

### Orchestration Upgrade Path

| Scale | Tool | Why |
|-------|------|-----|
| 2-3 machines | SSH scripts (current) | Works fine |
| 4-7 machines | **Ansible** | Provisioning, config management, version consistency across machines |
| 8-15 machines | **Nomad** (HashiCorp) | Single binary, 30-min setup. Handles non-containerized workloads natively (critical for Claude agent processes) |
| 15+ machines | **K3s** (lightweight K8s) | Only if workloads become containerized |

**Key signal to upgrade:** When you SSH into the wrong machine or forget which machine is running what, you've outgrown manual SSH.

### Monitoring Upgrade Path

| Scale | Tool | Setup time |
|-------|------|-----------|
| 2-3 machines | File-based health + dashboard (current) | Done |
| 4-7 machines | **Uptime Kuma** | 10 min (single Docker container, push/pull monitoring, alerts via email/Slack) |
| 7-15 machines | **VictoriaMetrics + Grafana** | 2-3 hours (Prometheus-compatible, lower resource usage) |
| 15+ machines | **Prometheus + Grafana + AlertManager** | 1 day |

**Key metrics for AI agent fleets:**
- Tasks completed per hour per machine
- Average task duration (trend over time)
- API cost per task
- Machine utilization (idle machines = wasted money)
- Failure rate by machine (hardware problems surface here)
- Queue depth over time (growing = need more workers)

### Shared Filesystem Upgrade Path

| Scale | Tool | Use case |
|-------|------|----------|
| 2-3 machines | Git + rsync (current) | Code repos, config |
| 3-5 machines | **Syncthing** | Fleet state dir (`~/.claude-fleet/`) auto-sync between machines |
| 5-10 machines | **NFS** on controller | Shared build caches (node_modules, pip, compiled artifacts) |
| 10+ machines | **MinIO** (S3-compatible) | Artifacts, large files, case libraries |

**Rule:** Never share git working directories over NFS. Each machine clones its own copy. Share artifacts and state, not source trees.

### Security Upgrade Path

| Scale | SSH | Secrets | Network |
|-------|-----|---------|---------|
| 2-3 | Manual Ed25519 keys | `.env` files (gitignored) | LAN / Tailscale |
| 4-7 | **Tailscale SSH** (no key management) | **SOPS + age** (encrypted in git) | Tailscale mesh |
| 8+ | **SSH certificates** (Smallstep, auto-expire) | **Vault or Infisical** (dynamic secrets) | Tailscale + ACL policies |

### Cost Model at Scale

| Fleet size | Setup | Monthly cost estimate |
|------------|-------|----------------------|
| 2 (current) | MacBook Pro + Mac Mini M4 | ~$15-20 power + API |
| 3 (+ Dell XPS) | + Dell XPS 15 as Worker 2 | ~$25-30 power + API |
| 5 | 1 Commander + 4 Mac Mini Workers | ~$60-80 power + $200-500 API |
| 10 | 3 Mac Minis + 7 cloud spot VMs | ~$40 power + $150-300 cloud + $500-1000 API |

**The dominant cost at scale is Anthropic API usage, not infrastructure.** At 10 workers running continuously, API costs will be 5-10x hardware costs.

### When NOT to Scale

- If any machine is idle >60% of the time, you have excess capacity
- Adding machines doesn't help if the bottleneck is API rate limits
- More machines = more maintenance. Only add when queue wait time is unacceptable
- 2 machines running 24/7 can process ~80-100 tasks/day. That's a lot.
