# /document-release — Post-Ship Documentation Update

You are updating project documentation after code has shipped. This command detects doc changes, updates the CHANGELOG, and optionally cuts a patch release.

## Steps

### Step 1: Detect the last release tag

```bash
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
```

If no tags exist, use the initial commit as the baseline:
```bash
LAST_TAG=$(git rev-list --max-parents=0 HEAD)
```

Read the current version from `VERSION` file if it exists.

### Step 2: Find doc changes since last release

Check for documentation changes since the last tag:

```bash
git diff --name-only "$LAST_TAG"..HEAD -- docs/ '*.md' README.md CLAUDE.md
```

Also check for doc-related commits:
```bash
git log --oneline "$LAST_TAG"..HEAD --grep="^docs:" --grep="^doc:" --grep="documentation" --grep-reflog=
```

### Step 3: Present a doc change summary

List what documentation changed, grouped by type:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DOC CHANGES since v{last_version}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  New docs:
    + docs/ARCHITECTURE.md
    + docs/ERROR-CODES.md

  Updated docs:
    ~ README.md (3 sections changed)
    ~ CLAUDE.md (file structure updated)

  Deleted docs:
    - docs/old-guide.md

  No changes:   docs/API-REFERENCE.md, docs/CONVERSATION-LOGGING.md
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 4: Cross-reference docs against current code

For each doc that existed before this release, quickly check for staleness:

1. **README.md** — Do install commands still work? Do listed features match reality?
2. **CLAUDE.md** — Does the file structure section match actual files? Are dev commands current?
3. **docs/*.md** — Scan for references to files/functions that no longer exist.

Flag any stale sections found:
```
⚠️  README.md references `fleet-brain.py` but file was renamed to `fleet-brain.py.disabled`
⚠️  docs/API-REFERENCE.md lists endpoint /api/budget but it was removed
```

### Step 5: Update CHANGELOG.md

If `CHANGELOG.md` exists, add entries under `[Unreleased]` for any doc changes not already captured:

```markdown
### Documentation
- {description of doc change} ({date})
```

Follow the [Keep a Changelog](https://keepachangelog.com/) format. Do not duplicate entries already in the CHANGELOG.

If `CHANGELOG.md` does not exist, offer to create one using the project's git history.

### Step 6: Fix stale docs

For each stale section found in Step 4, update the documentation to match the current state of the code. Make minimal, accurate edits — do not rewrite entire documents.

Commit each doc fix atomically:
```bash
git add <file>
git commit -m "docs: update {file} — {what changed}"
```

### Step 7: Optional patch release

If doc changes are significant (new guides, major rewrites), offer to bump the patch version:

1. Read current version from `VERSION`
2. Bump patch: `0.5.0` → `0.5.1`
3. Show what `./release.sh` would do (dry run)
4. Ask if the user wants to proceed

If running as a Worker (autonomous mode), do NOT cut the release — just update the CHANGELOG and commit. The Commander decides when to release.

### Step 8: Summary

Present what was done:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DOC RELEASE COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Docs updated:    3
  Stale refs fixed: 2
  CHANGELOG entries: 5 added
  Version:         0.5.0 (no bump)

  Commits:
    abc1234 docs: update README — fix install command
    def5678 docs: update CHANGELOG with doc entries
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
