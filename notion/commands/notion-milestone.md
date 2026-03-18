---
description: Add or update a milestone in the Notion Deadlines database
argument-hint: [project-name] [milestone description] [due date YYYY-MM-DD]
---

You are managing milestones in Notion. Read `notion/NOTION.md` for conventions.

## Steps

1. **Parse input.** "$ARGUMENTS" contains: project name, milestone description, and optionally a due date.

2. **Check existing milestones.** Query the Deadlines database filtered to this project. Avoid duplicates.

3. **Create or update:**
   - If this is a new milestone: add to Deadlines database with Status = "Upcoming"
   - If updating an existing one: update the Status (Upcoming / Submitted / Overdue) or Date

4. **Log to Activity Log** that a milestone was added/updated.

5. **Print confirmation** with the milestone details.
