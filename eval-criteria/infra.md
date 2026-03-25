# Evaluation Criteria: Infrastructure / CI / Config

## Scoring Rubric

### Correctness (35%)
- Configuration changes work as intended
- CI pipeline runs successfully
- Deployment scripts execute without errors
- Docker builds and runs correctly

### Security (25%)
- No secrets committed (API keys, passwords, tokens)
- No overly permissive file permissions
- Docker images use specific tags (not :latest in production)
- Environment variables used for sensitive config
- No exposed ports that should be internal

### Portability (20%)
- Works on both Commander (MacBook) and Worker (Mac Mini)
- No hardcoded paths (uses $HOME, relative paths, or env vars)
- Dependencies are pinned to specific versions
- Works with both zsh and bash

### Reliability (10%)
- Error handling for missing dependencies or services
- Graceful degradation when optional services unavailable
- Idempotent (safe to run multiple times)
- Logging sufficient for debugging failures

### Completeness (10%)
- All parts of the infrastructure task addressed
- README/docs updated if setup steps changed
- Existing infrastructure not broken
- Commits are clean with descriptive messages

## Automatic FAIL Conditions

- Secrets committed to repository
- Build/deploy pipeline broken
- Existing services no longer start
- Hardcoded paths that only work on one machine
- Pushed to main instead of worker/ branch

## Evaluation Method

1. Check for secrets in the diff (grep for API keys, passwords, tokens)
2. Verify no hardcoded user-specific paths
3. Check Docker builds if Dockerfile changed
4. Verify CI config is valid syntax
5. Test that scripts work on the target machine
