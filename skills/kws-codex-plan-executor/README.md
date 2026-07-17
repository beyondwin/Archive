# KWS Codex Plan Executor

CPE is a small sequential runner for approved Superpowers implementation
plans. It snapshots ordered inputs, creates one isolated worktree, launches
bounded controller slices for one plan at a time, and resumes at the first
incomplete plan.

## Release And Installation

Version 2.0.0 is the format-2 release. Run state, child results, compiled
indexes, and optimization reports use only their current format-2 contracts;
format-1 run state is neither read nor migrated. Format 2 consumes a strict
append-only execution-ledger event schema. The release adds typed
parent-observed capability blockers, progress-aware controller slices, fixed
checkpoint and launch budgets, strict evidence ingestion, and local result
envelope repair. It retains process-group cleanup, advisory locking, bounded
two-pipe draining, strict structured output, and the minimum linked-worktree
Git write grant.

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
~/.codex/orchestrator/<run-id>/
  state.json
  events.jsonl
  run.lock
  inputs/
  results/
  logs/
  evidence/
  reports/

~/.codex/worktrees/<run-id>/
```

These paths use the default Codex home; an explicit `CODEX_HOME` replaces the
`~/.codex` prefix. Runtime artifacts never belong in the source repository.
Attempt diagnostics are stored at
`~/.codex/orchestrator/<run-id>/logs/<plan-id>-attempt-<n>.log`. The derived
operator views are
`~/.codex/orchestrator/<run-id>/reports/optimization-report.json` and
`~/.codex/orchestrator/<run-id>/reports/optimization-report.md`.

`state.json` format version 2 is authoritative and atomically replaced. Run
creation records `preparing`, persists immutable input snapshots and the
compiled operator contract, creates and verifies the exact branch, repository,
worktree path, and source commit, then becomes `ready` or `running`. Inputs are
copied with their SHA-256 digest, size, role, and role-local order. Private
directories use `0700`; mutable private files use `0600`; accepted result
evidence uses `0400`.

A child result requires exactly these base properties:

- `plan_id`, `status`, `head_commit`, `verification`, and `summary`;
- optional `checkpoint`, required only when status is `checkpointed`;
- optional `blocker`, required only when status is `blocked`;
- optional `workflow_receipt`, required only when status is `completed`.

The strict structured-output wire schema declares every property as required,
because current Codex response schemas require that shape. Logically optional
properties are nullable on the wire and are normalized away before the
format-2 conditional-presence rules above are validated. Every completed slice
must include this workflow receipt:

```json
{
  "ledger_path": ".superpowers/sdd/execution-ledger.jsonl",
  "final_review_path": ".superpowers/sdd/final-review.md",
  "final_review_head": "0123456789abcdef0123456789abcdef01234567",
  "open_finding_ids": [],
  "open_obligation_ids": []
}
```

The two paths must resolve to existing regular, non-symlink files inside the
worktree. Normal completion requires safe relative spellings; absolute paths,
parent traversal, symlink components, and paths outside the worktree are
rejected. `final_review_head` must equal the exact clean worktree `HEAD`, the
open-finding list must be empty, and the open-obligation list must equal the
strict ledger projection (therefore it is empty for acceptance). Each
verification record carries a stable command ID, argv digest, phase, evidence
key, exit code, and optional receipt path. Completion requires successful
branch-final evidence.

The workflow receipt and verification array remain child-attested evidence.
CPE ingests and binds them mechanically to the exact clean `HEAD`, validates
ancestry from the plan start and the strict ledger, seals copied evidence, and
makes the accepted result read-only. Superpowers, not CPE, decides whether the
implementation, reviews, fixes, and verification are correct.

State validation also enforces the completed prefix, current index, pristine
future plans, attempt evidence, run/plan status agreement, and private regular
result files. Structurally valid but semantically impossible state is rejected
before Git mutation or child launch.

## Operational Safety

- One POSIX advisory lock serializes every mutating `run` and `resume`. A
  competitor returns durable `checkpointed` with `run_busy` and does not
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
- The child keeps the `workspace-write` sandbox. The launcher resolves the
  worktree's exact Git common directory and supplies only that path as an
  additional writable root, enabling linked-worktree index, object, log, and
  branch-ref writes without granting an arbitrary parent directory.
- The existing `plan.attempt_finished` event may include `duration_ms`, final
  aggregate `input_tokens`, `cached_input_tokens`, `output_tokens`,
  `reasoning_output_tokens`, and `launcher_prompt_bytes`. Missing or malformed
  usage is unavailable and does not affect completion.

## Completion, Failure, And Recovery

- `completed` (exit 0): every ordered plan has an accepted clean commit.
- `failed` (exit 1): invocation failure, runner-integrity failure, or exhausted
  plan attempts.
- `blocked` (exit 2): the current plan or pre-execution environment requires
  operator-owned resolution. A worktree-creation failure returns this operator
  status while preserving durable internal `failed` state for explicit resume
  handling.
- `checkpointed` (exit 3): durable state remains available for resume. This is
  a first-class recovery boundary, not a failure synonym.

Automatic recovery is conditional and evidence-driven:

| Observation | Action |
|---|---|
| unchanged parent-observed blocker fingerprint | stop with zero compiler, model, or verification child launches |
| changed capability fingerprint | permit a resume, subject to every plan budget |
| timeout with changed durable progress fingerprint | continue as `productive_timeout`, subject to every plan budget |
| first timeout with unchanged progress | permit one bounded confirmation slice as `first_no_progress_slice` |
| second consecutive timeout with unchanged progress | stop stalled as `second_no_progress_slice` |
| child returns `checkpointed` | persist the checkpoint; resume is allowed only within post-slice budgets |
| checkpoint, controller-launch, or wall-time budget exhausted | stop before another launch with a typed budget reason |
| child returns `blocked` or `failed` | preserve the typed terminal state; only explicit operator retry can reconsider a failed run |
| invalid result, wrong `HEAD`, broken ancestry, dirty handoff, or evidence drift | fail closed without product retry |

The capability fingerprint is derived from canonical parent probes. Incidental
probe details and a child hypothesis cannot manufacture a typed blocker. Once
an unavailable capability is parent-observed, resuming against the unchanged
fingerprint produces no compiler call, model turn, verification process, new
attempt, or controller-launch increment. A changed fingerprint removes that
specific stop, but does not bypass budgets or correctness gates.

The durable progress fingerprint covers `HEAD`, completed task IDs, current
task ID, accepted review IDs, and closed finding IDs. The fixed per-plan
defaults are:

| Budget | Default |
|---|---:|
| controller slice timeout | 3600 seconds |
| productive progress checkpoints | 6 |
| plan wall time | 21600 seconds |
| controller launches | 8 |

Every limit is checked before another controller launch. Changed durable
progress resets the consecutive no-progress counter. An unchanged first
timeout consumes only the single confirmation allowance; the second
consecutive unchanged timeout stops rather than spending another model slice.

### Local Result Envelope Repair

If an otherwise complete result failed only because the workflow receipt used
safe absolute spellings for `ledger_path` or `final_review_path`, CPE may repair
those spellings locally to verified worktree-relative paths. The repair:

- preserves the original result file and SHA-256 digest as immutable evidence;
- writes a distinct read-only repaired result under the private results tree;
- records exact before/after digests and the changed JSON pointer paths;
- changes no status, summary, commit, verification, finding, obligation, or
  other semantic result field;
- uses zero compiler calls, model turns, verification launches, controller
  launches, or attempts.

Verification receipt paths are validated but are not rewritten. A semantic
difference, unsafe path, symlink or inode swap, changed file mode, source
evidence drift, duplicate repair event, or unbound prior failure rejects repair
and fails closed. Crash reconciliation reuses the recorded repair without
launching a child.

The event-derived recovery metrics count avoided launches, local envelope
repairs, productive timeouts, no-progress slices, typed continuation reasons,
and budget stops. The optimization reports keep the corresponding trust-labelled
findings and evidence references, so each avoided launch, continuation, and
budget stop is explainable without adding mutable counters to `state.json`.

Recovery remains plan-level. CPE persists evidence and decides whether another
slice is justified; it does not interpret plan prose, redispatch completed
ledger tasks, judge product quality, merge, or push. Superpowers owns the
correctness of implementation, review, fixes, and final verification.

A `preparing` resume reuses a worktree only when repository, branch, path, and
source commit all match. An absent worktree may be recreated from the recorded
source. Ambiguous or mismatched evidence fails closed without deletion.

## Lean Superpowers Contract

CPE launches bounded controller slices for each approved plan. Superpowers owns
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
- A hard machine shutdown can leave a `preparing` run that requires normal
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
network-free, and model-free. Keep state-only recovery decisions in direct
boundary fixtures; process lifecycle and isolation claims must retain
real-process coverage. Record observed duration instead of treating one
development machine's timing as a portable pass/fail contract, and investigate
unexpected duration regressions against comparable host and fixture evidence.

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
and model-free. Its observed duration depends on the host and the number of
real-process lifecycle fixtures.

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
scripts/cpe_runtime/compiler.py
scripts/cpe_runtime/evidence.py
scripts/cpe_runtime/launcher.py
scripts/cpe_runtime/reporting.py
scripts/cpe_runtime/runner.py
scripts/cpe_runtime/state.py
templates/compiled-run-index.schema.json
templates/execution-ledger.schema.json
templates/optimization-report.schema.json
templates/plan-result-schema.json
```
