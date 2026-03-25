# Evaluation Criteria: Refactoring

## Scoring Rubric

### Behavioral Equivalence (40%)
- No observable behavior changes (same inputs produce same outputs)
- All existing tests pass without modification
- API surface is unchanged (or changes are documented and intentional)
- No new bugs introduced by the restructuring

### Code Quality Improvement (25%)
- The refactoring achieves its stated goal (extract module, rename, simplify, etc.)
- Reduced duplication or complexity where claimed
- Code is more readable or maintainable than before
- Naming is clear and consistent

### Test Coverage (20%)
- Existing tests still pass (no modifications needed indicates true refactor)
- If tests were modified, the changes are purely structural (not behavioral)
- Coverage is maintained or improved
- No tests deleted without replacement

### Completeness (15%)
- All references to renamed/moved items are updated
- No orphaned imports or dead code left behind
- Documentation updated if public API changed
- Commits are clean with descriptive messages

## Automatic FAIL Conditions

- Existing tests fail
- Observable behavior change (unless explicitly requested)
- Build does not compile
- Security vulnerability introduced
- Pushed to main instead of worker/ branch
- Deleted tests without equivalent replacement

## Evaluation Method

1. Verify ALL existing tests pass with zero modifications
2. Check that the refactoring goal is achieved (review diff structure)
3. Search for orphaned references to old names/paths
4. Verify no behavior changes by comparing test output before/after
