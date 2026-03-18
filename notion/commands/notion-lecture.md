---
description: Create a lecture note page from a course and topic
argument-hint: [course-code] [lecture topic]
---

You are creating a lecture note page. Read `notion/templates/FORMAT.md` for style rules and `notion/templates/lecture-notes.md` for the template.

## Steps

1. **Parse input.** First word of "$ARGUMENTS" is the course code. The rest is the lecture topic.

2. **Find the course's Lectures database.** Search Notion for "[course code] Lectures" database. If it doesn't exist, create it using the schema from `notion/schemas/SCHEMAS.md`.

3. **Check for duplicates.** Search the database for an existing entry with this topic. Don't create duplicates.

4. **Create the page** following the lecture-notes template:
   - Title: `[Course Code] — [Topic]`
   - Summary callout with course, date, week number
   - Key Concepts section (leave as placeholder headings for the user to fill)
   - Detailed Notes section (leave as placeholder)
   - Connections section
   - Questions & Gaps section
   - Resources section

5. **Add a database entry** to the Lectures database:
   - Name: [Course Code] — [Topic]
   - Status: Draft
   - Date: today
   - Tags: infer from the topic
   - Summary: "Lecture on [topic]"
   - Gaps: 0

6. **Log to Activity Log.**

7. **Print:** page created, database entry added, what to fill in.
