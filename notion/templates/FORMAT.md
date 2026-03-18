# Notion Document Format Specification

This is the single source of truth for how every Notion page is written. Claude Code reads this file before creating or editing any page. Every template in `templates/` inherits from these rules.

---

## 1. Page Anatomy

Every Notion page has this skeleton. Not every section applies to every page type — templates define which sections are required.

```
[Page Icon]          ← Only on hub/root pages. None on sub-pages.
# Page Title         ← Set by Notion title field. Never repeated in body.

[/table of contents] ← Only on hub pages or pages with 5+ sections.

---

[/callout — grey]    ← One-line summary. What this page is and why it exists.
[/end callout]

---

## Section 1          ← H2 heading

Body text.

### Subsection 1.1    ← H3 heading (max depth)

Body text.

[/toggle: "Detail"]  ← Collapsible content that most readers skip.
  Detail content.
[/end toggle]

---

## Section 2

...
```

---

## 2. Text Formatting Rules

### Headings
- **H1:** Page title only (set by Notion, never in body)
- **H2:** Major sections. Use for top-level grouping.
- **H3:** Subsections within an H2. Maximum depth.
- **H4+:** Never. If you need H4, split into a sub-page.
- Never skip levels (no H1 → H3)
- Never use bold text as a fake heading

### Paragraphs
- 2–4 sentences maximum. One idea per paragraph.
- No wall-of-text paragraphs. If it's more than 4 sentences, split it.

### Emphasis
- **Bold:** Key terms on first introduction per page only. Never for general emphasis.
- *Italic:* File names, paths, variable names when not in code blocks. Also for figure captions or aside notes.
- ~~Strikethrough:~~ Never use.
- UPPERCASE: Never use for emphasis.

### Code
- **Code blocks:** Always specify language. Use for any multi-line code, commands, configurations.
- **Inline code:** For identifiers, file names, endpoints, CLI commands, config values. Example: `parser.py`, `/api/simulate`, `npm install`.

### Lists
- **Bullet lists:** Unordered items. Use when order doesn't matter.
- **Numbered lists:** Sequential steps only. Use when order matters.
- **Nesting:** Maximum one level deep. If you need deeper nesting, restructure.
- **Checklist/to-do:** Never in documentation pages. Use databases with Status property instead.

### Links
- Descriptive text only. Never raw URLs in body text.
- Link to related Notion pages when mentioning concepts that have their own page.
- External links get inline description: "the [Rim et al. 2025 paper](url) validated..."

### Dividers
- Use `---` (horizontal divider) between every major H2 section.
- Creates visual breathing room. Don't skip this.

---

## 3. Notion Block Types

### Callout Blocks (`/callout`)

| Style | Icon | Background | Use for |
|-------|------|------------|---------|
| Summary | None | Grey | Page summary at top. One-liner about what this page covers. |
| Info | ℹ️ | Grey | Contextual notes, prerequisites, "how to read this" guidance |
| Warning | ⚠️ | Yellow | Known limitations, breaking changes, things that can go wrong |
| Success | None | Green | Validated results, confirmed outcomes, things that are proven |
| Status | None | Blue | Current status banners, active development notices |

Rules:
- Maximum 2 callouts visible without scrolling (top summary + one info/warning)
- Never use callouts for regular body content
- Never use callouts for decoration
- Callout text: 1–3 sentences maximum

### Toggle Blocks (`/toggle`)

Use toggles to hide detail that most readers don't need but some do:
- Detailed derivations behind a summary
- Full data tables behind a summary row
- Per-item breakdowns (e.g., per-bus validation results)
- Example code and request/response schemas
- FAQ-style expandable answers
- Historical context or background

Toggle heading rules:
- Must be descriptive enough that a reader knows whether to expand without expanding
- Good: "Detailed benchmark results for IEEE 118-bus"
- Bad: "More info" or "Details"

### Database Views (`/linked view of database`)

| View | When to use |
|------|-------------|
| Table | Default for structured data. Sortable, filterable. |
| Board | Status tracking. Kanban columns: Not Started / In Progress / Done / Blocked. |
| Gallery | Visual browsing. Cards with title + summary + tags. |
| Timeline | Date-based milestones. Shows sequence and duration. |
| List | Compact index. Title + one property. Minimal metadata. |

Rules:
- Every database on a hub page should have at least 2 views
- Default view should be the most useful for the primary audience
- Name every view descriptively (not "View 1")
- Set appropriate filters and grouping for each view

### Tables (Inline)

Use inline tables (not databases) for:
- Static reference data that doesn't change (e.g., notation glossary)
- Metrics summaries (e.g., "At a Glance" numbers)
- Comparison matrices
- API endpoint summaries

Never use inline tables for trackable data (use databases instead).

### Equations (`/equation`)

**Block equations** (centred, standalone):
- Core formulations and derivations
- Any equation that defines how something works
- System of equations

**Inline equations** (within text):
- Variable references: "where $\omega$ is the angular frequency"
- Short expressions: "the threshold $\epsilon = 10^{-6}$"
- Values with units: "$V = 1.0$ pu"

Notation must be consistent within a project. Define a notation table on the project hub or the first technical page.

