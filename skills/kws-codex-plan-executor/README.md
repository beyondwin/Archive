# KWS Codex Plan Executor

CPE is a small sequential runner for approved Superpowers implementation
plans. It snapshots ordered inputs, creates one isolated worktree, launches one
fresh Codex process per plan, and resumes at the first incomplete plan.

## Requirements

- Python 3 standard library
- Git
- `codex` on `PATH`
- a Git workspace without tracked changes
- absolute, readable UTF-8 specification and plan paths
- at least one plan

The deterministic evals use no network, provider credential, or model call.

## Commands

```bash
python3 scripts/cpe.py run \
  --spec /abs/spec-a.md --spec /abs/spec-b.md \
  --plan /abs/plan-01.md --plan /abs/plan-02.md \
  --workspace /abs/repository

python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py resume --run-id RUN_ID --retry-failed
python3 scripts/cpe.py inspect --run-id RUN_ID
```

Plan flag order is execution order. Every plan session receives all immutable
specification snapshot paths and its current plan snapshot. Later plans start
from the accepted commit of the preceding plan in the same worktree.

## State And Results

```text
CODEX_HOME/orchestrator/RUN_ID/
  state.json
  events.jsonl
  run.lock
  inputs/
  results/
  logs/

CODEX_HOME/worktrees/RUN_ID/
```

`state.json` format version 1 is authoritative and atomically replaced. Run
creation records `initializing`, verifies the exact branch, repository, path,
and source commit, then transitions to `running`.
`events.jsonl` records concise transitions; child output remains in `logs/`.
Inputs are copied before launch with their SHA-256 digest, size, role, and
role-local order. Private state uses `0700` directories and `0600` files.

A child result has exactly `plan_id`, `status`, `head_commit`, `verification`,
and `summary`. Completed is accepted only when the reported commit is the exact
clean worktree `HEAD`, descends from the plan start, and every non-empty
verification entry has exit code zero.

State validation also enforces the completed prefix, current index, pristine
future plans, attempt evidence, run/plan status agreement, and private regular
result files. Structurally valid but semantically impossible state is rejected
before Git mutation or child launch.

## Operational Safety

- One POSIX advisory lock serializes every mutating `run` and `resume`. A
  competitor returns transient `interrupted` with `run_busy` and does not
  increment attempts or launch a child.
- The lock descriptor is inherited by the child, so coordinator loss does not
  admit a second resume while that child remains alive.
- Each child runs in a new process group. Timeout, `SIGINT`, and `SIGTERM`
  trigger group-wide `SIGTERM`, a short grace period, `SIGKILL` when needed,
  direct-child reap, and group-quiescence confirmation.
- Attempt output is streamed through a bounded writer. The on-disk log compacts
  at two MiB and retains at most a one-MiB tail with an explicit discarded-byte
  marker.
- Attempt number, result path, and a private regular placeholder are persisted
  before launch. Numeric attempt identity selects prior evidence correctly for
  attempt 10 and later.
- Codex uses an ephemeral session and returns the strict schema object as its
  final response. `--output-last-message` persists only the current result;
  accepted result evidence is changed to read-only mode `0400`.

## Completion, Failure, And Recovery

- `completed` (exit 0): every ordered plan has an accepted clean commit.
- `failed` (exit 1): invocation failure, runner-integrity failure, or exhausted
  plan attempts.
- `blocked` (exit 2): the current plan requires operator-owned resolution.
- `interrupted` (exit 3): durable state remains available for resume.

An initial attempt and one recovery attempt are automatic. Invalid output,
wrong commit, broken ancestry, or a dirty successful handoff fails immediately.
`resume --retry-failed` grants exactly one additional attempt to the failed
current plan. Repeating it is a new explicit operator action.

Recovery is plan-level. A fresh process inspects Git, prior result and log
paths, and any Superpowers progress artifact. CPE does not maintain task-level
checkpoints, interpret plan prose, own product quality policy, merge, or push.

An `initializing` resume reuses a worktree only when repository, branch, path,
and source commit all match. An absent worktree may be recreated from the
recorded source. Ambiguous or mismatched evidence fails closed without deletion.

## Limitations

- Process groups and advisory locking require POSIX `setsid`, signals, and
  `fcntl`; Windows portability is not provided.
- A hard machine shutdown can leave an `initializing` run that requires normal
  resume reconciliation.
- The bounded log tail can omit early diagnostics; the truncation marker and
  discarded-byte count make that loss explicit.
- CPE validates reported verification evidence but does not rerun product
  verification after an accepted Superpowers handoff.
- Environment filtering is best-effort defense, not a complete secret boundary.

## Change Protocol

Every change to the public CLI, exit meanings, state semantics, process
lifecycle, retry policy, or completion acceptance must add or update a focused,
deterministic fixture. Evals must remain sequential, credential-free,
network-free, model-free, and below the fifteen-second gate.

## Verify

```bash
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
codex exec --help
```

The eval suite is sequential, network-free, credential-free, and must remain
below 15 seconds on the development machine.

## Tracked Inventory

```text
README.md
SKILL.md
evals/check_cli.py
evals/check_runner.py
evals/fake_codex.py
evals/run.sh
scripts/cpe.py
scripts/cpe_runtime/__init__.py
scripts/cpe_runtime/launcher.py
scripts/cpe_runtime/runner.py
scripts/cpe_runtime/state.py
templates/plan-result-schema.json
```
