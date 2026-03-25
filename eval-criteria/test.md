# Evaluation Criteria: Test Suite

## Scoring Rubric

### Coverage (35%)
- New tests cover the functionality described in the task
- Edge cases are tested (boundary values, empty inputs, error paths)
- Both happy path and failure path tested
- Integration points tested (not just unit isolation)

### Correctness (30%)
- Test assertions are meaningful (not just "doesn't throw")
- Expected values are correct (verified against specification or manual calculation)
- Tests actually exercise the code under test (not testing mocks)
- Setup/teardown is correct (no test pollution)

### Reliability (20%)
- Tests are deterministic (same result every run)
- No timing-dependent assertions (sleep, setTimeout)
- No dependency on external services without mocking
- Random seeds fixed where randomness is involved
- Tests can run in any order

### Quality (15%)
- Test names describe the scenario and expected behavior
- Arrange-Act-Assert pattern followed
- No excessive duplication (shared fixtures where appropriate)
- Tests are readable without comments

## Automatic FAIL Conditions

- New tests fail (they must pass)
- Existing tests broken by the changes
- Tests are flaky (pass sometimes, fail sometimes)
- Build does not compile
- Pushed to main instead of worker/ branch

## Evaluation Method

1. Run the full test suite -- all tests must pass
2. Review test assertions for meaningfulness
3. Check that tests cover the scenarios described in the task
4. Verify tests are deterministic (run twice, same result)
