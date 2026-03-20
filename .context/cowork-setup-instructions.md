# Cowork Setup — Paste These Into Claude Desktop

Open Claude Desktop on Mac Mini → Infrastructure project → paste each block as a separate message.

## Message 1: Fleet Monitor (every 30 min)

Schedule a recurring task every 30 minutes: Read all JSON files in /Users/doyungu/.claude-fleet/tasks/ directory. Count tasks by status (queued, running, completed, failed). Read all .md files in /Users/doyungu/.claude-fleet/review-queue/ directory. Write a compact summary to /Users/doyungu/.claude-fleet/daily-summary.md with format:

Fleet Status — {timestamp}
Running: {count} | Queued: {count} | Completed: {count} | Failed: {count}
Review items: {count}
{list each running task name and project}
{list each review item type and name}

If any task changed status since last check, also write to /Users/doyungu/.claude-fleet/review-queue/cowork-digest.md so the email notification system picks it up.

## Message 2: Bug Detector (every 2 hours)

Schedule a recurring task every 2 hours: Read /Users/doyungu/Developer/dynamic-phasors/DPSpice-com/DEBUG_DETECTOR.md. Count bugs with status NEW. If any new bugs found, write a one-line summary to /Users/doyungu/.claude-fleet/review-queue/cowork-bugs.md with the bug slugs and descriptions.

## Message 3: Conversation Log Processor (every 1 hour)

Schedule a recurring task every 1 hour: Check all .context/conversations/ directories across these projects for new files modified in the last hour:
- /Users/doyungu/Developer/dynamic-phasors/DPSpice-com/.context/conversations/
- /Users/doyungu/Developer/claude-handler/.context/conversations/
- /Users/doyungu/Developer/project-JULY/rp5-software/.context/conversations/

For any new conversation logs found, extract [TASK] items with priority P0 or P1 and write them as task manifests to /Users/doyungu/.claude-fleet/tasks/ with status queued. Extract [DECISION] items and append them to the project's .context/decisions.md file.

## Message 4: Daily Digest (every day at 9am)

Schedule a daily task at 9:00 AM: Read all task manifests, review queue items, and conversation logs from the past 24 hours. Write a comprehensive daily digest to /Users/doyungu/.claude-fleet/daily-digest.md with sections: Completed Yesterday, Running Now, Queued, Decisions Made, Open Questions, Bugs. Keep it under 50 lines.
