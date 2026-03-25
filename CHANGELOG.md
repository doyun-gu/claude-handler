# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-03-25

### Added
- Evaluator harness: planner-generator-evaluator pipeline with context resets (2026-03-25)
- One-shot Dell XPS worker setup script (2026-03-25)
- Remote worker routing — run tasks on Dell XPS via SSH (2026-03-25)
- Fleet backup system — sync critical data to MacBook after each task (2026-03-25)
- SQLite task database for fleet daemon (2026-03-24)
- P0 fleet upgrades — process group kills, heartbeat monitor, budget check (2026-03-24)
- Python health monitor with auto-fix and post-merge hook (2026-03-23)
- Observability and error code system to worker daemon (2026-03-23)

### Changed
- Worker daemon rewritten to prevent crash-loop failures (2026-03-23)
- `/workdone` upgraded with HANDOFF.md generation and full session save (2026-03-23)

### Fixed
- Route field preserved in SQLite schema for remote worker routing (2026-03-25)
- 6 daemon bugs + diagnostic API endpoint (2026-03-25)
- Redirect log_error to stderr in functions called via `$()` (2026-03-25)
- Prevent infinite auto-bugfix task loop (2026-03-24)
- Separate prompt into .prompt file to prevent silent data loss (2026-03-24)
- Remove hardcoded username path from workdone.md (2026-03-24)

### Documentation
- Comprehensive fleet architecture document with mermaid diagrams (2026-03-25)
- Dispatch architecture with SQLite-primary workflow (2026-03-25)
- Error code reference for daemon (D-xxx) and diagnostics (FD-xxx) (2026-03-25)
- Dell XPS worker setup guide + 2-worker dashboard plan (2026-03-25)
- Comprehensive multi-machine fleet guide (2 to 10+ machines) (2026-03-25)
- WSL2 worker quick-start added to README (2026-03-25)
- Fleet API reference (dashboard, health monitor, scripts) (2026-03-23)

### Tests
- Fleet routing verification — Mac Mini local (2026-03-25)
- Fleet routing verification — Dell XPS remote (2026-03-25)

## [0.4.0] - 2026-03-21

### Added
- Fleet dashboard v3 — focused UX improvements (2026-03-21)
- Task Timeline replaced with actionable analytics (2026-03-21)
- Light/dark mode toggle with system detection (2026-03-21)
- Mobile responsive layout for iPhone viewing (2026-03-21)

### Fixed
- Redesign chart tooltip — cleaner, rounded, better typography (2026-03-21)
- Remove Daily Cost chart from dashboard (2026-03-21)
- Remove personal paths and usernames from public repo (2026-03-21)
- Align Worker Pipeline cards with consistent height (2026-03-20)

## [0.3.0] - 2026-03-20

### Added
- Fleet dashboard with Kanban pipeline and charts (2026-03-20)
- SQLite backend, progress charts, project filters, and sync status (2026-03-20)
- Auto-restart services when code changes (2026-03-20)
- Events section with freeze integration (2026-03-20)
- Machine identity card to fleet dashboard (2026-03-20)
- Project + time filter pills to dashboard (2026-03-20)
- Daemon auto-merge for safe PRs (2026-03-20)
- Auto-heal known bugs from knowledge base (2026-03-20)
- fleet-brain.py — single intelligent fleet manager (2026-03-20)
- Terminal/htop-inspired dashboard rewrite (2026-03-20)
- config.example/ with placeholder configs (2026-03-20)
- Template launchd plist for any user (2026-03-20)
- Install script rewritten with Commander/Worker role selection (2026-03-20)

### Changed
- Replace budget_usd with estimated_time in worker daemon (2026-03-20)
- Dashboard made fully responsive for mobile (2026-03-20)

### Fixed
- Health checker crash loop + add process supervisor (2026-03-20)
- Dashboard api.py Python 3.9 compatibility (2026-03-20)
- Suppress all non-emergency emails (2026-03-20)
- Replace hardcoded paths in fleet-startup.sh with dynamic detection (2026-03-20)
- Replace hardcoded IP and paths in demo-healthcheck.sh (2026-03-20)
- Remove hardcoded paths from fleet-supervisor, sync, and dispatch (2026-03-20)
- Health checker wrong tmux session name (2026-03-20)
- gh auth health check added to demo-healthcheck.sh (2026-03-20)

### Documentation
- Fleet system setup, supervision architecture, bug-db, and troubleshooting (2026-03-20)
- Worker Daemon architecture section with diagrams (2026-03-20)
- Post-push sync protocol (2026-03-20)
- Worktree preview isolation and PR merge ordering (2026-03-20)
- README rewritten with mermaid diagrams and public-ready docs (2026-03-20)

## [0.2.0] - 2026-03-19

### Added
- Dual-machine Commander/Worker architecture (2026-03-19)
- `/fleet` dashboard and multi-project dispatch support (2026-03-19)
- Autonomous Worker daemon, review queue, and auto-sync startup (2026-03-19)
- `/queue` dashboard command and enhanced health checker (2026-03-19)
- `/architecture`, `/queue`, `/validate` commands (2026-03-19)
- Email notifications with action buttons, reply-to-merge pipeline (2026-03-19)
- Parallel task execution + redesigned email notifications (2026-03-19)
- Conversation logging system (Claude Desktop to Claude Code pipeline) (2026-03-19)
- `/save` command — Claude Desktop to Claude Code handoff (2026-03-19)
- gstack sprint workflow skills to global CLAUDE.md (2026-03-19)

### Fixed
- Worker daemon reads base_branch from task manifest (2026-03-19)

## [0.1.0] - 2026-03-18

### Added
- Technical Co-Founder framework with smart onboarding (2026-03-17)
- Notion documentation framework for Claude Code (2026-03-18)
- `/cofounder` command with unified installer (2026-03-18)
- Session startup with separate user profile (2026-03-18)

[Unreleased]: https://github.com/doyun-gu/claude-handler/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/doyun-gu/claude-handler/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/doyun-gu/claude-handler/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/doyun-gu/claude-handler/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/doyun-gu/claude-handler/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/doyun-gu/claude-handler/releases/tag/v0.1.0
