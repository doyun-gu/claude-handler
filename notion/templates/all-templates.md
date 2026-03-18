# Template: Development Log

```
## YYYY-MM-DD — [Session Summary]

### Completed
- [What was built, fixed, or shipped]
- [Each item: specific, with file paths or commit refs where relevant]

### Decisions
- [Any technical decisions made, with brief rationale]

### Issues Found
- [Bugs discovered, edge cases, unexpected behaviour]

### Next Session
- [What to work on next]
- [Any blockers to address first]

### References
- Commits: [hash or branch]
- Files changed: [list key files]
```

---

# Template: Decision Record

```
# [Project] — Decision: [Summary]

[/callout — grey, no icon]
Date: YYYY-MM-DD | Status: Active / Superseded / Revisit
Superseded by: [link — if applicable]
[/end callout]

---

## Context

Why this decision was needed. What problem or choice we faced.
2–3 sentences.

---

## Decision

What we chose. 1–2 sentences, direct and specific.

---

## Alternatives Considered

### [Option A]
- Pros: ...
- Cons: ...
- Why rejected: ...

### [Option B]
- Pros: ...
- Cons: ...
- Why rejected: ...

---

## Consequences

What changes as a result of this decision.
What becomes easier. What becomes harder.
```

---

# Template: Meeting Notes

```
# [Meeting Title] — YYYY-MM-DD

[/callout — grey, no icon]
Attendees: [Name 1], [Name 2], [Name 3]
Duration: [X] minutes
[/end callout]

---

## Agenda

1. [Topic 1]
2. [Topic 2]
3. [Topic 3]

---

## Discussion

### [Topic 1]

[Key points, decisions, context]

### [Topic 2]

[Key points, decisions, context]

---

## Action Items

[These should be database entries in the project's Modules or a Tasks DB]

| Action | Owner | Due |
|--------|-------|-----|
| [Task] | [Person] | YYYY-MM-DD |
| [Task] | [Person] | YYYY-MM-DD |

---

## Decisions Made

- [Decision 1 — log to Decisions DB]
- [Decision 2 — log to Decisions DB]
```

---

# Template: Sprint Report

```
# Sprint Report — [Sprint Name or Dates]

[/callout — grey, no icon]
Sprint: YYYY-MM-DD to YYYY-MM-DD
Team: [who was involved]
[/end callout]

---

## Goals

What we set out to accomplish this sprint.
1. [Goal 1]
2. [Goal 2]
3. [Goal 3]

---

## Completed

[Linked database view → Modules DB, filtered to Status = Done,
Date within sprint range]

Or bullet list:
- [Feature/task] — [brief description of what shipped]
- ...

---

## Carried Over

Items not completed, moving to next sprint:
- [Item] — [reason not completed, current status]
- ...

---

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Items completed | [N] | [N] |
| Bugs fixed | [N] | [N] |
| Test coverage | [X]% | [X]% |

---

## Next Sprint Goals

1. [Goal 1]
2. [Goal 2]
3. [Goal 3]

---

## Retrospective

[/toggle: "What went well"]
  - ...
[/end toggle]

[/toggle: "What could improve"]
  - ...
[/end toggle]
```

---

# Template: Changelog

```
# [Project] — Changelog

Newest entries at the top.

---

## [Version] — YYYY-MM-DD

### Added
- [New feature or capability]

### Changed
- [Modification to existing behaviour]

### Fixed
- [Bug fix with brief description]

### Removed
- [Deprecated feature or code removed]

[/callout — yellow, ⚠️ — only if breaking changes]
Breaking changes: [description of what breaks and how to migrate]
[/end callout]
```

---

# Template: API Reference

```
# [Project] — API Reference

[/callout — yellow, ⚠️]
Base URL: [url]
Authentication: [method or "None"]
[/end callout]

---

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| [path] | [GET/POST/...] | [one-line description] |
| ... | ... | ... |

---

## [Endpoint Group or Individual Endpoint]

### [METHOD] [/path]

[One-line description]

[/toggle: "Request schema"]
  ```json
  {
    "field": "type — description",
    ...
  }
  ```
[/end toggle]

[/toggle: "Response schema"]
  ```json
  {
    "field": "type — description",
    ...
  }
  ```
[/end toggle]

[/toggle: "Example"]
  Request:
  ```bash
  curl -X POST [url]/[path] -H "Content-Type: application/json" -d '{...}'
  ```
  Response:
  ```json
  {...}
  ```
[/end toggle]

---

## Error Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request |
| 401 | Unauthorised |
| 404 | Not found |
| 422 | Validation error |
| 500 | Internal server error |
```
