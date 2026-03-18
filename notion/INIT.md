# Notion Workspace — First-Time Initialisation

You are setting up a Notion workspace for the first time with the documentation framework. This creates the foundational structure that all slash commands and templates depend on.

---

## Step 1 — Read the framework

Read these files before doing anything:
1. `notion/templates/FORMAT.md` — formatting rules
2. `notion/schemas/SCHEMAS.md` — database schemas
3. `notion/templates/project-hub.md` — project hub template

---

## Step 2 — Discover the workspace

Search Notion to find what already exists:
1. Search broadly to get all pages
2. Search for "project", "notes", "meeting", "readme", "tracker"
3. Map the hierarchy: pages, databases, structure

Print a brief summary.

---

## Step 3 — Detect projects

Scan the local filesystem for project directories:
- `~/Developer/`, `~/Projects/`, `~/Code/`
- The current working directory and parent

For each directory with a git repo, package.json, pyproject.toml, Makefile, or similar:
- Note the project name, tech stack, path

Present the list and ask:
> "I found these projects: [list]. Which should I create Notion hubs for? Or type 'all'."

Wait for confirmation.

---

## Step 4 — Create global databases

If they don't exist, create at workspace root:
1. **Projects** database (see `schemas/SCHEMAS.md`)
2. **Deadlines** database
3. **Activity Log** database

---

## Step 5 — Create Workspace Dashboard

Create "Workspace Dashboard" at workspace root:
1. Grey callout — "Central hub for all projects and activity."
2. Active Projects — linked DB view → Projects, Board by Status
3. Upcoming Deadlines — linked DB view → Deadlines, Timeline view
4. Recent Activity — linked DB view → Activity Log, List view, latest 15

---

## Step 6 — Create Workspace Style Guide

Create "Workspace Style Guide" at workspace root containing a summary of:
- Formatting rules from `templates/FORMAT.md`
- Database schemas from `schemas/SCHEMAS.md`

---

## Step 7 — Create project hubs

For each confirmed project:
1. Create hub page following `templates/project-hub.md`
2. Create databases: [Project] Docs, [Project] Modules, [Project] Decisions
3. Add entry to Projects database
4. Scan local directory for README or docs to populate the Overview
5. If no local docs, build Overview from tech stack detection

---

## Step 8 — Create dev context files

For each project, create if they don't exist:
```
[project-path]/
├── CONTEXT.md       — Project overview, goals, current state
├── ARCHITECTURE.md  — System design, components, data flow
├── DECISIONS.md     — Key technical decisions
└── STATUS.md        — Current milestone, recent changes, blockers
```

Populate from README, package.json, directory structure.

---

## Step 9 — Lecture tracking (optional)

Ask: "Do you want to set up lecture note tracking for any courses?"

If yes: create a Lectures database per course.

---

## Step 10 — Summarise

Log to Activity Log: "Workspace initialised"

Print:
```
=== Workspace Initialised ===

Global databases: Projects, Deadlines, Activity Log
Project hubs: [list]
Dev context files: [list]

Available commands:
  /notion-status all      — See all project statuses
  /notion-progress [p]    — Log work after a session
  /notion-done [p]        — End-of-session handoff
  /notion-doc [p] [topic] — Create a documentation page
  /notion-sync all        — Sync Notion ↔ dev files
```
