# /conversation-log — Review and process Claude Desktop conversation logs

Check the project's `.context/conversations/` directory for logged items from Claude Desktop sessions. Process them into actionable tasks, decisions, and notes.

## Steps

### Step 1: Scan conversation logs

```bash
ls -t .context/conversations/*.md 2>/dev/null
```

If no conversation directory exists, create it:
```bash
mkdir -p .context/conversations
```

### Step 2: Parse and categorize

Read each `.md` file. Items are tagged with categories:
- `[DECISION]` — Architecture/product decision made
- `[TASK]` — Something that needs to be built/fixed
- `[INSIGHT]` — Important observation or learning
- `[QUESTION]` — Unanswered question to investigate
- `[BUG]` — Bug identified during conversation
- `[NOTE]` — General note worth remembering

### Step 3: Process into actions

For `[TASK]` items:
- Check if already in a task queue
- If not: offer to create a dispatch task for the Mac Mini

For `[DECISION]` items:
- Check if documented in `.context/decisions.md`
- If not: append to decisions log

For `[BUG]` items:
- Check if in `DEBUG_DETECTOR.md`
- If not: add it

For `[QUESTION]` items:
- Present unanswered questions to the user

### Step 4: Show summary

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CONVERSATION LOG — {project}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📋 3 tasks → dispatch?
  📌 2 decisions → logged
  💡 1 insight → saved
  ❓ 1 question → needs answer
  🐛 1 bug → added to tracker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
