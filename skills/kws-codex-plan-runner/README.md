# KWS Codex Plan Runner

An independent thin wrapper for implementing approved Superpowers
specifications and ordered plans through headless Codex. Superpowers owns the
engineering workflow; the runner supplies durable isolation, recovery, and
completion evidence.

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

The effective `CODEX_HOME` remains visible so installed authentication and
Superpowers are available. Both initial and resumed Codex launches use
`--ignore-user-config`, `--ignore-rules`, `--strict-config`,
`-c 'approval_policy="never"'`, and the selected sandbox. For unattended local
execution, select `danger-full-access`; it removes filesystem sandbox
mediation, not host-level TCC or Keychain authority.

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
  --retry-blocked --sandbox danger-full-access \
  --strategy-note "workspace-write capability is blocked; use authorized full access"
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note "new evidence and changed strategy" \
  --model MODEL

./scripts/runner inspect --run-id RUN_ID

./scripts/runner repair --run-id RUN_ID --expected-revision N \
  --repair-kind volatile-codex-turn-refs \
  --strategy-note "verified ref-only drift"
./scripts/runner repair --run-id RUN_ID --expected-revision N \
  --repair-kind unsealed-provider-partial \
  --attempt-id ATTEMPT_ID \
  --strategy-note "verified provider partial"
```

`unsealed-provider-partial` remains a recognized compatibility surface, but
new adoption is currently disabled and fails closed. Same-host PID/PGID polling
cannot prove that no descendant escaped with `setsid()` before observation.

`--spec` and `--plan` are repeatable and preserve CLI order. Every input is
snapshotted with its absolute path and digest. Specs form immutable common
context; plans run sequentially in one isolated worktree/branch with no positional pairing
between `spec[i]` and `plan[i]`. The provider receives all
specs but only the current plan target. A completed prior plan is represented by
Git, ledger, and receipts, not its provider conversation.
Every prior plan handoff HEAD is required to remain an ancestor of the current
candidate; resetting or dropping an earlier plan fails closed.

`--model` is an explicit user selection, not an automatic escalation policy.
The default sandbox is `workspace-write`. The stall lease defaults to 3600
seconds and is renewed only by material progress; a live process or repeated
heartbeat alone is not progress.

## Thin-wrapper ownership

Superpowers owns task decomposition, SDD dispatch, TDD, task review, and its
ledger. Superpowers v6.2.0 also owns its plan-scoped workspace, task briefs,
review packages, bounded fix loop, and cleanup through the public
`subagent-driven-development` workflow. Compatibility is judged by those
capabilities rather than exact version-string equality.
The public helper surface used by that workflow is `sdd-workspace`,
`task-brief`, and `review-package`; the runner depends on those interfaces, not
their private storage layout.

The runner owns immutable inputs, one isolated worktree, root launch/resume,
checkpoint-before-result handling, bounded strategic external recovery, and
final evidence. It does not mirror individual subagent state, and collaboration
events are only bounded activity signals. It does not parse or migrate those
internals.

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
Historical partial evidence is preserved but not adopted. Recorded process
group and descendant PID quiescence is necessary but not sufficient because it
cannot prove the absence of an unrecorded detached descendant. The runner does
not recommend this repair and leaves the run unchanged.

While the controller remains alive, provider loss, session loss, and stall
outcomes enter a bounded automatic `recovering` loop; the user is not asked to
drive ordinary defect repair. `resumable` is reserved for a stopped controller
that needs another invocation. Use `--retry-blocked` only after an external
blocker changes. `--retry-failed` requires a non-empty `--strategy-note`, so it
cannot silently reset and repeat the same strategy.

An authorized blocked or failed retry may select a different sandbox or model
on the same logical run. The initial immutable profile is retained, the
effective change is sealed as an `execution_profile_transition`, and the next
provider launch always uses a fresh session. Unchanged, unauthorized, or
tampered transitions fail before provider launch.

The wrapper is a strategic recovery shell, not a second workflow engine. An
unexpected external failure first preserves the latest checkpoint, then changes
one relevant strategy dimension and autonomously resumes the same goal. It
blocks only for missing external authority or an unprovable load-bearing
identity, ref, path, digest, state, or acceptance invariant. Filesystem
capability failures use `sandbox_capability_blocked`; macOS TCC, Keychain, and
other host permission failures use `host_permission_blocked` and are not
auto-approved. Provider-runtime capability gaps use
`provider_capability_blocked`.

Equivalent execution intents are serialized before run allocation. A refusal
uses `matching_run_exists`, names the existing branch/worktree, and recommends:

| Existing state | Action |
|---|---|
| `running`, `recovering`, `ready_for_integration` | `inspect --run-id ID` |
| `resumable` | `resume --run-id ID` |
| `blocked` | Fix the named blocker, then `resume --run-id ID --retry-blocked`. |
| Retryable `failed` | `resume --run-id ID --retry-failed --strategy-note TEXT` |
| Known repair evidence | Use the exact revision-guarded `repair` command reported by the runner. |
| Invalid or unproven match | Preserve evidence and fail closed. |

Only `refs/codex/turn-diffs/captures/` and
`refs/codex/turn-diffs/checkpoints/` are treated as volatile. Product and
unknown refs remain protected. Historical recovery is limited to the two exact
repair kinds shown above; only volatile-ref repair can currently change a run.
Partial repair preserves evidence and fails closed. Repair never launches a
provider, mutates Git, resets, rebases, merges, pushes, or deploys.
Legacy state without a volatile-ref policy remains readable only while the
protected observation still matches. A recognized volatile-only drift is
reported with its current observation and exact revision-guarded repair action;
successful repair creates the audit evidence that authorizes the current
versioned interpretation.

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

The repository-wide canonical final gate is run once at the final candidate
HEAD:

```bash
bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD
```
