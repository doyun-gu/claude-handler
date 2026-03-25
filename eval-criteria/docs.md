# Evaluation Criteria: Documentation

## Scoring Rubric

### Accuracy (40%)
- Documentation matches the current state of the code
- Code examples compile and run correctly
- API signatures match actual implementations
- No references to removed or renamed items

### Clarity (25%)
- Written for the target audience (developer, user, operator)
- Concepts explained before they are referenced
- Examples provided for non-obvious usage
- No ambiguous or contradictory statements

### Completeness (20%)
- All requested documentation is present
- New features/APIs are documented
- Edge cases and limitations noted
- Installation/setup instructions work from scratch

### Formatting (15%)
- Consistent markdown formatting
- Code blocks have language tags
- Tables are properly formatted
- Headers create logical hierarchy
- No broken links

## Automatic FAIL Conditions

- Documentation contradicts actual code behavior
- Code examples fail to compile or run
- Broken markdown rendering (unclosed tags, malformed tables)
- Pushed to main instead of worker/ branch

## Evaluation Method

1. Cross-reference documented APIs with actual source code
2. Verify code examples are syntactically valid
3. Check for stale references (grep for documented names in codebase)
4. Verify markdown renders correctly
