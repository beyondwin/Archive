# Local Environment Preflight

Local environment preflight is detection-only. It never copies secrets, never
installs dependencies, and never blocks execution by itself.

## Warning Kinds

- `missing_local_config`
- `dependencies_likely_stale`

## State Field

`state.preflight_warnings` is always present after preflight. It is `[]` when
the local environment looks clean.

## Escalation Use

If baseline or task verification fails with module-load, missing-config, or
dependency errors, compare the failure with `state.preflight_warnings` before
assigning root cause. A matching warning may classify the command observation as
`missing_local_env` or `dependency_bootstrap`.
