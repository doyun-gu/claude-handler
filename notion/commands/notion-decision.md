---
description: Log a technical decision to the project's Notion Decisions database and local DECISIONS.md
argument-hint: [project-name] [decision summary]
---

You are logging a technical decision. Read `notion/NOTION.md` for conventions.

## Steps

1. **Parse the input.** First word of "$ARGUMENTS" is the project name. The rest is the decision summary.

2. **Ask for details** (only if not provided):
   - Context: Why was this decision needed?
   - Alternatives: What else was considered?
   - Rationale: Why this choice over the alternatives?

3. **Add to Notion.** Create an entry in the `[Project] Decisions` database:
   - Name: decision summary (concise)
   - Date: today
   - Context: why it was needed
   - Decision: what was chosen
   - Alternatives: what was rejected
   - Status: Active

4. **Update local DECISIONS.md.** Append to the project's `/Developer/[project]/DECISIONS.md`:
   ```markdown
   ## YYYY-MM-DD — [Decision Summary]

   **Context:** [why]
   **Decision:** [what]
   **Alternatives:** [rejected options]
   **Status:** Active
   ```

5. **Print confirmation** with the decision entry.
