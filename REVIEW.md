# Architecture Review — Claude Code Fleet System

**Date:** 2026-03-20
**Reviewer:** Claude (Worker, self-review task)
**Scope:** Full system — daemon, queue manager, dashboard, notifications, slash commands

---

## Executive Summary

The claude-handler fleet system is a well-designed orchestration layer for running autonomous Claude Code agents across two machines. The core architecture — Commander/Worker split with file-based task queue and git branch isolation — is sound and pragmatically engineered. The system has grown organically from a simple daemon to include smart scheduling, task merging, email notifications, a web dashboard, and health monitoring.

This review identifies **3 P0 issues** (must-fix), **4 P1 improvements** (should-do), and **6 P2 ideas** (nice-to-have).

---

## 1. Architecture Fit: Bash + Python

**Verdict: Keep the hybrid, but reduce the seam.**

### Current State
- `worker-daemon.sh` (433 lines) — Bash process launcher with inline Python for JSON parsing
- `queue-manager.py` (938 lines) — Python scheduler with topic affinity, merging, watchdog
- `fleet-notify.sh` (371 lines) — Bash email sender with inline Python for IMAP
- `fleet-status-server.sh` (200 lines) — Bash nc-based HTTP server (superseded by `dashboard/api.py`)
- `demo-healthcheck.sh` (472 lines) — Bash health monitor with inline Python

### Analysis

The hybrid approach is pragmatic. Bash excels at process management (tmux, git, subprocess launching). Python excels at data logic (JSON parsing, scheduling, scoring). The problem isn't the split — it's the **seam between them**.

The daemon calls `python3 -c "import json; ..."` **34 times** across the codebase. These inline Python snippets:
- Are untestable
- Break on special characters in task prompts (shell injection risk)
- Are harder to read than function calls
- Duplicate logic that exists in `queue-manager.py`

### Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Current (bash+python hybrid)** | Process mgmt is natural in bash | Inline python is fragile |
| **Unified Python service** | Single language, testable, type-safe | Process management is clunkier in Python |
| **Node.js** | Good async, JSON native | Overkill, no benefit over Python |
| **Rust/Go binary** | Fast, single binary | Over-engineering for a personal tool |

### Recommendation

**Stay with bash+python but eliminate inline Python.** Add a `queue-manager.py task-field <file> <field>` subcommand that the daemon calls instead of raw `python3 -c`. This is the minimum change that fixes the fragility. **[P0]**

A full rewrite to unified Python is not worth the effort — the current architecture works, and bash is genuinely better for the process-launching half of the daemon.

---

## 2. Queue Manager: Topic-Keyword Affinity

**Verdict: Good enough for current scale. Improve incrementally.**

### Current State
- 9 topic categories with ~10 keywords each (hardcoded in `TOPIC_KEYWORDS`)
- Jaccard similarity for overlap scoring
- Affinity bonus for same-project, same-group, and post-completion context

### Analysis

For 9 projects and ~30 tasks/day, keyword matching is the right complexity level. The scoring function (`score_task`) considers:
- Base priority (from manifest)
- Topic affinity (Jaccard overlap with just-completed task)
- Dependency chain (tasks that unlock others)
- Age (anti-starvation)
- Retry penalty

This is a solid heuristic. The main gap is that **adding a new domain requires editing source code** — the keywords are hardcoded.

### Alternatives Considered

| Option | Benefit | Cost |
|--------|---------|------|
| **Embeddings (e.g., sentence-transformers)** | Semantic matching without keyword lists | Adds a dependency, overkill for 30 tasks/day |
| **File-path analysis from git diff** | Could predict which tasks touch same files | Requires pre-analysis, complex |
| **LLM-based classification** | Flexible, no keyword lists | Token cost, latency, overkill |
| **User-defined tags on dispatch** | Explicit, no guessing | Adds friction to dispatch flow |

### Recommendation

**[P2]** Move `TOPIC_KEYWORDS` to a config file (`~/.claude-fleet/topic-keywords.json`) so new domains can be added without editing source. Not urgent — the current keywords cover the active projects well.

---

## 3. Task Manifest Schema

**Verdict: Mostly good, but missing fields that are already needed.**

### Current Schema (from task manifests)

