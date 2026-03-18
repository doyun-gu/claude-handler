# Notion Workspace Discovery

Map the entire Notion workspace before restructuring. This is a read-only scan — no changes are made.

## Steps

### 1. Search broadly

Run multiple searches to find all pages:
1. Empty/broad query for recent and top-level pages
2. Search for: "project", "notes", "meeting", "tracker", "todo", "tasks", "planning", "architecture", "design", "readme", "log", "database"

### 2. Map the hierarchy

For each page found, record:
- Title, Parent, Type (page/database/sub-page), Last edited, Content summary

### 3. Identify databases

For databases: list all properties and types, count entries, note views.

### 4. Build the workspace map

```
📁 [Workspace Name]
├── 📄 Page Title (last edited: YYYY-MM-DD)
│   ├── 📄 Sub-page
│   └── 🗃️ Database [N entries]
└── ...
```

### 5. Save the map

Create a Notion page "Workspace Map — Auto-generated" with the full tree, database inventory, orphan page list, scan date, and counts.

### 6. Report

Print to terminal:
1. Workspace tree
2. Database inventory
3. Orphan pages
4. Recommendations for organisation

Ask: "Do you want me to restructure based on these findings?"
Wait for confirmation.
