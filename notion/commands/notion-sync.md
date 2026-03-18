---
description: Sync project state between Notion and local dev markdown files
argument-hint: [project-name or "all"]
---

You are syncing documentation between Notion and local dev markdown context files. Read `notion/NOTION.md` for workspace conventions.

## Sync direction: Notion → Dev files

For the project "$ARGUMENTS" (or all projects if "all"):

1. **Read the Notion project hub page** via MCP — full content including overview, architecture, status
2. **Read all sub-pages** under the hub
3. **Read the project's databases** — Modules, Decisions, Milestones
4. **Find the local dev path** from the project hub's "Dev path" field
5. **Update the local dev files:**
   - `CONTEXT.md` — Project overview, goals, current state
   - `ARCHITECTURE.md` — System design, components, data flow
   - `DECISIONS.md` — Append new decisions from Notion not already in the file
   - `STATUS.md` — Current milestone, recent activity, blockers

6. **Check the reverse** — if local dev files have content not in Notion, flag what needs updating

## Output

```
✓ [Project] — CONTEXT.md updated (3 changes)
✓ [Project] — STATUS.md updated (new milestone added)
⚠ [Project] — DECISIONS.md has 2 local decisions not in Notion
✓ [Project] — ARCHITECTURE.md unchanged
```
