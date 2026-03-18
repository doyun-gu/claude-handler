Personalise the Technical Co-Founder to work better with this specific user. This command runs an adaptive interview and writes the result to `~/.claude/user-profile.md` — a standalone file that is read at every session startup.

**Important:** Do NOT write personal information to `global/CLAUDE.md` or any file inside this repo. The profile lives at `~/.claude/user-profile.md` only.

If the user provided arguments: `$ARGUMENTS` — use them as context and skip questions you can already answer from that info.

---

## If a Profile Already Exists

Before starting the interview, check if `~/.claude/user-profile.md` already exists.

If it does:
1. Read it and show a summary to the user.
2. Ask: "What would you like to update? Or say 'start over' to redo the full interview."
3. If they want to update specific fields, ask targeted questions for just those fields, then rewrite the file with the changes merged in.
4. If they say "start over", run the full interview below.

---

## Adaptive Interview

Ask questions **one round at a time**. Wait for answers before continuing. Adapt later rounds based on earlier answers.

### Round 1 — Identity (always ask)

> I'd like to learn about you so I can tailor how I work with you. Let's start:
>
> 1. **What's your role?** (e.g., solo founder, student, backend engineer, data scientist, designer who codes)
> 2. **How long have you been coding?** (and formal training vs self-taught?)
> 3. **What are you strongest in?** (languages, frameworks, domains)

### Round 2 — Adaptive Follow-ups

Based on Round 1 answers, pick the appropriate follow-up set. You may combine questions from multiple sets if the user's profile spans categories.

**If beginner (< 2 years, student, self-taught newcomer):**
> 4. **How much explanation do you want?** (just code / brief context / teach me as we go)
> 5. **What are you currently learning or want to learn?**
> 6. **Do you want me to suggest best practices, or just help you get things working?**

**If experienced engineer (2+ years, mid/senior role):**
> 4. **How do you feel about me pushing back on decisions?** (always challenge me / only on big things / just do what I ask)
> 5. **Testing philosophy?** (TDD / test after / test critical paths only / depends on context)
> 6. **What are you currently learning or exploring?**

**If founder / product person:**
> 4. **Speed vs quality — where are you right now?** (ship fast and iterate / balanced / production-grade from day one)
> 5. **How do you feel about me pushing back on decisions?** (always challenge me / only on big things / just do what I ask)
> 6. **Are you technical enough to review code, or do you trust me to make implementation calls?**

**If data scientist / ML engineer:**
> 4. **Do you prefer notebooks or scripts?**
> 5. **How much explanation do you want?** (just code / brief context / teach me as we go)
> 6. **What's your deployment context?** (research/exploration / production ML / analytics)

### Round 3 — Environment (always ask)

> Almost done — a few practical things:
>
> 7. **What's your primary OS?** (macOS / Linux / Windows+WSL)
> 8. **Preferred editor/IDE?** (VS Code, Neovim, JetBrains, Cursor, etc.)
> 9. **Tools or services you always use?** (Docker, Tailwind, specific databases, hosting providers, etc.)
> 10. **Commit style?** (I commit frequently / when features are done / remind me to commit)

### Round 4 — Hard Rules (always ask)

> Last one — any non-negotiable rules?
>
> 11. **Anything I should always do?** (e.g., always use TypeScript strict mode, always write tests first, always use conventional commits)
> 12. **Anything I should never do?** (e.g., never use classes, never add comments to obvious code, never use `any` type)

### Sufficiency Check

After Round 4, review what you've collected. If any of these critical fields are still unclear, ask a targeted follow-up:

- Role (must know)
- Experience level (must know)
- Explanation depth preference (must know — infer from experience if not explicitly stated)
- Pushback preference (must know — infer from role if not explicitly stated)

If all critical fields are covered, proceed to output.

---

## Output

1. **Generate the profile** using this format:

```markdown
# User Profile

Generated: [YYYY-MM-DD]

## Identity

- **Role:** [their role]
- **Experience:** [level, years, background]
- **Strongest areas:** [languages, frameworks, domains]
- **Currently learning:** [areas they're picking up]

## Work Style

- **Explanation level:** [just code / brief context / teach me]
- **Pushback level:** [always challenge / big things only / just do what I ask]
- **Speed vs quality:** [if discussed]
- **Testing philosophy:** [if discussed]
- **Commit style:** [frequent / feature-done / remind me]

## Environment

- **OS:** [their OS]
- **Editor:** [their editor/IDE]
- **Key tools:** [tools and services they use]

## Rules

### Always
- [things to always do]

### Never
- [things to never do]

## Notes
- [any other relevant context from the interview]
```

2. **Show the profile to the user** for review. Ask: "Does this look right? Anything to add or change?"

3. **After confirmation**, write the file to `~/.claude/user-profile.md`.

4. **Confirm** with: "Profile saved to `~/.claude/user-profile.md`. This will be loaded at the start of every session."
