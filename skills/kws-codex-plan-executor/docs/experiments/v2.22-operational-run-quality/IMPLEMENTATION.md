# CPE v2.22 Operational Run Quality Implementation Spec

## Summary

v2.22 improves `kws-codex-plan-executor` run-state quality after real use. The
executor already finishes most runs and validates recent state reliably, but
recent state inspection shows four operational gaps:

1. `subagents=on` is the documented default, yet many real runs fall back to
   local execution because the active tool policy only permits spawning after an
   explicit user request for delegation.
2. Fresh worktrees repeatedly fail first verification commands for predictable
   bootstrap reasons such as missing dependencies, missing Android SDK env, or
   unavailable optional tools.
3. `inspect_runs.py` is useful for one-plan resume lookup, but not for a recent
   run-quality report, stale-run triage, schema-drift detection, or comparing
   `workspace` against the actual execution worktree.
4. Finished run state is valid enough for the current validator, but several
   fields are still hard to aggregate consistently across runs.

The implementation keeps CPE Codex-native and state-authoritative. It does not
change the core executor boundary, does not automatically run install commands,
and does not widen write scopes. It adds deterministic policy evidence and
inspection tools so the next agent can trust, resume, or close a run without
reading raw transcripts.

## Code Findings

The current code already has the right building blocks:

- `scripts/parse_invocation_args.py` has deterministic defaults and records
  argument sources. Its default remains `subagents=on`, and Korean/English
  natural-language hints can mark explicit delegation intent.
- `scripts/preflight_dispatch.py` validates packet hash, allowed write globs,
  forbidden globs, context budget, acceptance command, and dirty-overlap safety.
  It does not currently accept an executor-level spawn policy or explicit user
  delegation signal, so policy fallback reasons are written manually in state by
  the parent agent.
- `scripts/preflight_local_env.py` is detection-only and already emits
  `missing_local_config` and `dependencies_likely_stale`. Its package-manager
  heuristics are root-level and too coarse for repeated fresh-worktree issues in
  Bun, pnpm, Gradle, Android, and optional CLI surfaces.
- `scripts/inspect_runs.py` scans `~/.codex/orchestrator/*/state.json` and
  redacts `~/.codex` paths. It filters by one `--plan` value and reports active
  runs, ambiguity, blocker category, context budget, and missing worktree. It
  does not summarize recent runs across plans, validate states, or report stale
  non-terminal runs.
- `scripts/validate_state.py` enforces many v2.20+ invariants, including
  completed write-capable task `subagent_strategy`, finished-state prompt audit
  cleanliness, Graphify audit errors, dispatch block decisions, blocker
  clearance, recovery attempt closure, and progress-ledger type checks.
- `evals/static_execution_runner.py` creates deterministic fixture state. It is
  the right place to add new optional fields before wiring stricter validation.

Recent local state evidence from `~/.codex/orchestrator` is consistent with
those code findings:

- Recent 40 runs: 38 `finished`, 2 with no terminal `lifecycle_outcome`.
- Recent 20 runs under the current validator: 18 pass, 2 fail because older
  states have `current_task` or `subagent_strategy` drift.
- Recent 20 task strategy modes: 108 `local_fallback`, 10 `delegated`, 9
  `no_strategy`.
- Recent 40 command observation categories: 10 `dependency_bootstrap`, 11
  `missing_local_env`, 6 `source_failure`, 3 `timeout_or_hang`, 6
  `tooling_bug`.
- Recent 40 states with `workspace` outside `~/.codex/worktrees`: 13.

## Goals

- Make delegation policy outcomes machine-readable and consistent.
- Detect likely fresh-worktree bootstrap issues before the first RED command.
- Make run inspection useful for recent quality reports, stale active runs, and
  schema drift.
- Normalize state fields enough that simple scripts can aggregate completed
  runs without per-version special cases.
- Preserve backward compatibility for v2.19-v2.21 state files.

## Non-Goals

- Do not change the hard worktree boundary.
- Do not run dependency installation automatically.
- Do not create or manage real `spawn_agent` tool calls from Python scripts.
- Do not change `mode=interactive` as the default.
- Do not widen task `allowed_write_globs` from inspection or repair tools.
- Do not mutate stale run state during read-only inspection.

## Proposed State Additions

All fields are optional for older states. New v2.22 states should populate them
after preflight and before terminal completion.