```json
{
  "id": "20260320-015855-architecture-self-review",
  "slug": "architecture-self-review",
  "branch": "worker/architecture-self-review-20260320",
  "project_name": "claude-handler",
  "project_path": "/Users/doyungu/Developer/claude-handler",
  "subdir": "",
  "dispatched_at": "2026-03-20T01:58:55Z",
  "status": "running",
  "base_branch": "main",
  "prompt": "...",
  "budget_usd": 15,
  "permission_mode": "dangerously-skip-permissions",
  "group": "claude-handler:docs",
  "max_retries": 3,
  "retry_count": 0,
  "priority": 0,
  "started_at": "...",
  "finished_at": "..."
}
```

### Missing Fields (observed in practice)

| Field | Why | Priority |
|-------|-----|----------|
| `pr_number` | Sometimes added post-hoc but not standardized. Worker should always write this. | **P0** |
| `pr_url` | Same — present in some manifests but not part of the schema | **P0** |
| `error_message` | Failed tasks have no structured error. Only the raw log. | **P0** |
| `commits_count` | Useful for watchdog progress tracking | P2 |
| `estimated_minutes` | Better ETA predictions | P2 |
| `actual_tokens_used` | Cost tracking (if Claude CLI exposes this) | P2 |
| `files_changed` | Post-completion summary | P2 |

### Unnecessary Fields

| Field | Why |
|-------|-----|
| `tmux_session` | Derivable from task ID. Present in some manifests but not used by daemon. |
| `permission_mode` | Always `dangerously-skip-permissions`. Could be a daemon-level config. |

### Recommendation

**[P0]** Standardize `pr_number`, `pr_url`, and `error_message` in the schema. Add them to the worker system prompt so Claude always writes them to the manifest on completion/failure. The daemon should also extract PR URL from `gh pr list` output post-completion.

---

## 4. Prompt Efficiency: Worker System Prompt

**Verdict: Well-calibrated. Minor optimizations possible.**

### Current State

The worker system prompt is 10 rules, ~1,200 tokens. It's injected via `--append-system-prompt` on every Claude session.

### Token Breakdown

| Rule | Tokens (approx) | Essential? |
|------|-----------------|------------|
| 1. Fully autonomous | 20 | Yes |
| 2. Branch constraint | 15 | Yes |
| 3. Commit frequently | 10 | Yes |
| 4. Done actions | 15 | Yes |
| 5. Decision template | ~150 | Could reference template |
| 6. Blocked protocol | ~80 | Yes |
| 7. Write summary | 15 | Yes |
| 8. Update task status | 15 | Yes |
| 9. Use gstack skills | 20 | Yes |
| 10. Queue count | 20 | Yes |

### Analysis

1,200 tokens per session is reasonable — it's ~$0.02 at current Opus pricing. The rules are well-written and battle-tested.

**Rule 5** (decision template) is the largest single rule. It includes a full YAML frontmatter template. This could be shortened to "Write decisions to `~/.claude-fleet/review-queue/{task_id}-decision.md` using YAML frontmatter with task_id, project, type: decision_needed, priority, created_at fields" — saving ~80 tokens.

However, the explicit template reduces errors in Worker output. The token cost is negligible. **Leave it as-is.**

### Recommendation

No changes needed. The prompt is well-optimized for reliability over token count.

---

## 5. Multi-Agent: Parallel Workers per Project

**Verdict: Not worth the complexity at current scale.**

### Current Constraint

One Claude agent per project, serial execution. Tasks for the same project queue behind each other.

### Analysis

For DPSpice-com (37K LOC, 140 files), parallel agents could theoretically speed up independent tasks (e.g., API endpoint + frontend component). However:

- **Git worktrees** add complexity: merge conflicts between worktrees, shared node_modules, database locks
- **File locking** is non-trivial: two agents editing the same file causes silent conflicts
- **Claude sessions** are expensive: two parallel Opus sessions burn budget fast
- **The queue already merges** similar tasks, reducing the parallelism benefit
- **Debug complexity** doubles: which agent caused which regression?

### When Would It Pay Off?

