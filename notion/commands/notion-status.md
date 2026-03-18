---
description: Quick project status report from Notion — modules, milestones, blockers
argument-hint: [project-name or "all"]
---

You are pulling a status report from Notion. Read `notion/NOTION.md` for conventions.

## Steps

1. **Read the project hub page** for "$ARGUMENTS" (or all projects if "all") via Notion MCP.

2. **Query the Modules database.** Group by Status. Count items per status.

3. **Query the Deadlines database** filtered to this project. Find the next upcoming deadline.

4. **Query the Decisions database.** Get the most recent 3 decisions.

5. **Query the Activity Log.** Get the last 5 entries for this project.

6. **Print a compact status report:**

```
=== [Project Name] ===
Status: [Active/Paused/Complete]
Next deadline: [milestone] — [date] ([days until])

Modules:  ■■■■■□□ 5 Done / 2 In Progress / 0 Blocked
Recent activity:
  - [date] [description]
  - [date] [description]
  - [date] [description]

Recent decisions:
  - [date] [summary]
  - [date] [summary]

Blockers: [none or list]
```

If "all" projects requested, print one block per project.
