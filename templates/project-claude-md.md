# Project Claude.md Template

This is a reference template for generating per-project `CLAUDE.md` files. The actual generation is handled by the global CLAUDE.md instructions — this file serves as a human-readable guide.

---

## Standard Structure (< 50 files)

```markdown
# Project Name

One-line description of what this project does.

## Tech Stack

- **Frontend:** React 19, TypeScript, Vite, Tailwind
- **Backend:** Node.js, Express, PostgreSQL
- **Testing:** Vitest, Playwright
- **Deploy:** Vercel, GitHub Actions

## File Structure

\`\`\`
src/
├── components/       # Reusable UI components
├── pages/            # Route pages
├── hooks/            # Custom React hooks
├── utils/            # Shared utilities
├── types/            # TypeScript types
└── styles/           # Global styles
\`\`\`

## Key Patterns

### State Management
- Zustand stores with Immer for immutable updates
- Each domain has its own store file

### API Layer
- All API calls go through `src/api/client.ts`
- Response types in `src/types/api.ts`

### Naming Conventions
- Components: PascalCase files, default exports
- Utilities: camelCase files, named exports
- Types: PascalCase, prefixed with `I` for interfaces

## Dev Commands

\`\`\`bash
npm run dev          # Start dev server
npm run build        # Production build
npm run test         # Run tests
npm run lint         # Lint + type check
\`\`\`

## Current State / Priorities

- [x] Auth flow complete
- [x] Dashboard page
- [ ] Settings page — in progress
- [ ] API rate limiting — next up
```

---

## Extended Structure (50+ files)

For larger projects, keep the root `CLAUDE.md` concise (under 150 lines) and use a `.context/` directory for depth:

```markdown
# Project Name

One-line description.

## Context Files — Read When Needed

| File | When to Read |
|------|-------------|
| [.context/architecture.md](.context/architecture.md) | System overview, data flows |
| [.context/file-map.md](.context/file-map.md) | Looking for a specific file |
| [.context/types.md](.context/types.md) | Need type/interface definitions |
| [.context/patterns.md](.context/patterns.md) | Coding patterns, conventions |
| [.context/api.md](.context/api.md) | API endpoints, request/response formats |

## Quick Reference

### Tech Stack
[Brief list]

### Key Routes / Endpoints
[Table of main routes]

### Dev Commands
\`\`\`bash
[Essential commands only]
\`\`\`

## Current State / Priorities
[What's active right now]
```

### Context File Guidelines

- **architecture.md** — system overview, component diagram (text-based), data flow, deployment architecture
- **file-map.md** — complete directory tree with one-line descriptions per file/directory
- **types.md** — key interfaces, enums, and type definitions (copy the actual code)
- **patterns.md** — coding conventions, state management approach, error handling strategy
- **api.md** — endpoint table, auth flow, request/response examples

---

## Tips for Good CLAUDE.md Files

1. **Lead with what matters.** Tech stack and dev commands should be findable in 5 seconds.
2. **Don't duplicate the README.** CLAUDE.md is for Claude's context, not human documentation.
3. **Include the non-obvious.** Gotchas, workarounds, and "why we do it this way" are high-value.
4. **Keep it current.** Outdated CLAUDE.md is worse than none — it causes incorrect assumptions.
5. **Tables over prose.** Routes, stores, commands — use tables for scannable reference data.
6. **Link, don't inline.** For large projects, link to `.context/` files instead of cramming everything into one file.
