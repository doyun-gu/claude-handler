# Evaluation Criteria: Bug Fix

## Scoring Rubric

### Root Cause (40%)
- The actual root cause is identified and fixed, not just the symptom
- The fix addresses the underlying issue described in the task
- No workarounds or band-aids that mask the problem
- The fix is in the right layer (not patching the caller for a callee bug)

### Regression Prevention (25%)
- A regression test is added that would have caught the original bug
- The test fails before the fix and passes after
- The test covers the specific scenario described in the bug report
- Related edge cases are tested

### Side Effects (20%)
- The fix does not break existing functionality
- All existing tests still pass
- No unintended behavior changes in adjacent code
- Performance is not degraded

### Minimality (15%)
- The diff is focused on the fix (no unrelated changes)
- The fix is the simplest correct solution
- No unnecessary refactoring bundled with the fix
- Commits are clean with descriptive messages

## Automatic FAIL Conditions

- The specific bug described in the task is NOT fixed
- Build does not compile
- Existing tests fail
- New security vulnerability introduced
- Fix causes a different bug of equal or greater severity
- Pushed to main instead of worker/ branch

## Evaluation Method

1. Understand the bug from the task description
2. Review the diff -- does it address the root cause?
3. Check that a regression test exists for this specific bug
4. Verify all existing tests pass
5. Look for unintended side effects in the changed code paths
