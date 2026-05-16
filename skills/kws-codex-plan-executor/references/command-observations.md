# Command Observations

Command observations record what happened before assigning root cause. They are
useful for long-running verification where failures may be environmental,
resource-related, or genuinely caused by source changes.

Observation shape:

```json
{
  "command": "pnpm test",
  "status": "failed",
  "category": "dependency_bootstrap",
  "evidence": "node_modules missing; install command not yet run",
  "next_action": "Run pnpm install before retrying tests"
}
```

Allowed categories:

- `source_failure`
- `missing_local_env`
- `dependency_bootstrap`
- `resource_oom`
- `timeout_or_hang`
- `flaky_test`
- `permission_or_sandbox`
- `tooling_bug`
- `unknown`

Use `unknown` only when the executor has captured bounded evidence and the
completion audit records the residual risk. Do not use observations as a
substitute for fixing reproducible source failures.