```json
{
  "source_workspace": "/Users/kws/source/private/Archive",
  "execution_worktree": "/Users/kws/.codex/worktrees/example-run-20260609-120000",
  "command_cwd_evidence": [
    {
      "command": "python3 scripts/preflight_local_env.py --repo-root \"$WORKTREE_ABS\"",
      "cwd": "/Users/kws/.codex/worktrees/example-run-20260609-120000",
      "phase": "preflight",
      "status": "passed"
    }
  ],
  "delegation_policy": {
    "requested_mode": "on",
    "requested_source": "default",
    "explicit_user_delegation_request": false,
    "spawn_policy": "explicit-request-required",
    "effective_mode": "local_fallback",
    "reason": "subagents=on came from the skill default, but the active spawn tool policy requires explicit user delegation intent."
  },
  "preflight_bootstrap": {
    "schema_version": "1",
    "detected_at": "2026-06-09T00:00:00Z",
    "warnings": [],
    "bootstrap_plan": [],
    "environment_capabilities": {
      "node": "present",
      "bun": "present",
      "pnpm": "present",
      "gradle_wrapper": "absent",
      "android_sdk": "unknown",
      "cargo": "absent",
      "agentlens": "absent"
    }
  },
  "run_quality": {
    "schema_version": "1",
    "validation_status": "passed",
    "terminal_state": "finished",
    "stale": false,
    "workspace_matches_execution_worktree": true,
    "schema_drift": [],
    "open_followups": [],
    "summary": "Run finished with validated state and no open blockers."
  }
}
```

### Field Rules

- `source_workspace` is the caller/original checkout when known.
- `execution_worktree` is the isolated worktree where edits and verification
  commands should run. It must end with `.codex/worktrees/<run_id>` when set.
- `workspace` remains backward compatible. v2.22 docs should describe it as a
  legacy broad workspace pointer; new tooling should prefer
  `execution_worktree`.
- `command_cwd_evidence[]` records only command, cwd, phase, and status. It must
  not store secrets, long logs, or full transcripts.
- `delegation_policy.requested_source` is one of `default`, `explicit`,
  `natural_language`, or `resume_state`.
- `delegation_policy.spawn_policy` is one of `available`, `unavailable`,
  `explicit-request-required`, or `unknown`.
- `delegation_policy.effective_mode` is one of `delegate`, `local_fallback`,
  `off`, or `blocked`.
- Finished v2.22 states with `subagents_requested=true` and no accepted
  `subagent_runs` may still pass when `delegation_policy.effective_mode` is
  `local_fallback` and every completed write-capable task records
  `subagent_strategy.mode=local_fallback`.
- `preflight_bootstrap.bootstrap_plan[]` contains suggested commands only. CPE
  never runs them automatically.
- `run_quality` is generated by inspection/reporting tools and may be embedded
  in state at final audit time. Read-only inspection may also compute it without
  writing state.

## Local Environment Preflight Design

Extend `scripts/preflight_local_env.py` to preserve the existing
`warnings[]` contract and add two optional sections:

```json
{
  "schema_version": "1",
  "warnings": [
    {
      "kind": "dependencies_likely_stale",
      "manifest": "package.json",
      "lockfile": "pnpm-lock.yaml",
      "marker": "node_modules/.modules.yaml",
      "suggestion": "Run `pnpm install --frozen-lockfile` before baseline.",
      "detected_at": "2026-06-09T00:00:00Z"
    }
  ],
  "bootstrap_plan": [
    {
      "id": "node-pnpm-install",
      "command": "pnpm install --frozen-lockfile",
      "reason": "pnpm-lock.yaml is newer than node_modules/.modules.yaml",
      "auto_run": false
    }
  ],
  "environment_capabilities": {
    "node": "present",
    "bun": "present",
    "pnpm": "present",
    "gradle_wrapper": "absent",
    "android_sdk": "unknown",
    "cargo": "absent",
    "agentlens": "absent"
  }
}
```

Detection should be conservative:

- npm: `package-lock.json` or `npm-shrinkwrap.json`, marker
  `node_modules/.package-lock.json`, command `npm install`.
- pnpm: `pnpm-lock.yaml`, marker `node_modules/.modules.yaml`, command
  `pnpm install --frozen-lockfile`.
- yarn: `yarn.lock`, marker `node_modules/.yarn-integrity`, command
  `yarn install --frozen-lockfile`.
- bun: `bun.lock` or `bun.lockb`, marker `node_modules/.bun-install`, command
  `bun install`.
- Gradle: `gradlew` plus `settings.gradle*` or `build.gradle*`, command
  `./gradlew help --no-daemon` as a bootstrap probe.
- Android: `ANDROID_HOME` or `ANDROID_SDK_ROOT`, plus `adb` availability.
- Rust: `Cargo.toml`, `Cargo.lock`, and `cargo` availability.
- AgentLens: `agentlens` availability only affects observability; it must stay
  non-blocking.

## Delegation Policy Design

Keep the documented invocation choices:

- `subagents=on`: task-packet scoped subagent-first intent.
- `subagents=auto`: conservative delegation only after explicit request.
- `subagents=off`: local-only.

Add a separate effective policy layer so real runs stop repeating ambiguous
local fallback reasons.

`scripts/parse_invocation_args.py` should expose:

