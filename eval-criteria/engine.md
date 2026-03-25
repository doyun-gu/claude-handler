# Evaluation Criteria: Engine / Solver / Algorithm

## Scoring Rubric

### Numerical Accuracy (35%)
- Results match reference values within stated tolerance
- IEEE/standard test cases pass (14-bus, 30-bus, 118-bus as applicable)
- Convergence achieved for well-conditioned problems
- Edge cases handled (zero injection buses, isolated nodes, ill-conditioned matrices)

### Performance (25%)
- No regressions in execution time vs baseline
- Memory usage reasonable (no leaks in iterative solvers)
- Sparse matrix operations used where applicable
- No unnecessary copies of large data structures

### Correctness (20%)
- Algorithm matches the mathematical formulation in the spec or paper
- Matrix assembly is correct (Y-bus, Jacobian, admittance)
- Units are consistent throughout (per-unit, SI, degrees vs radians)
- Boundary conditions handled correctly

### Testing (15%)
- Unit tests for core math functions
- Integration tests against known reference solutions
- Edge case tests (singular matrix, non-convergence, negative values)
- Tests are deterministic with fixed seeds where randomness is involved

### Completeness (5%)
- All parts of the task addressed
- API surface documented (function signatures, expected inputs/outputs)
- Commits are clean with descriptive messages

## Automatic FAIL Conditions

- Build does not compile
- Existing tests fail
- Numerical results diverge from reference by more than stated tolerance
- Solver produces NaN or Inf without error handling
- Security vulnerability introduced
- Pushed to main instead of worker/ branch

## Evaluation Method

1. Check that all existing test suites pass
2. If reference values are provided, verify numerical output matches
3. Check for performance regressions (compare timing if benchmarks exist)
4. Review matrix assembly and solver logic for mathematical correctness
5. Verify convergence on at least one standard test case
