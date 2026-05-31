# CPE Execution Hardening Design

## Summary

This design hardens `skills/kws-codex-plan-executor` across three execution
reliability surfaces:

1. prompt cache stability,
2. Graphify freshness evidence, and
3. subagent pre-dispatch decision automation.

The goal is to reduce repeated operator judgment during plan execution without
changing CPE's core model. CPE remains Codex-native, state-authoritative, and
worktree-isolated. Code mutation still happens only in dedicated execution
worktrees under `~/.codex/worktrees/<run_id>`, while executor state and runtime
artifacts stay under `~/.codex/orchestrator/<run_id>/`.

## Problem

CPE v2.21 already has strong execution rules: task packets, context snapshots,
state validation, completion audit, subagent strategy records, and Graphify
freshness guidance. The remaining weakness is that three important checks are
mostly instruction-level rather than tool-enforced:

- Prompt-generating artifacts can accidentally place dynamic run data before
  stable instructions, causing cache-hostile prompt drift.
- Graphify freshness is documented, but a stale graph can be missed unless the
  operator manually compares the built commit with `git rev-parse HEAD`.
- `subagents=on` is subagent-first, but the decision to delegate, fall back
  locally, or block still depends on manually walking the pre-dispatch checklist.

These are not new runtime features. They are hardening points for existing
contracts.

## Goals

- Make prompt cache boundary drift mechanically detectable.
- Make Graphify freshness a deterministic audit artifact.
- Make subagent dispatch decisions reproducible and reviewable.
- Keep pre-v2.21 state files valid.
- Keep AgentLens best-effort; do not make telemetry a hard dependency.
- Keep `mode=interactive` as the default execution mode.
- Keep subagent dispatch task-packet scoped and parent-reviewed.

## Non-Goals

- Do not add provider-specific cache TTL or cache-control APIs.
- Do not change CPE's default execution mode.
- Do not add new subagent fan-out policy.
- Do not route work through legacy AgentRunway or Python AgentLens trees.
- Do not make Graphify output part of product runtime behavior.
- Do not replace state validation with AgentLens event replay.

## Current Architecture Fit

CPE already separates repository mutation from orchestration state:

- repository worktrees: `~/.codex/worktrees/<run_id>`
- orchestration state: `~/.codex/orchestrator/<run_id>`
- source package: `skills/kws-codex-plan-executor`

This design adds deterministic scripts and evals inside the skill package. The
scripts produce JSON evidence that is either copied into state or referenced by
the completion audit. The scripts do not mutate repository files except where a
specific command is explicitly an append/update helper for orchestration state.

## Proposed Components

Create:

- `references/cache-strategy.md`
- `scripts/audit_prompt_cache.py`
- `scripts/record_cache_observation.py`
- `scripts/check_graphify_freshness.py`
- `scripts/preflight_dispatch.py`
- `evals/check_prompt_cache_audit.py`
- `evals/check_cache_observations.py`
- `evals/check_graphify_freshness.py`
- `evals/check_preflight_dispatch.py`

Modify:

- `SKILL.md`
- `README.md`
- `ARCHITECTURE.md`
- `HISTORY.md`
- `references/execution-cycle.md`
- `references/headless-runner.md`
- `references/pre-dispatch-pipeline.md`
- `references/prompt-export-checklist.md`
- `references/state-schema.md`
- `docs/evals-and-verification.md`
- `docs/risks-limitations-deferrals.md`
- `docs/state-and-logging.md`
- `scripts/validate_state.py`
- `evals/check_state_schema.py`
- `evals/check_skill_contract.py`
- `evals/run.sh`

## Cache Strategy

Prompt cache hardening treats cache reuse as a prefix-stability problem.

Terms:

- Stable prefix: role instructions, safety boundaries, required skills, output
  schemas, and invariant checklists.
- Hot tail: plan paths, run ids, state paths, timestamps, git status, task
  packets, changed files, diffs, decisions, verification output, and retry
  context.
- Cache-hostile drift: dynamic material inserted before stable prompt content.

Prompt-generating artifacts use explicit markers:

```text
<!-- CPE_CACHE_STABLE_PREFIX_START -->
<!-- CPE_CACHE_STABLE_PREFIX_END -->
<!-- CPE_CACHE_HOT_TAIL_START -->
```

