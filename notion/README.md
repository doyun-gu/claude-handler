# notion-handler

A plug-and-play documentation framework that turns [Claude Code](https://code.claude.com) into your Notion documentation co-founder. Clone, setup, and Claude Code automatically formats, logs, and manages your Notion workspace with enterprise-grade consistency.

Works for software projects, lecture notes, research, or anything in your dev directory.

---

## Prerequisites

- [Claude Code](https://code.claude.com) installed (`npm install -g @anthropic-ai/claude-code`)
- A Claude Pro, Max, or API subscription
- A [Notion](https://notion.so) account (free or paid)
- Node.js 18+

## Quick Start (5 minutes)

```bash
# 1. Clone
git clone https://github.com/doyun-gu/claude-handler.git ~/claude-handler

# 2. Connect Claude Code to Notion
cd ~/claude-handler/notion
chmod +x setup.sh install-commands.sh
./setup.sh user

# 3. Authenticate — open Claude Code, run /mcp, follow OAuth in browser
claude
# Inside Claude Code: /mcp → grant Notion access

# 4. Install slash commands
~/claude-handler/notion/install-commands.sh

# 5. Initialise your workspace — inside Claude Code:
# "Read notion/INIT.md and execute it"
```

## Slash Commands

| Command | What it does |
|---------|-------------|
| `/notion-sync [project\|all]` | Sync Notion ↔ local dev markdown files |
| `/notion-progress [project]` | Log today's git commits to Notion |
| `/notion-done [project]` | End-of-session: log everything, sync files |
| `/notion-status [project\|all]` | Status report from Notion databases |
| `/notion-decision [project] [summary]` | Log a technical decision |
| `/notion-milestone [project] [desc] [date]` | Add/update a milestone |
| `/notion-doc [project] [topic]` | Create a styled documentation page |
| `/notion-search [query]` | Search the workspace |
| `/notion-review [project]` | Audit docs for quality |
| `/notion-lecture [course] [topic]` | Create a lecture note |

### Typical Workflow

```bash
claude                              # start session
# ... do your work ...
/notion-done my-project             # logs everything to Notion
/notion-status all                  # check status next session
```

## How It Works

**Dual-layer documentation:**
- **Notion** (for humans): Database-driven pages, styled docs, filterable views
- **Dev files** (for AI): CONTEXT.md, STATUS.md, DECISIONS.md in your project folders

**Templates** enforce consistent formatting. **Schemas** standardise databases. **FORMAT.md** is the single source of truth for all style rules.

## File Structure

```
notion/
├── README.md               ← This file
├── NOTION.md               ← Core prompt and conventions
├── INIT.md                 ← First-time workspace setup
├── setup.sh                ← MCP server registration
├── install-commands.sh     ← Slash command installer
├── templates/              ← Document format definitions
│   ├── FORMAT.md           ← Master format guide
│   ├── project-hub.md      ← Project hub template
│   ├── technical-concept.md
│   ├── lecture-notes.md
│   └── all-templates.md    ← Dev log, decision, meeting, sprint, changelog, API
├── schemas/
│   └── SCHEMAS.md          ← All database schemas
├── commands/               ← 10 slash commands
│   └── notion-*.md
└── prompts/
    └── DISCOVER.md         ← Workspace discovery scan
```

## Running Autonomously

```bash
tmux new -s notion
cd ~/claude-handler && claude --dangerously-skip-permissions -p "Read notion/INIT.md and execute it. Proceed autonomously."
# Detach: Ctrl+B then D
# Check: tmux attach -t notion
```

## Author

Created by [Doyun Gu](https://github.com/doyun-gu)

## License

MIT — see [LICENSE](../LICENSE)
