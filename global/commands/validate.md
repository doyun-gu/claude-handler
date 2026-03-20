# /validate — Quality Gate for Worker Output

Commander validates Worker task meets requirements before merge.

## Steps

1. **Identify task**: Use specified slug/PR or find latest completed task from `~/.claude-fleet/tasks/*.json`. Read original prompt and branch.

2. **Extract criteria**: Parse dispatch prompt into numbered acceptance checklist.

3. **Test each criterion**: Checkout worker branch. For each: read the code (verify substantive change), run relevant test, grade PASS/PARTIAL/FAIL with evidence.

4. **Report**: Show pass count / total. Per-criterion status table with evidence.

5. **Verdict**: MERGE (all pass → offer merge), RE-DISPATCH (failures → create new task with original spec + specific failures + code excerpts), CLOSE (wrong direction → close PR, fresh task).
