Force a full onboarding flow regardless of whether a CLAUDE.md already exists. This is useful when:
- You want to regenerate the project brief from scratch
- The project has changed significantly
- The existing CLAUDE.md feels stale or incomplete

Steps:

1. **Auto-scan the project** — detect tech stack, git history, directory structure, README, build/test scripts, file count. Present a summary of everything you find.

2. **Ask all onboarding questions** (even if some are detectable):
   - What's the product idea in one sentence?
   - Who is the target user?
   - What problem does this solve?
   - Any tech stack preferences or changes?
   - Commitment level — exploring / personal use / sharing / public launch?
   - Current priorities — what should we focus on?

3. **Generate a new CLAUDE.md** based on the scan + answers. If one already exists, show a diff of what would change and ask for confirmation before overwriting.

4. For larger projects (50+ files), suggest creating or updating `.context/` files for detailed documentation.
