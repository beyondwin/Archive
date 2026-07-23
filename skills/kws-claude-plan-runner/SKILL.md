---
name: kws-claude-plan-runner
description: Use when approved Superpowers specifications and one or more ordered implementation plans must run autonomously through Claude Code with durable recovery and fail-closed ready-for-integration evidence.
metadata:
  version: "1.0.0"
  updated_at: "2026-07-23"
---

# Claude Plan Runner

## Overview

Claude/Superpowers owns engineering judgment; this thin controller owns
immutable inputs, isolation, recovery, verification, and completion evidence.

## Run

Preinstall uv-managed normal-GIL CPython `>=3.13,<3.14` with
`uv python install 3.13`; then use the self-locating launcher:

```bash
./scripts/runner run \
  --workspace /absolute/repository \
  --spec /absolute/spec-a.md --spec /absolute/spec-b.md \
  --plan /absolute/plan-a.md --plan /absolute/plan-b.md
./scripts/runner inspect --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID --retry-blocked
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note "new evidence and changed strategy"
```

Repeat inputs in source order. Do not merge, rewrite, or positionally pair
them. Specs are immutable common context; plans run in one worktree and branch.
Every packet names the current plan only and excludes future-plan paths. Each
new plan starts a new UUID and session.

Use `resume` after controller interruption, `--retry-blocked` after an external
blocker changes, and `--retry-failed --strategy-note` only with meaningful new
input.

`SIGINT` and `SIGTERM` stop the active provider process group before exposing a
durable `resumable` checkpoint. If an interrupted implementation left
uncommitted work, that exact bounded Git worktree identity is sealed; resume
accepts it only while unchanged and rejects any drift as an integrity failure.

## Claude transport

Initial attempts use `claude -p`, `stream-json`, `--verbose`, an inline JSON schema,
and a new UUID through `--session-id`. Healthy same-plan continuation
uses its recorded UUID with `--resume`; implicit selection is forbidden. The
adapter scrubs nested-session markers and unrelated credentials.

The adapter supplies one variadic `--disallowedTools` flag against accidental
remote/destructive actions. It is not a security boundary against a same-UID
process; hard isolation belongs to Waygent/kernel.

## Recovery and completion

Canonical recovery sources are durable state, Git HEAD, ledger, and receipts,
not conversation memory. Prefer healthy same-plan session resume after a simple
interruption. Use a fresh-session fallback when resume fails or repeated
failure, stall, context overflow, abnormal compaction, or session damage makes
context suspect.

A live controller continues the bounded recovery loop itself in `recovering`;
it never delegates ordinary defect recovery to the user. Required retries use a
materially changed strategy. `resumable` means an external invocation must
restart a stopped controller. Only true external authority, unavailable
provider/runtime, irreconcilable requirements, exhausted changed strategies, or
integrity failure stop the run.

Keep lifecycle layers exact:

- Task status is `pending`, `running`, or `reported_done`.
- Plan status is `pending`, `running`, or `implemented`.
- Run status carries `recovering`, `resumable`, and
  `ready_for_integration`; never assign those values to a task or plan.

A plan becomes `implemented` only after its Git result and ledger are sealed.
The run becomes `ready_for_integration` only after every plan is implemented
and the declared verification set plus fresh final review succeed at one
unchanged candidate HEAD. The parent helper executes exact argv without a
shell, enforces each deadline, and seals receipts. A HEAD change invalidates
verification and review.

Do not merge, push, or deploy. Successful handoff records
`integration=not_observed`.

## Runtime and validation

Active commands never download Python or fall back to system Python. This
greenfield runner has no legacy state support. `./evals/run.sh` is deterministic
fake-provider validation; a live Claude canary is separate explicit evidence.

`run` and `resume` exit 0 only for `ready_for_integration`.
`inspect` exits 0 for any valid, readable run state; it does not assert
completion. `inspect` exits 64 for an unknown run and 65 for invalid state.
Run `./scripts/runner --help` and subcommand `--help` for the full CLI.
