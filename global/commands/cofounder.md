Personalise the Technical Co-Founder. Writes result to `~/.claude/user-profile.md` (read at every session startup). **Never** write personal info to files inside this repo.

If `$ARGUMENTS` provided, use as context — skip questions you can already answer.

## If Profile Exists

Check `~/.claude/user-profile.md`. If exists: show summary, ask what to update (or "start over" for full interview).

## Adaptive Interview

Ask **one round at a time**, wait for answers, adapt later rounds.

**Round 1 — Identity:** Role? Coding experience (years, formal/self-taught)? Strongest areas?

**Round 2 — Adaptive** (pick based on Round 1):
- *Beginner*: Explanation depth? Currently learning? Best practices or just get it working?
- *Experienced*: Pushback preference? Testing philosophy? Currently exploring?
- *Founder*: Speed vs quality? Pushback preference? Technical enough to review code?
- *Data/ML*: Notebooks or scripts? Explanation depth? Deployment context?

**Round 3 — Environment:** OS? Editor/IDE? Key tools/services? Commit style?

**Round 4 — Rules:** Always do? Never do?

Ensure you have: role, experience level, explanation depth, pushback preference. Infer from context if not explicit.

## Output

Generate profile with sections: Identity (role, experience, strengths, learning), Work Style (explanation, pushback, speed/quality, testing, commits), Environment (OS, editor, tools), Rules (always/never), Notes. Show for review, write to `~/.claude/user-profile.md` after confirmation.
