# Pre-Commit Security Check

Before every commit that touches API routes, endpoints, or user-facing features:

**Ask: "Can this feature be called without authentication?"**

## Checklist

- [ ] New endpoint has auth middleware/decorator
- [ ] No hardcoded secrets, API keys, or tokens in the diff
- [ ] No `dangerouslySetInnerHTML` or unsanitized user input
- [ ] No `eval()`, `exec()`, or dynamic SQL
- [ ] File uploads validate type and size
- [ ] CORS settings not set to `*` in production
- [ ] No sensitive data in error messages or logs
- [ ] Rate limiting applied to new public endpoints

## When to block the commit

- Any API route missing authentication = BLOCK
- Any `.env`, credentials, or key file staged = BLOCK
- Any SQL string concatenation (use parameterized queries) = BLOCK

This is a one-line question that prevents post-deployment incidents.
