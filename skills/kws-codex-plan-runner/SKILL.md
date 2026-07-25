---
name: kws-codex-plan-runner
description: Use when approved Superpowers specifications and one or more ordered implementation plans must run autonomously through Codex with durable recovery and fail-closed ready-for-integration evidence.
metadata:
  version: "2.0.0"
  updated_at: "2026-07-25"
---

# Codex Plan Runner

## Overview

The runner is a thin wrapper around Codex and Superpowers, and a strategic
recovery shell only at external boundaries. Specifications and plans are
immutable inputs handed unchanged to Superpowers.
Do not merge, rewrite, or positionally pair them. Superpowers owns task
decomposition, SDD dispatch, TDD, task review, fixes, and the final whole-branch
review.

The runner owns exact external facts: immutable input digests, one worktree,
plan order, root recovery actions, ordered plan handoff HEADs, accepted
verification digests and receipts, and the run outcome. It does not mirror
individual subagent state. Collaboration events are bounded activity signals,
not a second task database.

## Run

Preinstall uv-managed normal-GIL CPython `>=3.13,<3.14` with
`uv python install 3.13`, then invoke the self-locating launcher:

```bash
./scripts/runner run \
  --workspace /absolute/repository \
  --spec /absolute/spec-a.md --spec /absolute/spec-b.md \
  --plan /absolute/plan-a.md --plan /absolute/plan-b.md \
  --sandbox danger-full-access
./scripts/runner inspect --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID --retry-blocked
./scripts/runner resume --run-id RUN_ID \
  --retry-blocked --sandbox danger-full-access \
  --strategy-note "workspace-write capability is blocked; use authorized full access"
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note "new evidence and changed strategy" \
  --model MODEL
./scripts/runner repair --run-id RUN_ID --expected-revision N \
  --repair-kind volatile-codex-turn-refs \
  --strategy-note "verified ref-only drift"
```

Repeat `--spec` and `--plan` in order. Specs are immutable common context.
Superpowers receives all specifications unchanged and the current plan only;
future plan paths are excluded. Every prior plan handoff HEAD is an ancestor of
the accepted current candidate.

## Superpowers and Codex boundary

Initial and resumed providers use `--ignore-user-config`, `--ignore-rules`,
`--strict-config`, `-c 'approval_policy="never"'`, and the selected sandbox.
`--ignore-rules` disables Codex execpolicy rules for these controlled launches;
the runner's explicit argv, Git, and integration checks remain in force.
`danger-full-access` removes filesystem mediation but does not grant macOS TCC,
Keychain, or other host GUI authority. The effective `CODEX_HOME` remains
visible for installed authentication and Superpowers discovery.

Superpowers v6.2.0 owns its plan-scoped workspace, task briefs, review packages,
fix loop, single final whole-branch review, and cleanup through the public
`subagent-driven-development` capabilities. Compatibility is capability-based,
not an exact version gate. The public capability surface is `sdd-workspace`,
`task-brief`, and `review-package`; the runner does not parse or migrate those
internals.

## Recovery

The canonical recovery source is durable state, Git HEAD, ledger, and receipts,
not conversation memory. Every plan starts with a fresh root. A plan gets at
most one healthy same-plan session resume, expressed as one healthy root resume,
and one fresh-root fallback when resume fails or context may be contaminated.

While the controller is alive, bounded changed-strategy recovery is automatic
in `recovering`. A live controller continues the bounded recovery loop itself.
`resumable` means an external invocation must restart a stopped controller.
Ordinary implementation defects stay inside Superpowers. Only true external
authority, provider/runtime unavailability, irreconcilable requirements,
exhausted strategies, or integrity failure stop the run.

An authorized retry may record an `execution_profile_transition`; provider
runtime gaps use `provider_capability_blocked`. Equivalent intents report
`matching_run_exists` and the state-appropriate inspect, resume, or retry
action.

Only `refs/codex/turn-diffs/captures/` and
`refs/codex/turn-diffs/checkpoints/` are volatile. The only active repair is
revision-guarded `volatile-codex-turn-refs`; unknown or product refs remain
protected. Recorded process group and descendant PID quiescence is necessary
before a dirty checkpoint can be accepted, but it is not a security boundary.

A dirty checkpoint records HEAD, branch, porcelain, and bounded content digests
for drift detection. It is not a backup and cannot restore files.

## Verification and completion

A plan becomes `implemented` after its Superpowers ledger and Git handoff are
sealed. The final plan carries all immutable requirements and owns the single
final whole-branch review. The run becomes `ready_for_integration` only after
all plans are implemented and exact verification receipts plus that review
succeed at the same candidate HEAD. The runner executes exact argv without a
shell, applies deadlines, and invalidates evidence when the candidate HEAD
changes.

The final helper derives the exact ordered duplicate-free union of all sealed
plan verification declarations at the final HEAD. The final handoff and
accepted verification digest bind that run-level union.

Do not merge, push, or deploy. Every provider packet sets
`integration_policy=keep`; successful handoff records
`integration=not_observed`. Processes running as the same-UID are not a security boundary;
hard containment belongs to Waygent/kernel isolation.

Version 1 state is inspect-only. Version 2 is required for `run`, `resume`, and
recovery; older state is never upgraded or reinterpreted in place.

The active launcher never downloads Python and never falls back to system
Python. Deterministic validation is `./evals/run.sh`; real provider canaries are
separate explicit evidence. The repository-wide canonical gate is:

```bash
bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD
```

## Quick reference

`run` and `resume` exit 0 only for `ready_for_integration`.
`inspect` exits 0 for any valid, readable run state; this is read success, not
run completion. `inspect` exits 64 for an unknown run and 65 for invalid state.

| Outcome | Meaning |
|---|---|
| `run`/`resume` exit 0 | `ready_for_integration` |
| `inspect` exit 0 | valid state was read |
| exit 2 | externally `resumable` |
| exit 3 | externally `blocked` |
| exit 4 | bounded recovery exhausted or provider failure |
| exit 64 | invalid invocation or immutable input |
| exit 65 | state, Git, receipt, or integrity failure |
| exit 70 | internal failure |