`scripts/audit_prompt_cache.py` checks configured templates and verifier
prompts for:

- exactly one stable-prefix start marker,
- exactly one stable-prefix end marker,
- hot-tail marker after the stable-prefix end,
- no unapproved `{{...}}` placeholders inside the stable prefix,
- no obvious dynamic terms such as run ids, state paths, task packet paths,
  timestamps, git status, diff text, or absolute home paths inside the stable
  prefix,
- stable-prefix hash and byte-count reporting.

The audit does not require provider cache counters. Provider counters are
optional telemetry recorded separately by `record_cache_observation.py` when
available.

## Cache State

State gains optional fields:

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

Validation rules:

- The cache fields are optional for existing state.
- `cache_strategy.mode` is one of `interactive-default`,
  `headless-explicit`, `prompt-export`, or `handoff-export`.
- `provider_cache_control` is one of `unavailable`, `available-unused`,
  `available-enabled`, or `unknown`.
- Token counters in `cache_observations` may be integer or null.
- A finished lifecycle outcome cannot include non-empty
  `prompt_audit.dynamic_marker_violations`.

## Graphify Freshness Audit

When repository instructions mention Graphify, CPE currently requires the
operator to read `graphify-out/GRAPH_REPORT.md`, compare `Built from commit`
with `git rev-parse HEAD`, run `graphify update .` after code changes, and
record the result in completion audit.

`scripts/check_graphify_freshness.py` turns that into a deterministic check.

Inputs:

- `--repo-root`
- optional `--graph-report`, defaulting to
  `<repo-root>/graphify-out/GRAPH_REPORT.md`
- optional `--require-update-evidence`
- optional `--output`

Output:

```json
{
  "schema_version": "1",
  "graph_report": "graphify-out/GRAPH_REPORT.md",
  "graphify_present": true,
  "built_commit": "0e16c9c2",
  "head_commit": "44a078d2367b341634e299135dc7bb6a3026cc3d",
  "fresh": false,
  "update_required": true,
  "update_evidence": {
    "command": "graphify update .",
    "ran": false,
    "tracked_outputs_changed": false,
    "ignored_outputs_note": ""
  },
  "warnings": [],
  "errors": []
}
```

Behavior:

- Missing `graphify-out/` is a warning unless repo instructions require
  Graphify for the current task.
- Missing `Built from commit` is an error when the report exists.
- A short built commit is accepted if it is a prefix of HEAD.
- A stale report requires explicit evidence after code or meaningful
  documentation structure changes.
- If `graphify-out/` is ignored, the audit records that the update ran but
  generated outputs were not tracked.

Finished CPE state must include Graphify audit evidence when the active repo
instructions mention Graphify and the execution changed code or meaningful
documentation structure.

## Subagent Pre-Dispatch Decision

`subagents=on` remains subagent-first for eligible write-capable tasks.
`scripts/preflight_dispatch.py` mechanizes the existing checklist.

Inputs:

- `--state`
- `--task-id`
- `--task-packet`
- `--repo-root`
- `--write-scope`
- optional `--output`

The script checks:

- resolved invocation allows delegation,
- task packet exists and is readable,
- declared files are non-empty,
- dirty files do not overlap task files or write scope,
- state file is writable,
- requested write scope is non-empty,
- requested write scope is equal to or narrower than
  `write_policy.allowed_write_globs`,
- active subagent write scopes do not overlap unless an explicit rationale is
  already recorded,
- forbidden globs are not included in the delegated write scope.

Output:

```json
{
  "schema_version": "1",
  "task_id": "task_0",
  "decision": "delegate",
  "reason": "all pre-dispatch prerequisites passed",
  "write_scope": ["src/foo.ts"],
  "failed_prerequisites": [],
  "state_updates": {
    "subagent_strategy": {
      "mode": "delegated",
      "reason": "all pre-dispatch prerequisites passed",
      "run_ids": []
    }
  }
}
```

Decision values:

- `delegate`: safe to spawn a task-packet-scoped subagent.
- `local_fallback`: delegation is not safe or available, but local execution is
  allowed after recording the exact fallback reason.
- `block`: execution must stop because proceeding could touch ambiguous,
  related dirty files or violate declared write policy.

