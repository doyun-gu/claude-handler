# Template: Project Hub

Use this template when creating a new project documentation hub page.

---

## Notion Structure

```
# [Project Name]

[/table of contents]

---

[/callout — grey, no icon]
One-sentence description. What it does, what problem it solves, current stage.

Status: [Active / Paused / Complete]
Dev path: [/Developer/path/to/project]
[Deadline: YYYY-MM-DD — if applicable]
[/end callout]

---

## At a Glance

[/callout — blue, ℹ️]
Source: [where these numbers come from, e.g., "validated on IEEE test systems"]
[/end callout]

[Inline table — static metrics, NOT a database]
| Metric | Value |
|--------|-------|
| [Key metric 1] | [value] |
| [Key metric 2] | [value] |
| ... | ... |

[/toggle: "Detailed data"]
  [Extended tables, benchmark results, full numbers]
[/end toggle]

---

## Start Here

[/callout — grey, ℹ️]
New to this project? Read these pages in order.
[/end callout]

1. **[Page 1]** — [one-line description]
2. **[Page 2]** — [one-line description]
3. **[Page 3]** — [one-line description]

[/toggle: "Reading path for [audience 1]"]
  1. [Page] — [description]
  2. ...
[/end toggle]

[/toggle: "Reading path for [audience 2]"]
  1. [Page] — [description]
  2. ...
[/end toggle]

---

## Overview

2–3 paragraphs. Project scope, current state, goals.
Technical enough to onboard someone unfamiliar.
Plain language. No assumed context.

---

## Architecture

[/callout — grey, no icon]
One-line architecture summary.
[/end callout]

[/toggle: "System diagram"]
  [ASCII diagram or structured description of components and data flow]
[/end toggle]

Link to detailed architecture page if one exists.

---

## Documentation

[Linked database view → [Project] Docs database]
[Default: Table view, grouped by Category]

[Additional views: Board by Status, Gallery for audience, Needs Attention]

---

## Project Status

### Modules
[Linked database view → [Project] Modules DB]
[Board view — grouped by Status]

[/toggle: "Full module table"]
  [Linked database view → same DB, table view, all columns]
[/end toggle]

### Milestones
[Linked database view → Deadlines DB, filtered to this project]
[Timeline view]

[/toggle: "Milestone table"]
  [Same DB, table view]
[/end toggle]

### Decisions
[Linked database view → [Project] Decisions DB]
[List view — 10 most recent]

[/toggle: "Full decision history"]
  [Same DB, table view, all entries]
[/end toggle]

---

## [Project-specific sections]

[Add sections relevant to this project: API Reference, Core Concepts, etc.]
[Each links to or embeds the relevant sub-page or database view]

---

## Archive

[/toggle: "Archived and legacy content"]
  [Links to or database view filtered to Status = Archived]
[/end toggle]
```

---

## Databases to Create

When creating a new project hub, create these databases as children of the hub page:

1. **[Project] Docs** — documentation index (see schemas/docs-index.json)
2. **[Project] Modules** — component/feature tracking (see schemas/modules.json)
3. **[Project] Decisions** — architectural decisions (see schemas/decisions.json)

Also add entries to the global databases:
- **Projects** — add the new project entry
- **Deadlines** — add initial milestones if known
