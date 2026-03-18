Personalise the Technical Co-Founder to work better with this specific user. This command gathers information through conversation and appends a `## User Profile` section to the global CLAUDE.md.

If the user provided arguments: `$ARGUMENTS` — use them as context and skip questions you can already answer from that info.

If no arguments provided, run the full interview below.

---

## Interview Flow

Ask these questions **one group at a time** (not all at once). Wait for answers before continuing.

### Group 1: Role & Expertise

> I'd like to learn about you so I can tailor how I work with you. Let's start with the basics:
>
> 1. **What's your role?** (e.g., solo founder, student, backend engineer, data scientist, designer who codes)
> 2. **What's your experience level?** (years coding, self-taught vs formal, junior/mid/senior)
> 3. **What languages/frameworks are you strongest in?** (and which are you learning?)

### Group 2: Work Style

> Now about how you like to work:
>
> 4. **How much explanation do you want?** (just code / brief context / teach me as we go)
> 5. **How do you feel about me pushing back?** (always challenge me / only on big things / just do what I ask)
> 6. **Commit style?** (I commit frequently / I commit when features are done / remind me to commit)

### Group 3: Environment & Tools

> Almost done — a few practical things:
>
> 7. **What's your primary OS?** (macOS / Linux / Windows+WSL)
> 8. **Preferred editor/IDE?** (VS Code, Neovim, JetBrains, etc.)
> 9. **Any tools/services you always use?** (Docker, Tailwind, specific databases, hosting providers)

### Group 4: Preferences (Optional)

> Last one — any pet peeves or preferences?
>
> 10. **Anything I should always do?** (e.g., always use TypeScript strict, always write tests first)
> 11. **Anything I should never do?** (e.g., never use classes, never add comments to obvious code)
> 12. **Anything else I should know about how you work?**

---

## After the Interview

1. **Read the current global CLAUDE.md** at `~/.claude/CLAUDE.md` (or the symlink target).

2. **Generate a `## User Profile` section** based on the answers. Format:

```markdown
## User Profile

- **Role:** [their role]
- **Experience:** [level + strongest areas]
- **Learning:** [what they're currently picking up]
- **Explanation level:** [their preference]
- **Pushback level:** [their preference]
- **OS / Editor:** [environment]
- **Key tools:** [tools they always use]

### Always
- [things to always do]

### Never
- [things to never do]

### Notes
- [any other relevant context]
```

3. **Show the generated section** to the user for review before writing.

4. **Append it to the global CLAUDE.md** — place it after the `## Guardrails` section and before `## Session Startup Protocol`. Do NOT overwrite anything else.

5. **Confirm** with a one-liner like: "Co-founder personalised. This will apply to all future sessions."

---

## If User Profile Already Exists

If the global CLAUDE.md already has a `## User Profile` section:
- Show what's currently there
- Ask what they'd like to update
- Replace only the User Profile section, leaving everything else intact
