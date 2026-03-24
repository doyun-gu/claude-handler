I'm done working on this machine and need to save everything so I can continue on another machine or in another session. Do ALL of the following steps in order:

## Step 1: Generate HANDOFF.md

Write `~/.claude-fleet/HANDOFF.md` with today's session summary. This is the **first thing** the next session reads.

```markdown
# Handoff — {YYYY-MM-DD}

Machine: {hostname}
Session ended: {HH:MM}

## Completed Today
- [x] {task description} ({project name})

## Still Pending
- [ ] {task description} ({project name}) — {brief context why it's not done}

## Decisions Made
- {any decisions or direction changes not captured in code}

## Blockers / Waiting On
- {anything blocked and why, or "None"}

## Notes for Next Session
- {what to pick up first, any gotchas, user requests not yet started}
```

To populate this:
- Review the conversation for what was accomplished and what wasn't
- Check the task list (if TaskCreate was used) for pending items
- Include direction changes and user requests that aren't in code yet
- Keep it concise — quick-reference, not a journal

## Step 2: Update project WORKSTATE (if applicable)

If the current working directory has `.context/WORKSTATE.md`, update it:
- Mark completed tasks with `[x]`
- Add any new tasks discovered during this session
- Update "In Progress" and "Next" sections

## Step 3: Save memories

Scan the conversation for unsaved memories. Look for:
- **Feedback**: corrections, confirmations, preferences ("don't do X", "always do Y")
- **Project**: decisions, priorities, deadlines, blockers
- **User**: new info about skills, role, goals
- **Reference**: external tools, URLs, systems

Only save things that are **non-obvious and useful across sessions**. Deduplicate against the user's memory index (MEMORY.md). Update existing memories rather than creating duplicates.

## Step 4: Commit and push ALL touched projects

For **every project that has uncommitted changes** (not just the current directory):

1. `git status` to identify changes
2. Stage relevant files (exclude .env, credentials, secrets)
3. Commit with a descriptive message
4. Push to remote
5. Confirm success

Check these locations:
- Current working directory
- Any other project directory you modified during the session
- `~/Developer/my-world` (if HANDOFF.md is synced there)

## Step 5: Sync HANDOFF.md to shared location

Copy HANDOFF.md into my-world so it syncs across machines:

```bash
cp ~/.claude-fleet/HANDOFF.md ~/Developer/my-world/HANDOFF.md 2>/dev/null
cd ~/Developer/my-world && git add HANDOFF.md && git commit -m "handoff: $(date +%Y-%m-%d)" && git push origin main 2>/dev/null
```

Also run memory sync if available:
```bash
~/Developer/claude-handler/memory-sync.sh sync 2>/dev/null
```

## Step 6: Report

Show a compact summary:

```
── Session Handoff ──────────────────────────
Completed:  {N} tasks
Pending:    {N} tasks
Memories:   {N saved/updated}
Projects pushed:
  ✓ {project} — {commit message}
  ✓ {project} — {commit message}
HANDOFF.md: ✓ saved + synced
──────────────────────────────────────────────
```
