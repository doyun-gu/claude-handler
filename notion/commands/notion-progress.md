---
description: Log today's work to Notion Activity Log and update project status
argument-hint: [project-name]
---

You are logging development progress to Notion. Read `notion/NOTION.md` for workspace conventions.

## Steps

1. **Detect what changed today.** Run `git log --oneline --since="today" --all` across the project "$ARGUMENTS" dev folder to find today's commits. If no commits, ask what was worked on.

2. **Build the activity entry.** From the commits and context, construct:
   - Name: concise summary of today's work (1 line)
   - Project: link to the correct project in the Projects database
   - Date: today
   - Category: Code / Paper / Hardware / Design / Admin (infer from commits)

3. **Add to Notion Activity Log database** via MCP.

4. **Update the project's Modules database.** If any module status changed (e.g., a feature moved from In Progress to Done), update it.

5. **Update the project's Milestones.** If a milestone was completed or progress was made, update the Deadlines database entry.

6. **Update local STATUS.md** in the project's dev folder with today's changes.

7. **Print summary:**
   ```
   Logged to Notion Activity Log:
     "[summary]" — [project] — [category] — [date]

   Updated:
     ✓ Module "[name]" → Done
     ✓ STATUS.md updated
   ```