### Synced Blocks (`/synced block`)

Use when the same content must appear identically on multiple pages:
- Metrics tables that appear on both hub and detail pages
- Standard disclaimers or status banners
- Shared navigation links

---

## 4. Page Types and Their Required Sections

### Project Hub
Required: Summary callout, Overview, Architecture, Modules DB, Milestones DB, Decisions DB, Sub-pages list
Optional: At a Glance metrics, Start Here guide, API Quick Reference, Core Concepts
Template: `templates/project-hub.md`

### Technical Concept
Required: Summary callout, Prerequisites callout, Problem/Motivation, Core Explanation (with equations), Practical Impact
Optional: Comparison table, Toggle derivations, References
Template: `templates/technical-concept.md`

### API Reference
Required: Warning callout (base URL, auth), Endpoints table, Per-endpoint details (in toggles), Error codes
Optional: Example request/response, Rate limits, Authentication
Template: `templates/api-reference.md`

### Development Log
Required: Date header, What was done (bullet list), Decisions made, Next steps
Optional: Commits referenced, Files changed, Blockers
Template: `templates/dev-log.md`

### Decision Record
Required: Date, Context (why), Decision (what), Alternatives (rejected), Status
Optional: Consequences, Review date
Template: `templates/decision-record.md`

### Lecture Notes
Required: Course, Date, Topic, Summary callout, Key Concepts, Detailed Notes
Optional: Equations, Examples, Practice problems, References, Related lectures
Template: `templates/lecture-notes.md`

### Meeting Notes
Required: Date, Attendees, Agenda, Discussion, Action items (as database entries)
Optional: Decisions made, Follow-ups
Template: `templates/meeting-notes.md`

### Sprint Report
Required: Sprint dates, Goals, Completed, Carried over, Metrics, Next sprint goals
Optional: Blockers, Retrospective notes
Template: `templates/sprint-report.md`

### Changelog
Required: Version, Date, Added/Changed/Fixed/Removed sections
Optional: Breaking changes callout, Migration notes
Template: `templates/changelog.md`

---

## 5. Database Standards

### Property Naming

Use these exact property names across ALL databases. This enables cross-database filtering and consistency.

| Property | Type | Standard Values |
|----------|------|-----------------|
| Name | Title | — |
| Status | Select | Not Started (grey) / In Progress (blue) / Done (green) / Blocked (red) / Archived (light grey) |
| Priority | Select | P0 Critical / P1 High / P2 Medium / P3 Low |
| Category | Select | Project-specific |
| Type | Select | Document-type-specific |
| Audience | Select | Everyone / Developer / Researcher / Advisor / Student |
| Date | Date | ISO format (YYYY-MM-DD) |
| Due | Date | Deadline date |
| Owner | Person | Assignee |
| Tags | Multi-select | Lowercase, hyphenated |
| Summary | Text | One sentence |
| Notes | Text | Additional context |
| Link | URL | External reference |
| Last Reviewed | Date | When last checked for accuracy |

### Tag Rules

- All lowercase
- Hyphenated for multi-word: `power-flow`, `bug-fix`, `lecture-notes`
- No duplicates: pick one canonical form per concept
- No overly generic tags: don't use `code`, `work`, `important`
- Tags should be filterable: a reader should be able to click a tag and find all related pages

### Database View Naming

Name views as: "[What it shows]" — not "View 1", "Table 2", etc.
Examples: "All Docs", "Board by Status", "For Developers", "Needs Attention", "This Week"

---

## 6. Writing Style

### Tone
- Technical and concise. No fluff, no filler.
- Third-person or first-person plural: "the engine validates" or "we implemented"
- Never chatbot-style: no "In this section we will explore..." or "Let's dive into..."
- Write as a senior engineer documenting their own system

### Lead with action
- Good: "Solves Newton-Raphson power flow for IEEE bus systems"
- Bad: "This is a module for power system simulation"

### Specifics over generalities
- Good: "4–6 iterations to converge on IEEE 14-bus with flat start"
- Bad: "Converges quickly on standard test systems"

### Date everything
- Log entries, decisions, status updates: always ISO date
- Bug fixes: include when discovered and when fixed
- Validation results: include when the test was run

### Acronyms
- Spell out on first use per page: "Instantaneous Dynamic Phasor (IDP)"
- After first use, abbreviation only: "IDP"
- Common exceptions that don't need spelling out: API, URL, HTML, CSS, JSON, SQL

---

## 7. Co-Founder Perspective

This isn't note-taking. This is building a knowledge base that serves the team.

### Every page must answer:
1. **What is this?** (summary callout — 1 sentence)
2. **Why does it matter?** (first paragraph of Overview or Motivation)
3. **How does it work?** (body content, equations, architecture)
4. **What's the current status?** (database views, status callouts)
5. **Where do I go next?** (cross-links, navigation callouts, related pages)

### Quality bar:
- Would a new team member understand this page without asking questions?
- Would an investor/advisor get the key message in 30 seconds from the summary?
- Would a developer find the exact technical detail they need within 2 clicks?
- Would you be embarrassed to share this page externally?

If any answer is no, the page isn't done.
