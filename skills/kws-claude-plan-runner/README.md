# KWS Claude Plan Runner

An independent quality-first controller for approved Superpowers
specifications and ordered implementation plans executed through Claude Code.
Claude/Superpowers owns engineering decisions; the controller supplies durable,
fail-closed recovery and completion evidence.

## Runtime

Install the managed interpreter before starting or resuming:

```bash
uv python install 3.13
```

The runtime is uv-managed normal-GIL CPython `>=3.13,<3.14`. Production Python
uses only the standard library. The self-locating launcher resolves its own
directory and an already-installed managed interpreter with
`--no-python-downloads`; active commands never download Python or use system
Python fallback.

## Public commands

Run from this directory. Input paths should be absolute.

```bash
./scripts/runner run \
  --workspace /absolute/repository \
  --spec /absolute/spec-a.md \
  --spec /absolute/spec-b.md \
  --plan /absolute/plan-01.md \
  --plan /absolute/plan-02.md \
  [--stall-seconds 3600] \
  [--model MODEL]

./scripts/runner resume --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID --retry-blocked
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note "new evidence and changed strategy"
./scripts/runner inspect --run-id RUN_ID
```

`--spec` and `--plan` preserve CLI order. Inputs are snapshotted by absolute
path and digest. Specs are immutable common context with no positional pairing
to plans. Plans execute sequentially in one isolated worktree/branch. Provider
packets expose all specs and only the current plan; prior plans pass forward
through Git, ledger, and receipts, not conversation history.

`--model` is an explicit user choice, never automatic escalation. The stall
lease defaults to 3600 seconds and renews only on material progress, not mere
process existence or repeated output.

## Claude sessions and recovery

Initial attempts use `claude -p --output-format stream-json --verbose`, an
inline JSON schema, and an explicit new UUID through `--session-id`. Healthy
same-plan recovery uses the recorded UUID through `--resume`. Each new plan
always uses a fresh session. Nested Claude markers and unrelated credentials
are removed before launch.

One variadic `--disallowedTools` flag reduces accidental remote mutation. It is
not same-UID containment; hard isolation is a Waygent/kernel responsibility.

Plain `resume` reconciles durable state with the exact worktree and Git
identity. Simple interruptions prefer healthy session resume. Repeated failure,
stall, context overflow, abnormal compaction, session damage, or failed resume
uses a durable fresh session with a changed strategy.

While the controller is alive, provider/session loss and stalls enter a bounded
automatic `recovering` loop. `resumable` is reserved for a stopped controller
requiring another invocation. `--retry-blocked` follows correction of a real
external blocker. `--retry-failed` requires a non-empty `--strategy-note`.

Canonical recovery state lives under `~/.claude/plan-runner`; isolated
worktrees live under `~/.claude/worktrees/plan-runner`. This 1.0.0 greenfield
runner has no legacy run-state compatibility.

## Verification and completion

The provider declares the final command set for a candidate HEAD. A
parent-owned helper executes exact argv without a shell, applies command
deadlines, and seals immutable receipts. Every required command and a
structured fresh final review must succeed at the same unchanged HEAD. When no
executable verification applies, a structured rationale and approving final
review are still required.

Task status is `pending/running/reported_done`; plan status is
`pending/running/implemented`. Only run status `ready_for_integration` is final
success. The runner never merges, pushes, or deploys and records
`integration=not_observed`.

`run` and `resume` exit 0 only for `ready_for_integration`.
`inspect` exits 0 for any valid, readable run state; it reports state rather
than asserting completion. `inspect` exits 64 for an unknown run and 65 for invalid state.

| Exit code | Contract |
|---:|---|
| `run`/`resume`: 0 | Run is `ready_for_integration`. |
| `inspect`: 0 | Valid state was read, regardless of lifecycle status. |
| 2 | Controller stopped with durable externally `resumable` state. |
| 3 | External/runtime/provider authority is `blocked`. |
| 4 | Run failed after bounded recovery or provider failure. |
| 64 | Invocation or immutable input is invalid. |
| 65 | State, Git, receipt, or helper integrity failed. |
| 70 | Unexpected internal failure. |

## Validation

Deterministic validation uses the fake Claude provider and never invokes a real
model:

```bash
./evals/run.sh
```

A real Claude canary is separate opt-in evidence. Offline success must not be
reported as live provider compatibility.
