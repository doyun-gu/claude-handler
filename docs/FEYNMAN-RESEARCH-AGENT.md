# Feynman -- AI Research Agent

Usage guide for [getcompanion-ai/feynman](https://github.com/getcompanion-ai/feynman), an open-source multi-agent research tool that automates deep academic and technical research with source-grounded, cited outputs.

## Why We Use It

Before implementing complex DPSpice features (engine algorithms, visualization design, SaaS architecture), we need grounded research -- not LLM hallucinations. Feynman provides:

- **Multi-agent parallel research** -- spawns 3-6 researchers on different angles simultaneously
- **Source-grounded outputs** -- every claim has a URL or citation
- **Adversarial verification** -- a reviewer agent checks for unsupported claims and logical gaps
- **Provenance tracking** -- `.provenance.md` sidecar shows what was consulted, accepted, rejected

This replaces our manual "search, read, synthesize" loop and enforces the "research before design" rule.

## Installation

```bash
# Standalone (recommended)
curl -fsSL https://feynman.is/install | bash

# First-time setup (interactive)
feynman setup

# Verify installation
feynman doctor
```

### Required API Keys

Set in `~/.feynman/.env` or environment:

```bash
FEYNMAN_MODEL=anthropic/claude-sonnet-4    # or openai/gpt-4o
FEYNMAN_THINKING=medium                     # low | medium | high
ANTHROPIC_API_KEY=sk-...                    # if using Anthropic
OPENAI_API_KEY=sk-...                       # if using OpenAI
```

Optional for GPU compute:
```bash
RUNPOD_API_KEY=...     # persistent GPU pods
MODAL_TOKEN_ID=...     # serverless GPU bursts
MODAL_TOKEN_SECRET=...
```

## Architecture

```
Lead Agent (plans, delegates, synthesizes)
  |
  +-- Researcher (evidence gathering -- papers, web, repos)
  +-- Reviewer (adversarial audit, peer review simulation)
  +-- Writer (structured drafting from research notes)
  +-- Verifier (inline citation, URL verification, dead link cleanup)
```

Agents communicate via **file-based handoffs** (not context passing). Each subagent writes output to a file and passes back a lightweight reference.

### Deep Research Pipeline

```
Plan (strategy + acceptance criteria)
  -> Scale Decision (how many researchers to spawn)
  -> Spawn Parallel Researchers (disjoint dimensions)
  -> Evaluate & Loop (check gaps, spawn more if needed)
  -> Write Report (structured brief with charts/diagrams)
  -> Cite (inline citations, numbered sources)
  -> Verify (adversarial audit for unsupported claims)
  -> Deliver (final .md + .provenance.md sidecar)
```

## Commands

### Research Workflows

| Command | What It Does | When to Use |
|---------|-------------|-------------|
| `/deepresearch` | Multi-round, multi-agent investigation | Complex algorithm research, architecture decisions |
| `/lit` | Literature review with consensus/gap analysis | Before implementing engine features, dissertation refs |
| `/review` | Simulated peer review with severity annotations | Auditing our own docs/reports before sharing |
| `/audit` | Paper vs codebase mismatch check | Verifying our engine matches cited papers |
| `/replicate` | Experiment replication (Docker/Modal/RunPod) | Reproducing benchmark results from papers |
| `/compare` | Source comparison matrix | Evaluating competing approaches (e.g., solvers) |
| `/draft` | Paper-style document from research | Dissertation sections, technical reports |
| `/watch` | Recurring research monitoring | Track new publications, competitor releases |

### Utility Commands

```bash
feynman model list          # available models
feynman model set <model>   # switch model
feynman packages list       # installed packages
feynman update              # self-update
```

## DPSpice Usage Patterns

### Pattern 1: Pre-Implementation Research

Before implementing a complex engine feature, run deep research first. Feed the output into dispatch prompts.

```bash
# Research before implementing
feynman deepresearch "PV-PQ bus switching algorithms in Newton-Raphson power flow -- how do PSS/E, PowerWorld, and MATPOWER implement Q-limit enforcement?"

# Output: outputs/pv-pq-bus-switching.md + pv-pq-bus-switching.provenance.md
# Use as background in the .prompt file for the Mac Mini dispatch
```

### Pattern 2: Algorithm Comparison

When choosing between approaches, use `/compare` or `/lit`:

```bash
feynman lit "sparse linear solvers for power system Jacobians -- KLU vs UMFPACK vs SuperLU vs PARDISO performance characteristics"

feynman compare "IDP vs shifted frequency analysis vs quasi-static time series for dynamic phasor simulation"
```

### Pattern 3: Dissertation Support

```bash
# Literature review for a dissertation section
feynman lit "dynamic phasor simulation methods for large-scale power systems"

# Audit our implementation against cited papers
feynman audit <arxiv-id>

# Peer review simulation before submission
feynman review outputs/dissertation-chapter-4.md
```

### Pattern 4: Competitive Intelligence

```bash
# One-time competitor analysis
feynman deepresearch "browser-based power system simulation tools -- what exists, pricing, capabilities, limitations"

# Recurring monitoring
feynman watch "new publications on web-based power system simulation tools" --interval weekly
```

### Pattern 5: SaaS Architecture Research

```bash
feynman deepresearch "authentication and tenant isolation patterns for scientific SaaS -- how do Figma, Vercel, and Replit handle multi-tenant compute with user-uploaded code"
```

## Integration with Fleet Dispatch

Research output feeds into the dispatch workflow:

```
1. Run feynman on MacBook (or Mac Mini)
2. Review the output .md file (has citations + provenance)
3. Copy relevant sections into the .prompt file as "Background Research"
4. Dispatch to Mac Mini with grounded context

Example .prompt structure:
---
## Background Research (from Feynman)
[paste relevant sections with citations]

## Task
Implement Q-limit enforcement using the approach described in [3] (MATPOWER's PV-PQ switching).

## Validation
- pytest -m validation passes
- Q-limit enforced on IEEE 30-bus (bus 2 should switch to PQ)
- Results match MATPOWER reference within 1e-6 pu
---
```

## Key Packages (Pi Ecosystem)

| Package | Purpose |
|---------|---------|
| `@companion-ai/alpha-hub` | AlphaXiv paper search, Q&A, code reading |
| `pi-web-access` | Web search (Perplexity or Gemini) |
| `pi-subagents` | Multi-agent orchestration |
| `pi-zotero` | Zotero reference manager integration |
| `@walterra/pi-charts` | Chart generation |
| `pi-mermaid` | Mermaid diagram rendering |
| `pi-schedule-prompt` | Recurring tasks (for /watch) |
| `@samfp/pi-memory` | Persistent memory across sessions |

## Skills-Only Install

If you already have a compatible agent shell (Codex, Pi), install just the research skills:

```bash
curl -fsSL https://feynman.is/install-skills | bash
# Skills installed to ~/.codex/skills/feynman/ or .agents/skills/feynman/
```

## File Locations

```
~/.feynman/
  agent/          -- live agent/skill definitions
  sessions/       -- session history
  memory/         -- persistent memory across sessions
  .state/         -- bootstrap state tracking

./outputs/        -- research outputs (created in working directory)
  .plans/         -- research plans
  *.md            -- final reports
  *.provenance.md -- provenance sidecars
```
