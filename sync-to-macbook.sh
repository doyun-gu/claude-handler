#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   claude-handler sync script
#   Run this on your MacBook Pro to match Mac Mini setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  claude-handler MacBook Pro sync"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 1: Clone or pull claude-handler
HANDLER_DIR="$HOME/Developer/claude-handler"
if [ -d "$HANDLER_DIR" ]; then
  echo "[1/3] claude-handler already exists — pulling latest..."
  cd "$HANDLER_DIR" && git pull
else
  echo "[1/3] Cloning claude-handler..."
  mkdir -p "$HOME/Developer"
  git clone https://github.com/doyun-gu/claude-handler.git "$HANDLER_DIR"
fi
echo ""

# Step 2: Run install.sh (symlinks global CLAUDE.md + all commands)
echo "[2/3] Running install.sh..."
cd "$HANDLER_DIR"
chmod +x install.sh
./install.sh
echo ""

# Step 3: Write user profile
echo "[3/3] Writing user profile..."
mkdir -p "$HOME/.claude"
cat > "$HOME/.claude/user-profile.md" << 'PROFILE'
# User Profile

Generated: 2026-03-19

## Identity

- **Role:** Final-year EEE student / Solo founder building DPSpice.com
- **Experience:** 3-4 years in power electronics, C/C++, Python, web development
- **Strongest areas:** Power electronics, circuit simulation, C/C++, Python
- **Currently learning:** Power system analysis (engineer workflows, competitor features like PSCAD), web dev architecture for SaaS

## Work Style

- **Explanation level:** High-level progress summaries always; low-level debug logs saved to md files (not in chat)
- **Pushback level:** Challenge on big architectural decisions; otherwise make good structured choices autonomously
- **Speed vs quality:** Quality and performance first — dissertation nearly done, building for production
- **Testing philosophy:** Always test with mock use cases after implementing features; run full test suites frequently
- **Commit style:** Commit frequently on every meaningful change; push when it needs to be logged

## Environment

- **OS:** macOS (Mac Mini + MacBook Pro, Windows available)
- **Editor:** VS Code (IDE), iTerm2 + tmux for Claude Code sessions
- **Workflow:** Sometimes grants full permissions for overnight autonomous work sessions
- **Sync:** Multiple laptops — always check GitHub sync at session start

## Rules

### Always
- Keep architecture docs and context files up to date — optimise for fast session onboarding (Claude should understand the project without reading everything)
- Sync progress to Notion for high-level tracking
- Test all features with mock use cases after implementation
- Check GitHub sync at session start (multi-machine workflow)
- Document all work and logs to save tokens and time
- Security-check features before considering them launch-ready
- When no specific task: run tests, log problems, identify missing features, update progress docs and plans
- Validate everything is up to date across documentation

### Never
- Never delete critical project files — move to another directory instead
- Never share personal information via GitHub

## Notes
- DPSpice.com concept: AI-assisted power system analysis SaaS where clicking on bus schematics/waveforms surfaces parameters and matrices for AI context, helping engineers understand and debug
- Dissertation and business are the same project — academic deliverable + commercial product
- Wants to deeply understand what engineers need and what competitors (PSCAD etc.) offer
PROFILE

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Sync complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  ✓ claude-handler installed"
echo "  ✓ All slash commands symlinked"
echo "  ✓ User profile written"
echo ""
echo "  Restart Claude Code for changes to take effect."