```json
{
  "values": {
    "subagents": "on"
  },
  "sources": {
    "subagents": "default"
  },
  "intent": {
    "explicit_delegation_request": false,
    "delegation_hint": null
  }
}
```

`scripts/preflight_dispatch.py` should accept:

```text
--spawn-policy available|unavailable|explicit-request-required|unknown
--explicit-delegation-requested true|false
--requested-subagents on|auto|off
--requested-source default|explicit|natural_language|resume_state
```

When `--spawn-policy explicit-request-required` and
`--explicit-delegation-requested false`, the decision should be
`local_fallback` with failed prerequisite
`spawn_policy_requires_explicit_user_request`. This makes the state update
deterministic instead of handwritten.

## Run Inspection Design

Extend `scripts/inspect_runs.py` without breaking the existing single-plan
resume report.

New flags:

```text
--recent N
--all-plans
--stale-hours N
--validate-state
--quality-report
--jsonl
```

Rules:

- `--plan` keeps current behavior.
- `--all-plans --recent 40` reports the newest 40 states by mtime.
- `--stale-hours 24` marks non-terminal runs older than 24 hours.
- `--validate-state` imports `validate_state.validate()` and records
  `validation_status=passed|failed|unreadable` plus validation errors.
- `--quality-report` returns aggregate counts and per-run `run_quality`.
- `--jsonl` writes one compact JSON object per run for shell-friendly analysis.

Example aggregate output:

```json
{
  "schema_version": "2",
  "scope": {"mode": "all-plans", "recent": 40},
  "summary": {
    "total": 40,
    "finished": 38,
    "non_terminal": 2,
    "validation_passed": 36,
    "validation_failed": 2,
    "stale_non_terminal": 2,
    "workspace_not_execution_worktree": 13,
    "delegated_tasks": 10,
    "local_fallback_tasks": 108
  },
  "runs": []
}
```

## Validation Design

Add optional validation for the new v2.22 fields while preserving older states:

- `source_workspace`: string when present.
- `execution_worktree`: string ending in `.codex/worktrees/<run_id>` when
  present.
- `command_cwd_evidence`: list of objects with non-empty `command`, `cwd`,
  `phase`, and `status`.
- `delegation_policy`: object with allowed enum values and non-empty `reason`
  when `effective_mode` is `local_fallback` or `blocked`.
- `preflight_bootstrap`: object with `schema_version=1`, list `warnings`, list
  `bootstrap_plan`, and object `environment_capabilities`.
- `run_quality`: object with `schema_version=1`, allowed `validation_status`,
  boolean `stale`, and list `schema_drift`.

Do not make `workspace == execution_worktree` mandatory. Several real runs use
`workspace` for the source checkout and `worktree` for the isolated execution
tree. The validator should instead require `execution_worktree == worktree`
when both are present.

## Documentation Impact

Update:

- `SKILL.md`: add v2.22 invariants for delegation policy, bootstrap preflight,
  and quality inspection before finished outcome.
- `README.md`: add new eval commands and design note.
- `ARCHITECTURE.md`: describe source workspace vs execution worktree and
  effective delegation policy.
- `HISTORY.md`: add a v2.22.0 entry.
- `references/state-schema.md`: document optional v2.22 fields.
- `references/local-env-preflight.md`: document bootstrap plan and capability
  detection.
- `references/pre-dispatch-pipeline.md`: document effective delegation policy
  and explicit-request tool-policy fallback.
- `docs/state-and-logging.md`: explain `run_quality`, `delegation_policy`, and
  `command_cwd_evidence`.
- `docs/evals-and-verification.md`: add new evals.
- `docs/risks-limitations-deferrals.md`: document remaining non-goals.

## Acceptance Criteria

- `bash evals/run.sh` passes from `skills/kws-codex-plan-executor`.
- `python3 -m py_compile scripts/*.py evals/*.py` passes.
- `bash -n evals/run.sh` passes.
- `git diff --check` passes from the repository root.
- `inspect_runs.py --all-plans --recent 40 --validate-state --quality-report`
  can produce a summary without jq-specific knowledge of older state shapes.
- Finished v2.22 fixture states validate with the new optional fields.
- Older v2.19-v2.21 fixture states still validate.
- Local fallback caused by explicit-request spawn policy is recorded by
  `preflight_dispatch.py`, not handwritten in task state.

## Residual Risks

- The Python scripts cannot know every host tool policy. They can only record
  the policy passed by the parent agent or harness.
- Capability detection can report likely bootstrap issues, but it cannot prove
  a command will pass after bootstrap.
- Existing historical states may remain non-terminal or schema-drifted. v2.22
  makes them visible; it does not silently rewrite them.
- `workspace` remains backward compatible and may keep mixed meanings in old
  states. New tooling should prefer `execution_worktree`.
