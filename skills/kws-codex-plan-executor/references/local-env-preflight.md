# Local Environment Preflight

Local environment preflight is detection-only. It never copies secrets, never
installs dependencies, and never blocks execution by itself.

## Warning Kinds

- `missing_local_config`
- `dependencies_likely_stale`

## State Field

`state.preflight_warnings` is always present after preflight. It is `[]` when
the local environment looks clean.

v2.22 runs may also persist the full preflight report in
`state.preflight_bootstrap`:

```json
{
  "schema_version": "1",
  "warnings": [],
  "bootstrap_plan": [
    {
      "id": "pnpm-install---frozen-lockfile",
      "command": "pnpm install --frozen-lockfile",
      "reason": "Run `pnpm install --frozen-lockfile` before baseline.",
      "auto_run": false
    }
  ],
  "environment_capabilities": {
    "node": "present",
    "bun": "present",
    "pnpm": "present",
    "gradle_wrapper": "absent",
    "android_sdk": "unknown",
    "adb": "absent",
    "cargo": "absent",
    "agentlens": "absent"
  }
}
```

Package-manager stale checks use manager-specific markers: npm
`node_modules/.package-lock.json`, pnpm `node_modules/.modules.yaml`, yarn
`node_modules/.yarn-integrity`, and bun `node_modules/.bun-install`.
`bootstrap_plan` entries are commands the operator may run; the preflight script
never executes them.

## Escalation Use

If baseline or task verification fails with module-load, missing-config, or
dependency errors, compare the failure with `state.preflight_warnings` before
assigning root cause. A matching warning may classify the command observation as
`missing_local_env` or `dependency_bootstrap`.