| Project Size | Tasks/Day | Parallel Agents? |
|--------------|-----------|-------------------|
| <10K LOC | 1-3 | No |
| 10-50K LOC | 3-10 | No — merge similar tasks instead |
| 50-100K LOC | 10+ | Maybe — if tasks are clearly modular |
| 100K+ LOC | 20+ | Yes — with file-level locking |

### Recommendation

**[P2]** Not now. The current approach of merging similar tasks and running one-per-project is the right tradeoff. Revisit if DPSpice grows beyond 100K LOC or if the user adds more projects to the fleet.

---

## 6. Observability: Log Buffering Problem

**Verdict: P0 fix needed. Logs are useless during execution.**

### Current State

```bash
"$CLAUDE_BIN" -p ... "$task_prompt" 2>&1 | tee "$log_file"
```

The `tee` command buffers its input when the output is a pipe (which it is, since stdout goes through bash). This means:
- Log files are **0 bytes** until the Claude session completes
- The watchdog can't read logs to check progress
- If the daemon crashes, the log is lost entirely

### Root Cause

`tee` uses stdio buffering (4KB blocks by default). When Claude CLI writes output, it goes into a buffer that isn't flushed until full or until the process exits.

### Fix

```bash
# Option A: Force line buffering with stdbuf
stdbuf -oL "$CLAUDE_BIN" -p ... "$task_prompt" 2>&1 | tee "$log_file"

# Option B: Use script command (macOS native, handles PTY)
script -q "$log_file" "$CLAUDE_BIN" -p ... "$task_prompt"

# Option C: Use unbuffer from expect (requires expect package)
unbuffer "$CLAUDE_BIN" -p ... "$task_prompt" 2>&1 | tee "$log_file"
```

**Option A (`stdbuf -oL`)** is the simplest and most portable. It forces line-buffered output, so each line from Claude CLI is written to the log file immediately. Note: on macOS, `stdbuf` requires GNU coreutils (`brew install coreutils` provides `gstdbuf`).

**Option B (`script`)** is macOS-native and handles PTY allocation, which may give better output from Claude CLI. However, it captures terminal control codes.

### Recommendation

**[P0]** Use `script -q` on macOS (native, no dependencies) with a fallback to `stdbuf -oL` on Linux. This ensures logs are available in real-time for the watchdog and for debugging.

---

## 7. Merge Buffer: Task Combining Heuristic

**Verdict: Current rules are well-calibrated after previous tightening.**

### Current Rules

```python
MAX_MERGE = 3              # max tasks per combined session
MIN_AFFINITY_TO_MERGE = 0.6  # was 0.3, tightened
MAX_PROMPT_CHARS = 4000    # total prompt limit
```

Additional guards:
- Never merge retried tasks
- Never merge already-combined tasks
- Never merge heavy/review/audit tasks
- Never merge tasks with dependencies
- Must be same group (project:topic)

### Analysis

These rules are conservative and correct. The previous 0.3 affinity threshold was too aggressive (combined dissimilar tasks that failed). 0.6 is a good minimum.

The `MAX_PROMPT_CHARS = 4000` limit is smart — it prevents bloated sessions where Claude loses focus.

### One Gap

**No base_branch check.** Two tasks for the same project but different base branches (e.g., `main` vs `feature/x`) should never be merged. This hasn't been a problem yet because most tasks target `main`, but it's a latent bug.

### Recommendation

**[P1]** Add a base_branch check to `is_merge_safe()` — only merge tasks with the same base_branch.

---

## 8. Notification System

**Verdict: Right-sized for a single user. No changes needed.**

### Current State

- **Email (Gmail SMTP):** HTML emails with action buttons (merge/skip/fix)
- **Reply-to-action:** Check Gmail IMAP for replies, create action files
- **macOS notifications:** `osascript` in fleet-status-server.sh
- **Web dashboard:** Real-time via api.py
- **Filter:** Only failures, blocks, and digests email through. Completions suppressed.

### Analysis

For a single-user fleet, this is the right level. The email filter that suppresses non-critical notifications was a good recent change (commit `adf854f`).

Slack/Discord would add a dependency and configuration complexity for no benefit with one user. Push notifications are already handled by macOS `osascript`.

### Recommendation

No changes. The notification system is well-calibrated.

---

## 9. Cost Tracking

**Verdict: Useful but enforcement is risky.**

### Current State

