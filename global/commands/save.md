# /save — Save conversation log from Claude Desktop

Get content from user paste or `pbpaste`. Detect project from git root. Save to `.context/conversations/{date}-{topic}.md`.

Auto-process after saving: extract `[TASK]` (offer dispatch), `[DECISION]` (append to decisions.md), `[BUG]` (add to DEBUG_DETECTOR.md), `[QUESTION]` (show to user). Show confirmation with counts. Offer to commit if changes made.
