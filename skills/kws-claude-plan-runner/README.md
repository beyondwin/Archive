# KWS Claude Plan Runner

Current release: `2.0.0`.

An independent thin wrapper for approved Superpowers specifications and ordered
plans executed through Claude Code. Superpowers owns task decomposition, SDD
dispatch, TDD, task review, fixes, and the final whole-branch review. The
runner owns exact external facts and fail-closed evidence.

## Runtime

```bash
uv python install 3.13
```

The runtime is uv-managed normal-GIL CPython `>=3.13,<3.14`. Production Python
is standard-library-only. Active commands never download Python or fall back to
system Python.

## Public commands

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

`--spec` and `--plan` preserve CLI order with no positional pairing. They are
immutable inputs handed unchanged to Superpowers. Every provider root receives
all specifications and the current plan only; prior plans pass forward through
ordered Git handoff HEADs, digests, and receipts.

## Thin Superpowers boundary

Superpowers owns the task/review/fix workflow and its ledger. The runner does
not mirror that state. It owns immutable input digests, one worktree, plan
order, root recovery actions, ordered handoff HEADs, accepted verification
digests, exact receipts, and the final run/integration outcome.

Every plan starts with a fresh root. Each plan has at most one healthy root
resume and one fresh-root fallback. The transport uses an explicit new UUID for
the fresh root and the recorded UUID for `--resume`; provider-private UUIDs and
stream details are not part of cross-provider parity.

An interrupted dirty checkpoint seals HEAD, branch, porcelain, and bounded
content digests for drift detection. It is not a backup and cannot restore
files. On `SIGINT` or `SIGTERM`, the runner records the current attempt and
provider process group, requires that group to become quiescent, and exposes a
resumable checkpoint only after sealing the exact dirty worktree identity. An
unchanged checkpoint resumes the recorded healthy session; drift fails before
another provider launch.

## Verification and completion

The final plan carries all immutable requirements and owns the single final
whole-branch review. The runner executes declared exact argv without a shell,
applies deadlines, and seals receipts. Every required command and the review
must accept one unchanged candidate HEAD.

The final helper derives the exact ordered duplicate-free union of all sealed
plan verification declarations at the final HEAD. The final handoff and
accepted verification digest bind that run-level union.

Do not merge, push, or deploy. Provider packets set
`integration_policy=keep`; success records `integration=not_observed`.

Version 1 state is inspect-only. Version 2 is required for active run, resume,
and recovery.

`run` and `resume` exit 0 only for `ready_for_integration`.
`inspect` exits 0 for any valid, readable run state; it reports state rather
than asserting completion.
`inspect` exits 64 for an unknown run and 65 for invalid state.

| Exit code | Contract |
|---:|---|
| `run`/`resume`: 0 | Run is `ready_for_integration`. |
| `inspect`: 0 | Valid state was read. |
| 2 | Externally `resumable`. |
| 3 | External authority is `blocked`. |
| 4 | Bounded recovery or provider failure. |
| 64 | Invocation or immutable input is invalid. |
| 65 | State, Git, receipt, or integrity failure. |
| 70 | Unexpected internal failure. |

## Validation

```bash
./evals/run.sh
```

From the repository root, run the canonical gate and the two live release
canaries:

```bash
bun run agent:verify -- --base MERGE_BASE --head CANDIDATE_HEAD

./scripts/agent/plan-runner-live-canary \
  --provider all \
  --mode ownership
./scripts/agent/plan-runner-live-canary \
  --provider all \
  --mode interruption
```

The fake-provider suite is deterministic. A live Claude canary is separate
opt-in evidence; the release commands above invoke both installed providers.
