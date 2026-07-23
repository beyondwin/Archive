# KWS Codex Plan Runner

An independent, quality-first controller for implementing approved Superpowers
specifications and ordered plans through headless Codex. It delegates engineering
judgment to Codex/Superpowers while making recovery and completion durable and
fail-closed.

## Runtime

Install the managed interpreter before starting or resuming a run:

```bash
uv python install 3.13
```

The runtime contract is normal-GIL CPython `>=3.13,<3.14`, managed by `uv`, with
standard-library-only runner code. The self-locating `./scripts/runner` resolves
its own directory and invokes the already-installed managed interpreter. It
passes `--no-python-downloads` and has no active-run download or system-Python
fallback.

## Public commands

Run from this directory. Inputs may live anywhere, but paths should be absolute.

```bash
./scripts/runner run \
  --workspace /absolute/repository \
  --spec /absolute/spec-a.md \
  --spec /absolute/spec-b.md \
  --plan /absolute/plan-01.md \
  --plan /absolute/plan-02.md \
  [--stall-seconds 3600] \
  [--model MODEL] \
  [--sandbox workspace-write|danger-full-access]

./scripts/runner resume --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID --retry-blocked
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note "new evidence and changed strategy"

./scripts/runner inspect --run-id RUN_ID
```

`--spec` and `--plan` are repeatable and preserve CLI order. Every input is
snapshotted with its absolute path and digest. Specs form immutable common
context; plans run sequentially in one isolated worktree/branch with no positional pairing
between `spec[i]` and `plan[i]`. The provider receives all
specs but only the current plan target. A completed prior plan is represented by
Git, ledger, and receipts, not its provider conversation.

`--model` is an explicit user selection, not an automatic escalation policy.
The default sandbox is `workspace-write`. The stall lease defaults to 3600
seconds and is renewed only by material progress; a live process or repeated
heartbeat alone is not progress.

## Resume and recovery

Plain `resume` reconciles durable state with the exact worktree/Git identity.
For a simple same-plan interruption it prefers the explicitly recorded healthy
Codex session, then falls back to a fresh session. Suspected context corruption,
repeated failure, context overflow, or a failed resume starts a fresh session
with a changed strategy. Every new plan always starts a new session.

`SIGINT` and `SIGTERM` terminate and reap the isolated provider process group
before atomically exposing an external `resumable` state. An interrupted
implementation may resume an uncommitted partial tree only when its HEAD,
branch, porcelain digest, and bounded content digest exactly match the sealed
checkpoint; arbitrary dirty state or later drift fails closed without launching
another provider.

While the controller remains alive, provider loss, session loss, and stall
outcomes enter a bounded automatic `recovering` loop; the user is not asked to
drive ordinary defect repair. `resumable` is reserved for a stopped controller
that needs another invocation. Use `--retry-blocked` only after an external
blocker changes. `--retry-failed` requires a non-empty `--strategy-note`, so it
cannot silently reset and repeat the same strategy.

Canonical recovery evidence is under `~/.codex/plan-runner`; isolated worktrees
are under `~/.codex/worktrees/plan-runner`. Session memory is an optimization,
not a source of correctness.

## Verification and completion

The provider declares the final verification set for a candidate HEAD. A
parent-owned helper executes each exact argv directly, without a shell, under a
deadline and seals immutable receipts. All required commands and a structured
fresh final review must succeed at the same final HEAD. A HEAD change invalidates
both verification and review evidence. When no executable verification applies,
the provider must give a structured rationale and final review must approve it.

Task status is `pending/running/reported_done`; plan status is
`pending/running/implemented`. Only the run-level status
`ready_for_integration` is final success. The runner does not merge, push, or
deploy; every successful handoff records `integration=not_observed`.

`run` and `resume` exit 0 only for `ready_for_integration`.
`inspect` exits 0 for any valid, readable run state; it reports state and does
not assert completion. `inspect` exits 64 for an unknown run and 65 for invalid state.

| Exit code | Contract |
|---:|---|
| `run`/`resume`: 0 | Run is `ready_for_integration`. |
| `inspect`: 0 | Valid state was read, regardless of lifecycle status. |
| 2 | Controller stopped with durable externally `resumable` state. |
| 3 | External/runtime/provider authority is `blocked`. |
| 4 | Run failed after bounded recovery or provider failure. |
| 64 | Invocation or immutable input is invalid. |
| 65 | State, Git, receipt, or helper integrity check failed. |
| 70 | Unexpected internal failure. |

## Security boundary

Credential minimization, noninteractive Git settings, deny rules, source-ref
checks, and exact-argv execution reduce accidental remote mutation. They do not
contain a malicious process running as the same UID. Hard isolation is a
Waygent/kernel responsibility.

## Validation

Deterministic validation never invokes a real model:

```bash
./evals/run.sh
```

A live Codex canary is separate, opt-in evidence. Offline success must not be
reported as provider compatibility, and live evidence must not replace the
deterministic gate.
