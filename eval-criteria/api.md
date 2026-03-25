# Evaluation Criteria: API / Backend Endpoints

## Scoring Rubric

### Correctness (35%)
- Endpoints return correct data for valid requests
- HTTP status codes are appropriate (200, 201, 400, 401, 404, 500)
- Response schema matches documented or expected format
- Query parameters and path parameters handled correctly
- Database operations are correct (CRUD works as intended)

### Error Handling (25%)
- Invalid input returns 400 with descriptive error message
- Missing resources return 404
- Unauthorized access returns 401/403
- Server errors return 500 with safe error message (no stack traces leaked)
- Malformed JSON returns 400

### Security (20%)
- Authentication/authorization enforced on protected routes
- Input validated and sanitized
- No SQL injection vectors
- No path traversal vulnerabilities
- Secrets not exposed in responses or logs
- CORS configured appropriately

### Performance (10%)
- No N+1 query patterns
- Database queries use indexes where appropriate
- Response times reasonable for expected payload size
- No unbounded queries (pagination or limits on list endpoints)

### Completeness (10%)
- All requested endpoints implemented
- Request/response types defined
- Error responses are structured JSON (not plain text)
- Commits are clean with descriptive messages

## Automatic FAIL Conditions

- Server does not start
- Existing tests fail
- SQL injection or path traversal vulnerability
- Secrets exposed in response body or logs
- Authentication bypass possible
- Pushed to main instead of worker/ branch

## Evaluation Method

1. Verify the server starts without errors
2. Test each new endpoint with valid input (check response schema)
3. Test with invalid input (check error handling)
4. Test with missing/wrong authentication (check auth enforcement)
5. Check for N+1 queries in database-backed endpoints
