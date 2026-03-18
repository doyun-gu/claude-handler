---
description: Create a new documentation page under a project hub following the style guide
argument-hint: [project-name] [page topic]
---

You are creating a new documentation page. Read `notion/templates/FORMAT.md` for style rules.

## Steps

1. **Parse input.** First word of "$ARGUMENTS" is the project. The rest is the page topic.

2. **Read the project hub page** to understand what already exists. Don't duplicate.

3. **Pick the right template** from `notion/templates/`:
   - Technical/math topic → `technical-concept.md`
   - API documentation → `all-templates.md` (API Reference section)
   - General documentation → follow FORMAT.md rules

4. **Create the page** under the project hub with:
   - Title: `[Project] — [Topic]`
   - Navigation callout at top linking to related pages
   - H2/H3 heading structure
   - Horizontal dividers between sections
   - KaTeX equations if technical
   - No emoji

5. **Add an entry** to the project's Docs database with:
   - Category, Type, Audience, Tags, Summary
   - Status = "Current", Last Reviewed = today

6. **Update the hub page** sub-pages section if needed.

7. **Log to Activity Log database.**

8. **Print:** what was created, where it lives, tags applied.
