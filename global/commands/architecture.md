# /architecture — Diagnose and document any project

Scan the project, score its organization, generate missing context documentation, and optionally reorganize files for maximum Claude efficiency.

## Step 1: Diagnose

```bash
ls package.json Cargo.toml pyproject.toml go.mod Makefile CMakeLists.txt requirements.txt setup.py 2>/dev/null
find . -type f -not -path './.git/*' -not -path './node_modules/*' -not -path './.venv/*' -not -path './build/*' -not -path './dist/*' | wc -l
find . -maxdepth 2 -type d -not -path './.git/*' -not -path './node_modules/*' | sort
git log --oneline -20 2>/dev/null
ls CLAUDE.md README.md .context/ docs/ 2>/dev/null
```

## Step 2: Score (0–10 each)

| Dimension | What to check |
|-----------|--------------|
| File structure | Feature/layer grouping, clear hierarchy |
| Naming | Consistent convention, files match purpose |
| Separation | Tests, docs, config, source clearly separated |
| Dead code | Unused files, duplicates, leftover experiments |
| Documentation | CLAUDE.md, README, necessary inline comments |
| Context files | `.context/` with architecture, file-map, types |
| Build/test | Clear commands, CI config present |

Present the scores as the "before" baseline.

## Step 3: Propose Reorganization

If file structure < 7, propose a layout. Standard structure:
- `CLAUDE.md` — Claude entry point (< 150 lines)
- `README.md` — human entry point
- `.context/` — INDEX.md, architecture.md, file-map.md, types.md, patterns.md, decisions.md
- `src/` — source, grouped by feature or layer
- `tests/` — mirrors src/ structure
- `scripts/` — build, deploy, utility
- `config/` — configuration files

## Step 4: Generate Context Files

For each missing `.context/` file, read the actual code and generate it.

**`.context/architecture.md`** — system overview, tech stack table (Layer / Technology / Purpose), data flow, key components (3–5 with one-liners), external boundaries, constraints.

**`.context/file-map.md`** — table of every source file: path, purpose, key exports. Separate section for test files.

**`.context/patterns.md`** — naming conventions, error handling approach, state management, testing patterns.

**Quality bar:** A new Claude session should read `.context/INDEX.md` and understand the project well enough to make changes without reading every source file.

## Step 5: Clean Up (with approval)

- Move files to proposed structure
- Remove dead/unused files (ask if unsure)
- Consolidate duplicates
- Add `.gitignore` entries for build artifacts
- Update imports after any moves

Flag before touching: CI/CD-dependent paths, published library import paths, or projects with active multi-person development.

## Step 6: Re-score

Show before/after scores for all 7 dimensions and totals.

## Context File Standards

- **Current:** reflects actual code, not aspirational
- **Scannable:** tables and bullets, not paragraphs
- **Specific:** file paths, function names, types — not vague descriptions
- **Actionable:** new developer/Claude can start working after reading INDEX.md
- **Under 200 lines each:** split into sub-files if longer
