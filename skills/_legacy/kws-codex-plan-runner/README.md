# KWS Codex Plan Runner

Current release: `2.0.0`.

An independent thin wrapper for implementing approved Superpowers
specifications and ordered plans through headless Codex. Superpowers owns task
decomposition, SDD dispatch, TDD, task review, fixes, and the final whole-branch
review. The runner owns exact external facts and fail-closed evidence.

## Runtime

Install uv-managed normal-GIL CPython `>=3.13,<3.14` before starting:

```bash
uv python install 3.13
```

The self-locating launcher uses the already-installed managed interpreter with
no downloads or system-Python fallback. Initial and resumed launches use
`--ignore-user-config`, `--ignore-rules`, `--strict-config`,
`approval_policy="never"`, and the selected sandbox. `--ignore-rules` disables
Codex execpolicy rules; it does not disable the runner's explicit safety and
evidence checks. `danger-full-access` removes filesystem mediation, not TCC,
Keychain, or other host authority. The effective `CODEX_HOME` remains visible.

## Public commands

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
```

`--spec` and `--plan` are repeatable and preserve CLI order.
There is no positional pairing. They are immutable inputs handed unchanged to Superpowers. The
provider sees all specifications and the current plan only. Prior plans pass
forward through ordered Git handoff HEADs, digests, and receipts.

## Thin Superpowers boundary

Superpowers v6.2.0 owns its plan workspace, `subagent-driven-development`,
task briefs, review packages, fixes, cleanup, and the single final whole-branch
review. The public capability surface is `sdd-workspace`, `task-brief`, and
`review-package`. The runner does not parse or migrate those internals and does
not mirror individual subagent state.

The runner owns immutable input digests, one isolated worktree, plan order,
root launch/recovery decisions, ordered handoff HEADs, accepted verification
digests, exact receipts, and the final run/integration outcome. It remains a
strategic recovery shell, not another engineering workflow.

## Recovery

Every plan starts with a fresh root. Each plan has at most one healthy root
resume and one fresh-root fallback. A live controller continues bounded
recovery itself. Use `resume` only for an externally `resumable` controller,
`--retry-blocked` after an external blocker changes, and
`--retry-failed --strategy-note` after bounded recovery fails.

Authorized model or sandbox changes are sealed as an
`execution_profile_transition`; provider runtime gaps use
`provider_capability_blocked`. Host authority gaps use
`host_permission_blocked`. Equivalent intent admission reports
`matching_run_exists` with an exact next action.

Only `refs/codex/turn-diffs/captures/` and
`refs/codex/turn-diffs/checkpoints/` are volatile. The active repair surface is
revision-guarded `volatile-codex-turn-refs`. Recorded process group and
descendant PID quiescence is necessary before accepting an interrupted dirty
checkpoint.

A dirty checkpoint is drift detection: it seals HEAD, branch, porcelain, and
bounded content digests. It is not a backup and cannot restore files.
On `SIGINT` or `SIGTERM`, the runner records the current attempt and provider
process group, requires that group to become quiescent, and exposes a resumable
checkpoint only after sealing the exact dirty worktree identity. An unchanged
checkpoint resumes the recorded healthy session; drift fails before another
provider launch.

## Verification and completion

The final plan carries all immutable requirements and owns the single final
whole-branch review. The runner executes declared exact argv without a shell,
applies deadlines, and seals receipts. Every required command and the review
must accept the same candidate HEAD. Every prior plan handoff HEAD is an
ancestor of that candidate.

The final helper derives the exact ordered duplicate-free union of all sealed
plan verification declarations at the final HEAD. The final handoff and
accepted verification digest bind that run-level union.

Do not merge, push, or deploy. Provider packets set
`integration_policy=keep`; success records `integration=not_observed`.

Version 1 state is inspect-only. Version 2 is required for active run, resume,
and recovery.

`run` and `resume` exit 0 only for `ready_for_integration`.
`inspect` exits 0 for any valid, readable run state; it reports state and does
not assert completion.
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

Deterministic validation does not prove live Codex compatibility. Live canaries
remain separate opt-in evidence and invoke both installed providers.