`budget_usd` exists in task manifests but is not enforced. It's displayed in daemon logs but Claude isn't told its budget in a way that affects behavior.

### Analysis

- **Claude CLI does not expose real-time token usage** during a session
- **Killing a session mid-flight** loses partial work (uncommitted changes, incomplete PRs)
- **Post-hoc tracking** is possible by parsing log file size as a proxy, or by checking the Claude API usage dashboard
- **The worker prompt mentions budget** (Rule 10 mentions queue count but not budget)

### Recommendation

**[P1]** Add budget to the worker system prompt: "Your budget for this task is $X. If you're approaching the limit, commit what you have and wrap up." This gives Claude soft awareness without hard enforcement. Hard killing based on budget is not recommended — partial work is worse than slightly over-budget.

---

## 10. What's Missing

### Already Implemented (not missing)
- Task dependencies (`depends_on` in queue-manager.py) ✓
- Approval gates (review queue) ✓
- Auto-retry (queue-manager.py `max_retries`) ✓
- Task merging (conservative, well-tuned) ✓

### Missing — Worth Adding

| Feature | Value | Complexity | Priority |
|---------|-------|------------|----------|
| **Task cancellation** | Kill stuck tasks gracefully | Low — `tmux kill-session` + status update | **P1** |
| **Log streaming** | View live output from Commander | Medium — SSH + tail -f | P2 |
| **Scheduled tasks (cron)** | "Run tests every night at 2am" | Medium — add cron-like scheduling | P2 |
| **Rollback capability** | Undo a bad merge quickly | Low — `git revert` wrapper | P2 |
| **Cross-project refactors** | Rename shared types across repos | High — multi-repo coordination | P2 |
| **Priority preemption** | Urgent task interrupts running one | High — graceful interruption is hard | P2 |

### Not Worth Adding
- **A/B testing branches:** Over-engineering for a 2-machine fleet
- **Kubernetes/container orchestration:** This is a personal dev tool, not a production service
- **Database for task state:** File-based JSON is simpler and sufficient at this scale

---

## P0 Implementation Plan

### Fix 1: Log Buffering
**File:** `worker-daemon.sh` line 190-195
**Change:** Use `script -q` on macOS for unbuffered log capture
**Risk:** Low — only affects logging, not task execution

### Fix 2: Replace Inline Python
**File:** `worker-daemon.sh` (34 inline python calls), `queue-manager.py` (add subcommands)
**Change:** Add `queue-manager.py task-field <file> <field>` and `queue-manager.py update-status <file> <status>` subcommands. Replace all `python3 -c "import json; ..."` calls in daemon with these.
**Risk:** Low — same logic, better interface

### Fix 3: Standardize Task Manifest Fields
**File:** `worker-daemon.sh` (completion handler), worker system prompt
**Change:** Always write `pr_url`, `pr_number`, `error_message` to task manifest. Update the worker system prompt to instruct Claude to update these fields.
**Risk:** Low — additive change

---

## Summary Table

| # | Issue | Priority | Effort | Impact |
|---|-------|----------|--------|--------|
| 1 | Log buffering (0 bytes during execution) | **P0** | 1 line | Observability |
| 2 | Inline Python in daemon (fragile, untestable) | **P0** | ~50 lines | Reliability |
| 3 | Missing manifest fields (pr_url, error_message) | **P0** | ~20 lines | Data completeness |
| 4 | Redundant fleet-status-server.sh | **P1** | Delete file | Code hygiene |
| 5 | No base_branch check in merge logic | **P1** | 3 lines | Correctness |
| 6 | Budget not in worker prompt | **P1** | 1 line | Cost awareness |
| 7 | Task cancellation support | **P1** | ~30 lines | Operations |
| 8 | Topic keywords in config file | P2 | ~20 lines | Extensibility |
| 9 | Log streaming from Commander | P2 | ~40 lines | Observability |
| 10 | Scheduled tasks (cron) | P2 | ~100 lines | Automation |
| 11 | Rollback wrapper | P2 | ~20 lines | Safety |
| 12 | Cross-project refactors | P2 | ~200 lines | Multi-repo |
| 13 | Priority preemption | P2 | ~100 lines | Scheduling |

---

*Generated by architecture-self-review task on 2026-03-20.*
