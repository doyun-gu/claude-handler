---
description: Audit a project's Notion docs for style issues, stale content, and missing sections
argument-hint: [project-name]
---

You are auditing documentation quality for "$ARGUMENTS". Read `notion/NOTION.md` for the style guide and hub template.

## Steps

1. **Read the project hub page.** Check against the hub template:
   - Has: quote summary, dev path, status, overview, architecture, modules DB, milestones DB, decisions DB, sub-pages list?
   - Missing sections?

2. **Read every sub-page** under this project hub. For each page check:
   - Title follows `[Project] — [Topic]` convention?
   - Heading hierarchy correct (H2 → H3, no skips, no H4+)?
   - No inline emoji in headings or body text?
   - Code blocks have language specified?
   - Bold used only for key terms, not emphasis?
   - Has a navigation callout at the top linking to related pages?
   - Content is current (no references to APEC, outdated data)?

3. **Check databases:**
   - All entries have Status set?
   - Any "In Progress" items older than 30 days?
   - Any missing Tags?
   - Last Reviewed dates — anything older than 60 days?

4. **Check dual-layer sync:**
   - Read the local dev files (CONTEXT.md, STATUS.md, etc.)
   - Compare with Notion content
   - Flag any contradictions or drift

5. **Print audit report:**

```
=== [Project] Documentation Audit ===

Hub page:
  ✓ All template sections present
  ⚠ Missing: [section]

Sub-pages: [N] total
  ✓ [N] pass style guide
  ⚠ [N] issues found:
    - [Page] — [issue description]
    - [Page] — [issue description]

Databases:
  ⚠ [N] entries with no Tags
  ⚠ [N] "In Progress" items older than 30 days
  ✓ Decisions database current

Sync status:
  ⚠ STATUS.md mentions [thing] not in Notion
  ✓ CONTEXT.md matches hub page

Recommended actions:
  1. [action]
  2. [action]
```
