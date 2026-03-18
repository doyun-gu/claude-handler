---
description: End-of-session handoff — log all work to Notion and sync dev files
argument-hint: [project-name]
---

You are closing out a work session on "$ARGUMENTS". This is the end-of-session routine that ensures everything is documented.

## Steps

1. **Gather what happened this session:**
   - `git diff --stat` — what files changed
   - `git log --oneline --since="4 hours ago"` — recent commits
   - Review the conversation history for decisions made, problems solved, features built

2. **Log to Notion Activity Log:**
   - Create one entry summarising the session's work
   - Name: concise description of what was accomplished
   - Category: infer from the work (Code / Design / Paper / etc.)
   - Date: today

3. **Update Notion Modules database:**
   - If any module moved to Done or a new one started, update the status
   - If a new module was created, add it

4. **Update Notion Decisions database:**
   - If any architectural or design decisions were made during this session, log them

5. **Update Notion Milestones:**
   - If progress was made toward a deadline, update the milestone notes

6. **Sync dev files:**
   - Update `STATUS.md` with what was done and what's next
   - Update `DECISIONS.md` if new decisions were made
   - Update `CONTEXT.md` if the project scope or state changed significantly

7. **Print session summary:**
   ```
   === Session Closed: [Project] ===
   Date: YYYY-MM-DD

   Work completed:
     - [bullet list from commits/conversation]

   Notion updated:
     ✓ Activity Log: "[entry name]"
     ✓ Module "[name]" → [new status]
     ✓ Decision logged: "[summary]"
     ✓ STATUS.md synced

   Next session:
     - [what to work on next, based on milestones and blockers]
   ```
