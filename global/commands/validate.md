# /validate — Quality Gate for Worker Output

You are the Commander (MacBook Pro). This command validates that a Worker's completed task actually meets the requirements before you merge it.

## Steps

### Step 1: Identify what to validate

If the user specifies a task slug or PR number, use that. Otherwise, find the latest completed Worker task:

```bash
ls -t ~/.claude-fleet/tasks/*.json | head -5
```

Read the task manifest to get:
- The original prompt/spec (from `prompt_file` or `prompt`)
- The branch name
- The project

### Step 2: Extract acceptance criteria from the original spec

Read the dispatch prompt file. Extract every requirement, fix, and "must have" into a numbered checklist.

### Step 3: Checkout and test

```bash
cd <project_path>
git checkout <worker_branch>
```

For each acceptance criterion:
1. **Read the code** — verify the change was actually made (not just superficial)
2. **Run the relevant test** — build, test, or visually verify
3. **Grade: PASS / PARTIAL / FAIL** with evidence

### Step 4: Present validation report

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VALIDATION REPORT — {task_slug}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Overall: {PASS / FAIL} ({pass_count}/{total} criteria met)

  #  Criterion                          Status    Evidence
  ── ──────────────────────────────── ─────── ──────────
  1  Label overlap fixed               ❌ FAIL  Labels still overlap at Bus 5
  2  Animation visible                 ⚠️ PARTIAL Arrows bigger but no dash animation
  3  AI chat wired to Cmd+Shift+Click  ❌ FAIL  No context appears in chat
  ...

  VERDICT: {MERGE / RE-DISPATCH / CLOSE}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 5: Action

Based on the verdict:
- **MERGE**: All criteria pass → offer to merge the PR
- **RE-DISPATCH**: Multiple failures → create a new task with specific fixes needed, referencing exactly what failed and why
- **CLOSE**: Work is wrong direction → close PR, create fresh task

When re-dispatching, include:
1. The original spec
2. What specifically failed validation
3. Code excerpts showing what needs to change
4. "The previous attempt made superficial changes. This time, verify each fix by running the app and checking visually."
