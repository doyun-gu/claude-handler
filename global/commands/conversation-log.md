# /conversation-log — Process Claude Desktop conversation logs

Scan `.context/conversations/*.md` for logged items. Create directory if missing.

## Categories
`[DECISION]` `[TASK]` `[INSIGHT]` `[QUESTION]` `[BUG]` `[NOTE]`

## Actions
- **TASK**: Check if in queue → offer to dispatch to Mac Mini
- **DECISION**: Check `.context/decisions.md` → append if missing
- **BUG**: Check `DEBUG_DETECTOR.md` → add if new
- **QUESTION**: Present unanswered to user

Show summary with counts per category and actions taken.
