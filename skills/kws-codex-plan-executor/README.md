# KWS Codex Plan Executor

CPE is a small sequential runner for approved Superpowers implementation
plans. It snapshots ordered inputs, creates one isolated worktree, launches one
fresh Codex process per plan, and resumes at the first incomplete plan.

## Release And Installation

Version 1.3.1 preserves the lean-quality contract and restores compatibility
with strict Codex structured-output schemas by normalizing nullable wire-only
optional fields before public contract validation. Focused deterministic tests
still reject partial or completed recovery-field triples and exercise two-pipe
drain behavior during timeout and exceptional launcher cleanup. Test fixtures
avoid child processes when the contract is purely a state or decision boundary,
while real processes remain mandatory for process groups, advisory locking,
coordinator loss, resume continuity, and result isolation.

The tracked skill directory is the release source of truth. Local Codex and
Claude Code installations should be linked to this directory rather than
copied, so a new session discovers the same versioned skill without creating a
second mutable installation.

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

`state.json` format version 1 remains authoritative and is atomically replaced;
no task, review, or usage records are added to it. Run creation records
`initializing`, verifies the exact branch, repository, path, and source commit,
then transitions to `running`. Inputs are copied before launch with their
SHA-256 digest, size, role, and role-local order. Private state uses `0700`
directories and `0600` files.

A child result requires exactly these base properties:

- `plan_id`, `status`, `head_commit`, `verification`, and `summary`;
- optional `retryable`, `failure_signature`, and `next_strategy`, which must
  appear together, are valid only for a non-completed result, and describe a
  structured recovery decision;
- optional `workflow_receipt`, which is valid only for completed output.

The strict structured-output wire schema declares every property as required,
because current Codex response schemas require that shape. Logically optional
properties are nullable on the wire and are normalized away before the public
format-version-1 conditional-presence rules above are validated.

The result schema keeps the additional properties optional so historical
result files and completed format-1 runs remain readable. Every newly launched
completed attempt must include the workflow receipt. Its exact contract is:

```json
{
  "mode": "subagent-driven-lean",
  "progress_ledger": ".superpowers/sdd/progress.md",
  "task_reviews": "complete",
  "final_review": "approved",
  "final_review_artifact": ".superpowers/sdd/final-review.md",
  "duplicate_verification": "none"
}
```

The two artifact paths must be non-empty safe relative paths to existing
regular, non-symlink files inside the worktree; absolute paths, parent
traversal, symlink components, and paths outside the worktree are rejected.
The workflow receipt and top-level verification remain child-reported evidence.
CPE binds that evidence mechanically to the exact clean worktree `HEAD`, checks
ancestry from the plan start, requires non-empty successful verification, and
seals an accepted result read-only.

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
  direct-child reap, and bounded group-quiescence confirmation. Transient
  `EPERM` is treated as a still-live group; persistent `EPERM` fails cleanup
  closed instead of spinning forever. Deterministic fixtures use a `0.02`
  second cleanup grace where the case does not test the production default.
- Codex stdout is a newline-delimited JSON event stream. CPE filters only the
  final `turn.completed.usage` totals in bounded memory; it does not retain the
  raw stdout JSON as an attempt log, `events.jsonl` transcript, or second
  artifact.
- Ordinary child diagnostics remain on stderr and pass through a bounded
  writer. The on-disk attempt log compacts at two MiB and retains at most a
  one-MiB stderr tail with an explicit discarded-byte marker.
- Attempt number, result path, and a private regular placeholder are persisted
  before launch. Numeric attempt identity selects prior evidence correctly for
  attempt 10 and later.
- Codex uses an ephemeral session and returns the strict schema object as its
  final response. `--output-last-message` persists only the current result;
  accepted result evidence is changed to read-only mode `0400`.
- The existing `plan.attempt_finished` event may include `duration_ms`, final
  aggregate `input_tokens`, `cached_input_tokens`, `output_tokens`,
  `reasoning_output_tokens`, and `launcher_prompt_bytes`. Missing or malformed
  usage is unavailable and does not affect completion.

## Completion, Failure, And Recovery

- `completed` (exit 0): every ordered plan has an accepted clean commit.
- `failed` (exit 1): invocation failure, runner-integrity failure, or exhausted
  plan attempts.
- `blocked` (exit 2): the current plan requires operator-owned resolution.
- `interrupted` (exit 3): durable state remains available for resume.

Automatic recovery is conditional and evidence-driven:

