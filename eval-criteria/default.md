# Evaluation Criteria: Default

Use this rubric when no task-type-specific criteria file matches.

## Scoring Rubric

### Correctness (40%)
- Does the implementation match the task requirements?
- Are all stated objectives addressed?
- Does the code compile/build without errors?
- Do existing tests still pass?

### Quality (25%)
- Code follows existing project patterns and conventions
- No introduced linting errors or type errors
- Error handling for likely failure modes
- No hardcoded values that should be configurable
- No obvious performance regressions

### Testing (20%)
- New functionality has corresponding tests
- Existing tests still pass
- Edge cases considered
- Tests are deterministic (no flaky assertions)

### Completeness (15%)
- All parts of the task are addressed
- No TODO/FIXME left unless explicitly scoped out
- Documentation updated if API surface changed
- Commits are clean with descriptive messages

## Automatic FAIL Conditions

Any of these triggers an instant FAIL regardless of score:

- Build does not compile or start
- Existing tests fail
- Security vulnerability introduced (exposed secrets, SQL injection, XSS, path traversal)
- Code pushed to main instead of worker/ branch
- User data or critical files deleted
- Dependency added with known critical CVE