The main agent still performs post-diff and state review before accepting
subagent output. This script standardizes the pre-dispatch decision; it does
not replace parent responsibility.

## Completion Gates

Before `lifecycle_outcome=finished`, CPE must prove:

- `scripts/reconcile_state.py --check` passes.
- `scripts/validate_state.py` passes.
- Prompt audit has no dynamic marker violations.
- Unknown command observations are mentioned in residual risk.
- Required Graphify audit evidence is present when the repo instructions
  mention Graphify and the execution changed code or meaningful documentation
  structure.
- Every completed write-capable task under `subagents_requested=true` has a
  valid `subagent_strategy`.
- No delegated subagent run is running or unreviewed.
- `completion_audit.verification_evidence` references the prompt audit,
  Graphify audit when required, acceptance command, and changed-project tests
  or an honest substitute.

## Testing Strategy

Add deterministic evals before implementation:

- `check_prompt_cache_audit.py`
  - missing markers fail,
  - dynamic placeholders inside stable prefix fail,
  - hot-tail-only changes do not change stable-prefix hash,
  - stable-prefix instruction changes do change stable-prefix hash.
- `check_cache_observations.py`
  - missing provider counters become null,
  - invalid token field types fail,
  - pre-cache state still validates,
  - finished state with prompt-audit violations fails.
- `check_graphify_freshness.py`
  - fresh report passes,
  - stale report is detected,
  - missing report is classified,
  - ignored output update evidence is represented.
- `check_preflight_dispatch.py`
  - clean task packet delegates,
  - dirty overlap blocks,
  - missing task packet falls back or blocks with exact reason,
  - overlapping active write scopes fail,
  - forbidden write globs fail.

Extend existing checks:

- `check_state_schema.py` covers optional cache, Graphify, and dispatch fields.
- `check_skill_contract.py` verifies the new hardening contracts are documented.
- `evals/run.sh` runs the new deterministic checks.

Required verification for the implementation branch:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 evals/check_spec_manifest.py
python3 evals/check_task_packet.py
python3 evals/check_local_env_preflight.py
python3 evals/check_invocation_args.py
python3 evals/check_inspect_runs.py
python3 evals/check_decisions_register.py
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
bash evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
```

## Rollout Plan

Implement in four commits:

1. Cache hardening docs and audit
   - Add cache strategy reference.
   - Add prompt boundary markers.
   - Add prompt cache audit script and eval.
   - Add optional cache observation appender and validation.

2. Graphify audit
   - Add Graphify freshness script and eval.
   - Wire audit evidence into execution-cycle docs and state validation.
   - Update docs for ignored `graphify-out/` behavior.

3. Dispatch preflight
   - Add pre-dispatch decision script and eval.
   - Update pre-dispatch pipeline docs.
   - Add state validation for dispatch decision evidence where appropriate.

4. Integration and docs
   - Update `SKILL.md`, README, architecture, history, verification docs, and
     risk docs.
   - Run the deterministic suite and update baselines only for intentional
     output changes.

## Risks And Mitigations

- Prompt audit could become too strict.
  - Keep dynamic marker rules explicit, allowlisted, and fixture-backed.
- Graphify may be unavailable locally.
  - Classify tool absence separately from stale graph output; require honest
    completion-audit evidence rather than silent success.
- Dispatch preflight might block too often.
  - Return `local_fallback` for safe non-delegation cases and reserve `block`
    for related dirty ambiguity or write-policy violation.
- State schema expansion could break old runs.
  - Keep new fields optional and preserve pre-v2.21 validation fixtures.
- Operators could treat JSON decisions as final authority.
  - Keep parent post-diff and state review as a hard boundary.

## Acceptance Criteria

The implementation is complete when:

- all new scripts exist and produce deterministic JSON,
- all new evals pass,
- existing deterministic evals still pass,
- finished state validation rejects prompt audit violations,
- Graphify stale/fresh/missing states are classified deterministically,
- dispatch preflight emits `delegate`, `local_fallback`, or `block` with exact
  reasons,
- `SKILL.md`, README, architecture, history, references, and verification docs
  describe the new behavior consistently,
- no executor runtime artifacts are written into the repository worktree, and
- `git diff --check` passes.
