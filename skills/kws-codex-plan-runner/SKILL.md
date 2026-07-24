---
name: kws-codex-plan-runner
description: Use when approved Superpowers specifications and one or more ordered implementation plans must run autonomously through Codex with durable recovery and fail-closed ready-for-integration evidence.
metadata:
  version: "1.1.0"
  updated_at: "2026-07-25"
---

# Codex Plan Runner

## Overview

The runner is a thin wrapper around Codex and Superpowers, and a strategic
recovery shell only at external boundaries. Superpowers owns task decomposition,
SDD dispatch, TDD, task review, and its ledger. The runner does not mirror
individual subagent state.

The runner owns immutable inputs, one worktree, root launch/resume,
checkpoint-before-result handling, bounded external recovery, and final
evidence. Collaboration events are bounded activity signals, not a second task
database.

## Run

Preinstall uv-managed normal-GIL CPython `>=3.13,<3.14` with
`uv python install 3.13`, then invoke the self-locating launcher from this skill
directory:

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
  --retry-failed --strategy-note "new evidence and changed strategy"
./scripts/runner repair --run-id RUN_ID --expected-revision N \
  --repair-kind volatile-codex-turn-refs --strategy-note "verified ref-only drift"
./scripts/runner repair --run-id RUN_ID --expected-revision N \
  --repair-kind unsealed-provider-partial --attempt-id ATTEMPT_ID \
  --strategy-note "verified provider partial"
```

Repeat `--spec` and `--plan` in order. Do not merge, rewrite, or positionally pair
specs and plans. Specs are immutable common context; plans
execute sequentially in one worktree and branch. Every provider packet identifies
the current plan only and excludes future-plan paths.

Use `resume` after controller or terminal interruption. Use `--retry-blocked`
only after the external blocker is corrected. A failed run requires new
information: `--retry-failed --strategy-note "changed strategy"`.

`SIGINT` and `SIGTERM` stop the active provider process group before exposing a
durable `resumable` checkpoint. If an interrupted implementation left
uncommitted work, that exact bounded Git worktree identity is sealed; resume
accepts it only while unchanged and rejects any drift as an integrity failure.

## Superpowers and Codex Boundary

Initial and resumed providers use `--ignore-user-config`, `--ignore-rules`,
`--strict-config`, `-c 'approval_policy="never"'`, and the selected sandbox.
`danger-full-access` removes filesystem mediation but does not grant macOS TCC,
Keychain, or other host GUI authority. The effective `CODEX_HOME` stays visible
for installed authentication and Superpowers discovery.

Superpowers v6.2.0 owns its plan-scoped workspace, task briefs, review packages,
bounded fix loop, and workspace cleanup through the public
`subagent-driven-development` capabilities. Compatibility is capability-based,
not an exact version-string gate. The runner does not parse or migrate those
internals.

## Recovery and Completion

The canonical recovery source is durable state, Git HEAD, ledger, and receipts,
not conversation memory. A healthy same-plan session resume is preferred for a
simple interruption, with a fresh-session fallback when resume fails or context
may be contaminated. Each new plan starts a fresh session.

While the controller is alive, bounded changed-strategy recovery is automatic
in `recovering`. A live controller continues the bounded recovery loop itself;
do not invoke `resume` or `--retry-*`. `resumable` means an external invocation
must restart the controller. Ordinary implementation defects are fixed autonomously. Only
true external authority, provider/runtime unavailability, irreconcilable product
requirements, exhausted changed strategies, or integrity failure stop the run.

Equivalent inputs are admitted once. A refusal reports `matching_run_exists`
and the existing run's state-specific `inspect`, `resume`, retry, or repair
action. Unexpected external errors preserve evidence, change one relevant
strategy dimension, and autonomously resume the same goal. The wrapper blocks
only when authority is missing or a load-bearing invariant cannot be proved.

Only `refs/codex/turn-diffs/captures/` and
`refs/codex/turn-diffs/checkpoints/` are volatile. Recovery never exempts
unknown or product refs and exposes only the revision-guarded
`volatile-codex-turn-refs` and `unsealed-provider-partial` repairs.

A plan becomes `implemented` after its current-plan ledger and Git result are
sealed. That is not final completion. The run becomes
`ready_for_integration` only after all plans are implemented and every declared
verification command plus the final review succeed at the same candidate HEAD.
The parent helper executes exact argv without a shell, applies per-command
deadlines, and invalidates evidence when the candidate HEAD changes.

## Boundaries

Do not merge, push, or deploy. Successful handoff records
`integration=not_observed`. Credentials and mutation defenses reduce accidental
remote changes, but same-UID processes are not a security boundary; hard
containment belongs to Waygent/kernel isolation.

The active launcher never downloads Python and never falls back to system
Python. Deterministic validation is `./evals/run.sh`; a real provider canary is a
separate, explicit validation and must never be inferred from offline results.
The repository-wide canonical final gate is:

```bash
bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD
```

## Quick Reference

`run` and `resume` exit 0 only for `ready_for_integration`.
`inspect` exits 0 for any valid, readable run state; this is read success, not run completion.
`inspect` exits 64 for an unknown run and 65 for invalid state.

| Outcome | Meaning |
|---|---|
| `run`/`resume` exit 0 | `ready_for_integration` |
| `inspect` exit 0 | valid state was read, regardless of lifecycle status |
| exit 2 | externally `resumable` |
| exit 3 | externally `blocked` |
| exit 4 | bounded recovery exhausted or provider failure |
| exit 64 | invalid invocation or immutable input |
| exit 65 | state, Git, receipt, or helper integrity failure |
| exit 70 | internal failure |

Run `./scripts/runner --help` and subcommand `--help` for the complete flag
surface.
