# /architecture — Auto-diagnose and document any project

Scan the current project, generate standardized architecture documentation, and organize files for maximum Claude efficiency. Based on industry benchmarks (C4 model, Arc42, Diátaxis, Stripe/Vercel internal practices).

## When to Use
- First time working on a project
- After major refactors
- When file organization is messy
- When context files are missing or outdated

## Steps

### Step 1: Diagnose Current State

Scan the project:
```bash
# Tech stack detection
ls package.json Cargo.toml pyproject.toml go.mod Makefile CMakeLists.txt *.sln requirements.txt setup.py 2>/dev/null

# Project size
find . -type f -not -path './.git/*' -not -path './node_modules/*' -not -path './.venv/*' -not -path './build/*' -not -path './dist/*' -not -path './__pycache__/*' | wc -l

# Directory structure
find . -maxdepth 2 -type d -not -path './.git/*' -not -path './node_modules/*' -not -path './.venv/*' | sort

# Git history
git log --oneline -20 2>/dev/null

# Existing docs
ls CLAUDE.md README.md .context/ docs/ ARCHITECTURE.md 2>/dev/null
```

### Step 2: Score Current Organization (0-10)

Rate these dimensions:

| Dimension | What to check | Score |
|-----------|--------------|-------|
| **File structure** | Are files grouped by feature/layer? Is there a clear hierarchy? | /10 |
| **Naming** | Consistent naming convention? Files match their purpose? | /10 |
| **Separation of concerns** | Are tests, docs, config, source clearly separated? | /10 |
| **Dead code** | Unused files, duplicate code, leftover experiments? | /10 |
| **Documentation** | CLAUDE.md, README, inline comments where needed? | /10 |
| **Context files** | .context/ directory with architecture, file-map, types? | /10 |
| **Build/test** | Clear build and test commands? CI config? | /10 |

Present the scorecard. This becomes the "before" baseline.

### Step 3: Propose File Reorganization

If score < 7 on file structure, propose a reorganized layout.

**Standard project structure (benchmark: Stripe, Vercel, Linear):**

```
project/
├── CLAUDE.md                    # Claude Code entry point (< 150 lines)
├── README.md                    # Human entry point
├── .context/                    # Claude context files (fast onboarding)
│   ├── INDEX.md                 # Table of contents for context files
│   ├── architecture.md          # System overview, data flows, C4 diagrams
│   ├── file-map.md              # Every source file with one-line description
│   ├── types.md                 # Key type/interface definitions
│   ├── patterns.md              # Coding patterns, conventions, gotchas
│   ├── decisions.md             # ADR-style architecture decision records
│   └── session-log.md           # Session history (optional, for multi-session)
├── src/                         # Source code (grouped by feature or layer)
├── tests/                       # Tests (mirror src/ structure)
├── docs/                        # Human-readable documentation
│   ├── api/                     # API docs
│   ├── design/                  # Design specs, wireframes
│   └── guides/                  # How-to guides
├── scripts/                     # Build, deploy, utility scripts
└── config/                      # Configuration files
```

**Context file format (benchmark: `.context/architecture.md`):**

```markdown
# Architecture — {Project Name}

## System Overview
{1-paragraph description}

## Tech Stack
| Layer | Technology | Purpose |
|-------|-----------|---------|
| ... | ... | ... |

## Data Flow
{How data moves through the system — text or ASCII diagram}

## Key Components
{3-5 most important modules/files with one-line descriptions}

## Boundaries
{Where does this system end? External dependencies, APIs, services}

## Constraints
{Performance requirements, security boundaries, deployment limits}
```

**Context file format: `.context/file-map.md`:**

```markdown
# File Map

## Source Files
| File | Purpose | Key exports |
|------|---------|-------------|
| src/main.py | Entry point | app |
| src/solver.py | Core algorithm | solve() |
| ... | ... | ... |

## Test Files
| File | Tests |
|------|-------|
| tests/test_solver.py | solve(), edge cases |
| ... | ... |
```

**Context file format: `.context/patterns.md`:**

```markdown
# Patterns & Conventions

## Naming
- Files: kebab-case
- Functions: camelCase
- Types: PascalCase

## Error Handling
{How errors are handled in this project}

## State Management
{How state flows — stores, contexts, etc.}

## Testing
{Test patterns, fixtures, mocking approach}
```

### Step 4: Generate Documentation

For each missing context file, generate it by reading the actual code:
1. Read key source files
2. Extract types, exports, patterns
3. Write the context file

**Quality bar:** A new Claude session should be able to read `.context/INDEX.md` and understand the project well enough to make changes without reading every file.

### Step 5: Clean Up

If the user approves:
- Move files to the proposed structure
- Remove dead/unused files (ask first if unsure)
- Consolidate duplicate files
- Add `.gitignore` entries for build artifacts
- Update imports if files moved

### Step 6: Re-score

Run the scorecard again. Show before/after:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ARCHITECTURE SCORECARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        Before  After
  File structure:        3/10   8/10
  Naming:                5/10   8/10
  Separation:            4/10   9/10
  Dead code:             6/10   9/10
  Documentation:         2/10   9/10
  Context files:         0/10   10/10
  Build/test:            7/10   9/10
  ─────────────────────────────────────
  TOTAL:                27/70  62/70
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Context File Quality Standards

Every `.context/` file must meet these criteria:
- **Current:** Reflects the actual code, not aspirational
- **Scannable:** Tables and bullet points, not paragraphs
- **Specific:** File paths, function names, type definitions — not vague descriptions
- **Actionable:** A new developer (or Claude) can start working after reading INDEX.md
- **Under 200 lines each:** If longer, split into sub-files

## When NOT to Reorganize

- If the project has CI/CD that depends on file paths — flag it, don't break it
- If the project is a library with published import paths — don't move public API files
- If there's active multi-person development — coordinate before restructuring