| Observation | Action |
|---|---|
| timeout or coordinator interruption | one fresh recovery attempt |
| child-reported retryable product failure | one fresh attempt using the reported changed strategy |
| blocked or operator-owned decision | stop without automatic retry |
| non-retryable failure | stop without automatic retry |
| invalid result, wrong `HEAD`, broken ancestry, or dirty completed handoff | fail closed without product retry |
| repeated failure signature | stop without another automatic attempt |
| explicit `resume --retry-failed` | grant one operator-initiated attempt |

Before recovery CPE writes one private regular `0600` recovery capsule under
the existing results directory. It contains only the plan ID and attempt,
starting commit and current `HEAD`, bounded completed-task and current-task
ledger hints, prior status, bounded failure signature and next strategy, up to
100 dirty-file entries, and prior result/log paths. The capsule is derived from
state, Git, prior evidence, and at most 64 KiB of the Superpowers progress
ledger; it is not a task graph or semantic plan parser.

The fresh controller reads the recovery capsule, progress ledger, Git status
and log, and current task artifacts in that order. It reuses existing commits,
reports, and completed-task ledger evidence and never redispatches a completed
ledger task. Targeted prior result or bounded log evidence is read only when
those sources are insufficient.

Recovery remains plan-level. CPE does not maintain task-level checkpoints,
interpret plan prose, own product quality policy, merge, or push.

An `initializing` resume reuses a worktree only when repository, branch, path,
and source commit all match. An absent worktree may be recreated from the
recorded source. Ambiguous or mismatched evidence fails closed without deletion.

## Lean Superpowers Contract

CPE launches one fresh controller for each approved plan. Superpowers owns
task execution, TDD, reviews, consolidated fixes, the cross-task final review,
final product verification, and commits. CPE owns the durable plan boundary,
bounded recovery, and mechanical handoff validation; it does not independently
prove review quality.

- The controller uses file-backed task briefs, implementer reports, review
  packages, task review files, a final-review file, and
  `.superpowers/sdd/progress.md`. Compact returns keep only status, commits,
  one-line test evidence, finding IDs, decisions, and the next action in
  controller context.
- Implementers run plan-declared focused RED/GREEN verification and tests
  affected by later fixes. No task gets an automatic full-suite run unless
  broader verification is itself an approved task deliverable.
- Reviewers reuse recorded evidence and inspect task briefs, reports, and
  file-backed diffs. One consolidated fix pass resolves a task finding set;
  the reviewer then checks only the delta and affected evidence.
- After all tasks, one whole-branch review checks cross-task interfaces,
  regressions, global constraints, and unresolved findings. It does not replay
  each task review.
- The plan controller runs one final full verification at the final HEAD. The
  same normalized command is not run twice at one `HEAD` unless the first
  observation was an explicitly recorded transient infrastructure failure or
  the approved plan intentionally tests mutable external state.

A weak approved plan that lacks focused task commands or a final verification
command produces a plan-contract blocker. The controller does not invent broad
package or repository tests to repair the plan at runtime.

## Limitations

- Process groups and advisory locking require POSIX `setsid`, signals, and
  `fcntl`; Windows portability is not provided.
- A hard machine shutdown can leave an `initializing` run that requires normal
  resume reconciliation.
- The bounded log tail can omit early diagnostics; the truncation marker and
  discarded-byte count make that loss explicit.
- The workflow receipt, reviews, and verification array are child-reported
  evidence. CPE validates their shape, safe artifact locations, exact clean
  `HEAD`, and successful exit codes, but does not independently judge review
  quality or rerun product verification after acceptance.
- Attempt usage totals can aggregate the root controller and nested subagents.
  They are not a root-controller measurement or a root-versus-subagent split.
- Missing plan-focused or final verification is a plan-contract blocker, not
  permission for CPE to invent broad tests.
- Environment filtering is best-effort defense, not a complete secret boundary.

## Change Protocol

Every change to the public CLI, exit meanings, state semantics, process
lifecycle, retry policy, or completion acceptance must add or update a focused,
deterministic fixture. Evals must remain sequential, credential-free,
network-free, model-free, and below the fifteen-second ceiling. Twelve seconds
or less is the target on the development machine. State-only recovery decisions
may use direct boundary fixtures; process lifecycle and isolation claims must
retain real-process coverage.

## Verify

```bash
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
```

`./evals/run.sh` is the only complete behavioral gate. Run it once at the final
revision after the whole-branch review, then run the static syntax and public
help checks above. Do not repeat an identical command at the same `HEAD` unless
its first observation was an explicitly recorded transient infrastructure
failure. The deterministic gate is sequential, network-free, credential-free,
and model-free; its hard ceiling is fifteen seconds and its target is twelve
seconds or less on the development machine.

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
