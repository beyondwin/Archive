# State And Logging

State lives at `~/.codex/orchestrator/<run_id>/state.json`.

Execution artifacts live beside it:

- `context.json`
- `spec_manifest.json`
- `task_packets/task_<N>.json`
- `DECISIONS.md`
- `preflight_warnings.json`
- `trajectory.jsonl`
- `hooks/`
- `learning_events/`
- raw verification evidence
- headless result files

AgentLens events are best-effort. They never replace state and never block
implementation.

## Cache State

CPE may record prompt-cache audit and token telemetry fields in state:

```json
{
  "cache_strategy": {
    "mode": "interactive-default",
    "stable_prefix_policy": "static-first-hot-tail",
    "provider_cache_control": "unavailable",
    "prompt_audit_version": "1"
  },
  "cache_observations": [],
  "prompt_audit": {
    "last_checked_at": "2026-05-31T00:00:00Z",
    "stable_prefix_hashes": {},
    "stable_prefix_bytes": {},
    "dynamic_marker_violations": []
  }
}
```

Provider token counters are optional. Missing cache counters are stored as
`null`; they are not inferred as zero. Finished runs must have no prompt audit
dynamic-marker violations.

## Graphify And Dispatch Evidence

`graphify_audit` stores the output of
`scripts/check_graphify_freshness.py`. It records `Built from commit` freshness,
whether `graphify update .` ran, and whether tracked or ignored outputs changed.
Finished runs cannot retain Graphify audit errors.

`dispatch_decisions` stores `scripts/preflight_dispatch.py` output for
write-capable subagent tasks. Decisions are `delegate`, `local_fallback`, or
`block`; a finished run cannot retain an unresolved `block` decision.

## Failure, Recovery, And Progress

`current_blocker` is the machine-readable blocked-state record. It includes a
category, summary, recoverability flag, and next action kind. `blocked` outcomes
require a recoverable current blocker, while `finished` outcomes must clear it.

`failure_decision` records non-recoverable failure decisions for `failed`
outcomes. `recovery_attempts` records bounded retry/bootstrap attempts by root
signature; finished runs cannot retain open recovery attempts.

`trajectory_path` points at an append-only JSONL projection. Events contain
sequence, event name, timestamp, task id, state ref, summary, evidence refs, and
redacted context budget metadata. Raw prompts are not stored there.

`progress_ledger` records per-task progress, stall count, last root signature,
next action, and whether operator input is needed.
