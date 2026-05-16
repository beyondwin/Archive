# Command Observations

Command observations record what happened before assigning root cause. They are
stored in state under top-level `command_observations`. They are useful for
long-running verification where failures may be environmental, resource-related,
or genuinely caused by source changes.

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

Validation rules:

- `command_observations` is optional, but when present it must be a list.
- Each observation requires non-empty `command`, `status`, `category`,
  `evidence`, and `next_action`.
- `category` must be one of the allowed categories above.
- For `lifecycle_outcome=finished`, every `category=unknown` observation must
  be mentioned in `completion_audit.residual_risk` by command.
