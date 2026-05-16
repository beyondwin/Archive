# Headless Result Schema

Headless execution should return a stable final result shape so the parent
session can review status, artifacts, verification, blockers, and residual risk
without parsing prose.

Final result shape:

```json
{
  "status": "success",
  "run_id": "20260516T073000Z-archive-codex-example-abcdef0-a1b2c3",
  "state_path": ".codex-orchestrator/runs/20260516T073000Z-archive-codex-example-abcdef0-a1b2c3/state.json",
  "summary": "Implemented task 2 and verified state schema checks.",
  "changed_files": ["scripts/validate_state.py", "evals/check_state_schema.py"],
  "verification": [
    {"command": "python3 evals/check_state_schema.py", "status": "passed"}
  ],
  "open_gaps": [],
  "residual_risk": [],
  "next_action": "Review diff and commit."
}
```

`status` should be one of `success`, `blocked`, `failed`, or `interrupted`.
Successful results must include non-empty verification evidence and a readable
state path. Non-success results must include the blocker or failure in
`open_gaps` or `residual_risk`, plus a concrete `next_action`.

When `codex exec --output-schema` is available, the headless runner can pass a
JSON Schema for this shape. When it is unavailable, the prompt must still ask
for this JSON result and save the last message for review.

