# Database Schema Reference

Claude Code reads this file to create consistent databases across any project. Every database follows these schemas exactly. Do not invent new property names — use the ones defined here.

---

## Global Databases (one per workspace)

### Projects

One entry per project in the workspace.

| Property | Type | Required | Values / Notes |
|----------|------|----------|----------------|
| Name | Title | Yes | Project name |
| Status | Select | Yes | Active / Paused / Complete / Archived |
| Phase | Text | Yes | Current phase (e.g., "Active dev", "Dissertation", "Maintenance") |
| Next Milestone | Text | No | What's coming next |
| Deadline | Date | No | Hard deadline if one exists |
| Dev Path | Text | No | Local filesystem path to project root |
| Notion Hub | URL | No | Link to the project hub page |

### Deadlines

Cross-project milestone and deadline tracker.

| Property | Type | Required | Values / Notes |
|----------|------|----------|----------------|
| Name | Title | Yes | What's due |
| Project | Relation → Projects | Yes | Which project |
| Date | Date | Yes | Due date |
| Status | Select | Yes | Upcoming (grey) / In Progress (blue) / Submitted (green) / Overdue (red) |
| Notes | Text | No | Additional context |
| Priority | Select | No | P0 / P1 / P2 / P3 |

### Activity Log

Timeline of all work across all projects. One entry per session or notable event.

| Property | Type | Required | Values / Notes |
|----------|------|----------|----------------|
| Name | Title | Yes | Brief description of what happened |
| Project | Relation → Projects | Yes | Which project |
| Date | Date | Yes | When it happened |
| Category | Select | Yes | Code / Paper / Hardware / Design / Admin / Research / Lecture |
| Tags | Multi-select | No | Freeform keywords |

---

## Per-Project Databases

### [Project] Docs

Documentation index. Every sub-page under a project hub gets an entry here.

| Property | Type | Required | Values / Notes |
|----------|------|----------|----------------|
| Name | Title | Yes | Page title |
| Category | Select | Yes | Project-specific (e.g., Engine / Web Platform / Math & Theory / API / Validation) |
| Type | Select | Yes | Overview / Concept / Reference / Log / Decision / Tutorial |
| Audience | Select | Yes | Everyone / Developer / Researcher / Advisor / Student |
| Status | Select | Yes | Current / Needs Update / Draft / Archived |
| Tags | Multi-select | Yes | Lowercase, hyphenated keywords |
| Summary | Text | Yes | One sentence describing what the page covers |
| Last Reviewed | Date | Yes | When last checked for accuracy |

### [Project] Modules

Component and feature tracker.

| Property | Type | Required | Values / Notes |
|----------|------|----------|----------------|
| Name | Title | Yes | Module or component name |
| Status | Select | Yes | Not Started / In Progress / Done / Blocked / Archived |
| Priority | Select | No | P0 / P1 / P2 / P3 |
| Category | Select | No | Project-specific grouping |
| Description | Text | No | What this module does |
| Key Files | Text | No | Paths to relevant source files |
| Last Updated | Date | No | When status last changed |

### [Project] Decisions

Architectural and technical decision log.

| Property | Type | Required | Values / Notes |
|----------|------|----------|----------------|
| Name | Title | Yes | Decision summary (concise) |
| Date | Date | Yes | When decided |
| Context | Text | Yes | Why this decision was needed |
| Decision | Text | Yes | What was chosen |
| Alternatives | Text | No | What was rejected |
| Status | Select | Yes | Active / Superseded / Revisit |

---

## Special-Purpose Databases

### [Course] Lectures

For academic/lecture note tracking.

| Property | Type | Required | Values / Notes |
|----------|------|----------|----------------|
| Name | Title | Yes | [Course Code] — [Topic] |
| Status | Select | Yes | Done / Draft / Review |
| Date | Date | Yes | Lecture date |
| Week | Number | No | Week number in term |
| Tags | Multi-select | Yes | Topic keywords |
| Summary | Text | Yes | One-sentence summary |
| Gaps | Number | No | Unresolved questions (0 = fully understood) |

---

## Creating Databases

When Claude Code creates a new database:

1. Use the exact property names and types from this schema
2. Set select option colours consistently:
   - Status: grey (Not Started), blue (In Progress), green (Done), red (Blocked), light grey (Archived)
   - Priority: red (P0), orange (P1), yellow (P2), grey (P3)
3. Create at least 2 views: a default table view and one contextual view (board, timeline, or gallery)
4. Name all views descriptively
5. Set appropriate default sorting and grouping
