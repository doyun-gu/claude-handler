# /save — Save conversation log from Claude Desktop

Receives a conversation log (pasted from Claude Desktop or from clipboard) and saves it to the right project location.

## Usage

User pastes a log block from Claude Desktop, or runs `/save` and Claude reads from clipboard.

## Steps

### Step 1: Get the log content

Check if the user pasted content directly. If not, read from clipboard:

```bash
pbpaste 2>/dev/null
```

### Step 2: Detect the project

Look at the current working directory to determine which project this is for:

```bash
basename "$(git rev-parse --show-toplevel 2>/dev/null)"
```

If not in a git repo, ask which project.

### Step 3: Ensure conversation directory exists

```bash
mkdir -p .context/conversations
```

### Step 4: Parse and save

If the content contains `---log---` markers, extract and save:

```bash
# Generate filename from date and first topic word
FILENAME=".context/conversations/$(date +%Y-%m-%d)-$(echo "$TOPIC" | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-30).md"
```

Write the content to the file.

### Step 5: Auto-process

After saving, immediately process the log:

1. Extract `[TASK]` items → offer to create dispatch tasks
2. Extract `[DECISION]` items → append to `.context/decisions.md`
3. Extract `[BUG]` items → check DEBUG_DETECTOR.md, add if new
4. Extract `[QUESTION]` items → show as "unanswered questions"

### Step 6: Confirm

```
Saved to: .context/conversations/2026-03-20-supervisor-feedback.md

Processed:
  📌 2 decisions → logged to .context/decisions.md
  📋 1 task → dispatch to Mac Mini? (y/n)
  🐛 1 bug → added to DEBUG_DETECTOR.md
```

### Step 7: Auto-commit (optional)

If there are changes:
```bash
git add .context/conversations/ .context/decisions.md
git commit -m "docs: conversation log — {topic}"
```

Only commit if the user approves or if auto-commit is enabled in their profile.
