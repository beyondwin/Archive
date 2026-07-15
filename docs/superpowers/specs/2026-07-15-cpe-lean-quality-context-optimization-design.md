# CPE Lean Quality And Context Optimization Design

**Date:** 2026-07-15

**Status:** Approved in conversation; pending written-spec review

**Repository:** `/Users/kws/source/private/Archive`

**Primary surface:** `skills/kws-codex-plan-executor/`

## 1. Summary

CPE remains a small sequential wrapper around approved Superpowers plans. This
design reduces the context retained by each plan controller without rebuilding
the retired CPE mapper, task queue, reviewer, fixer, or final-integrator
architecture.

The quality policy is deliberately lean: every piece of evidence has one
owner. Implementers run focused task verification, task reviewers read that
evidence without repeating it, the final reviewer checks cross-task
integration, and the plan controller runs full verification at the final
revision. CPE validates the accepted commit and the existing workflow receipt;
it does not repeat product review or verification.

Fresh subagents and file-backed handoffs may use more total provider tokens
than one inline agent. That trade-off is accepted because the primary goal is
to keep the controller context clean enough for reliable decisions. The design
still optimizes total work by removing duplicate full-suite runs, duplicate
reviews, blind recovery attempts, and repeated loading of raw artifacts.

## 2. Current Evidence And Problems

The current runner already has the correct high-level boundary:

- one fresh, ephemeral Codex process per plan;
- one isolated worktree shared by ordered plans;
- immutable plan and specification snapshots;
- exact clean-HEAD acceptance;
- plan-level resume with bounded attempts;
- no CPE-owned product verification after an accepted Superpowers handoff.

The remaining inefficiencies are narrower.

### 2.1 Broad Context Is Available Without A Read Policy

Every plan session receives every specification snapshot path. The launcher
does not distinguish reference-only context from context that should be loaded
immediately. A capable plan controller may therefore read more approved input
than the current task requires.

### 2.2 Generic Superpowers Verification Is Too Broad For CPE

The current Subagent-Driven implementer template asks each task implementer to
run the full suite once before committing. For a plan with many tasks this can
repeat the same expensive suite at several intermediate revisions even though
the plan controller must still verify the final revision.

The existing task-reviewer contract is better scoped: reviewers consume the
implementer report and diff package, avoid rerunning reported tests, and run a
new focused test only for a concrete unresolved doubt. CPE should preserve
that behavior while overriding the generic per-task full-suite rule for CPE
runs.

### 2.3 Reviewer Detail Can Accumulate In The Controller

Implementers already write full reports to files and return a short status.
Task reviewers currently return the complete review as their final message.
Across a long plan, those reviews remain in the controller transcript even
after their findings have been resolved.

### 2.4 Recovery Can Repeat A Whole Plan Attempt

The current runner grants an initial attempt plus one automatic recovery
attempt. It passes prior result and log paths to a fresh process, but it does
not require a compact failure signature, an explicit changed strategy, or a
machine-readable statement that a failure is retryable. This can cause a
fresh controller to rediscover prior state or repeat the same failed approach.

### 2.5 Context And Cost Changes Are Not Measured

CPE does not retain Codex usage totals. It therefore cannot show whether a
prompt or handoff change reduced input, cached input, output, or reasoning
tokens. Current Codex output does not provide a stable, guaranteed split
between root-controller usage and nested-subagent usage, so the design must not
invent that attribution.

### 2.6 The Deterministic Gate Exceeds Its Budget

The complete deterministic gate passed functionally in two local measurements
but took 16.17 seconds and 15.18 seconds. Both exceed the documented
fifteen-second ceiling. The suite remains valuable, but its setup and process
fixtures need enough simplification to restore timing headroom before more
coverage is added.

## 3. Goals

1. Keep the plan controller focused on task order, decisions, open findings,
   and final integration.
2. Move task requirements, implementation reports, diffs, reviews, logs, and
   recovery evidence through files instead of transcript text.
3. Give implementation, task review, final review, and final verification one
   distinct owner each.
4. Prevent identical verification commands from running repeatedly at the same
   Git revision.
5. Prevent recovery from redispatching completed tasks or repeating a failed
   strategy without new evidence.
6. Record bounded per-attempt usage totals without retaining the raw Codex JSON
   event stream.
7. Preserve CPE's current state format, public CLI, process safety, worktree
   model, and twelve-file tracked inventory.
8. Restore the complete deterministic gate to less than fifteen seconds, with
   a target of twelve seconds or less on the development machine.

## 4. Non-Goals

This design does not:

- restore CPE-owned task mapping, specification slicing, dependency graphs, or
  quality roles;
- launch one CPE process per task;
- modify installed Superpowers skill files;
- add a database, telemetry service, metrics directory, or provider-cost
  estimator;
- estimate a root-versus-subagent token split that Codex does not report
  reliably;
- run implementation workers in parallel against the shared worktree;
- weaken exact-HEAD, clean-worktree, result isolation, process cleanup, locking,
  or state validation;
- merge, push, deploy, or delete external run evidence.

## 5. Alternatives

### 5.1 Lean Quality Bridge — Selected

Keep one fresh Codex process per plan and use the current Superpowers
Subagent-Driven workflow with a small CPE-specific execution contract. Reuse
task briefs, reports, review packages, and the durable progress ledger. Add
only lazy context guidance, compact review returns, conditional recovery,
filtered usage totals, and a workflow receipt.

This approach keeps the controller context small without making CPE a second
quality framework.

### 5.2 Prompt-Only Adjustment — Not Sufficient

Changing only the launcher prompt would be the smallest patch. It could request
lazy specification reads and prohibit duplicate full-suite runs, but CPE would
still have no structured recovery decision, workflow receipt, or usage signal.
The behavior would be difficult to evaluate and easy to regress.

### 5.3 Task-Per-Process CPE — Rejected

Launching a new CPE process per task maximizes context isolation, but repeats
repository discovery, instruction loading, plan bootstrap, and process setup.
It also recreates task orchestration already owned by Superpowers. The extra
state, prompts, retries, and handoffs conflict with the lean-runner boundary.

## 6. Ownership Model

| Owner | Sole responsibility | Explicit exclusion |
|---|---|---|
| CPE | snapshots, worktree, fresh plan process, bounded retry, resume, commit and receipt validation | implementation, task mapping, review, product tests |
| Plan controller | plan order, compact decisions, current-task state, cross-task completion | direct implementation, raw diff or log retention |
| Implementer subagent | one task, focused RED/GREEN, affected tests, commit, self-review | automatic full suite, final integration review |
| Task reviewer | task brief, report, and diff review | repeating implementer verification, broad merge review |
| Fix subagent | one consolidated set of task findings and affected tests | one process per finding, unrelated cleanup |
| Final reviewer | cross-task interfaces, regressions, omissions, and branch-level risks | replaying every task review |
| Plan controller at final HEAD | final full verification and result preparation | asking CPE to rerun the same command |

The ownership rule is evidence-based rather than role-count-based. More review
roles do not imply higher quality when they repeat the same inputs and checks.

## 7. Lean Execution Contract

The launcher prompt adds a short CPE-specific contract. It does not copy the
Superpowers templates into CPE and does not change installed skill files.

### 7.1 Plan Startup

The initial prompt contains only:

- the isolated worktree path;
- current plan ID and immutable plan path;
- starting and current commits;
- ordered specification snapshot paths marked as reference-only;
- an optional recovery-capsule path;
- the lean execution rules and strict result contract.

The plan is the operational execution brief. Specification snapshots remain
authoritative inputs but are not preloaded. The controller searches and reads
only a relevant section when the plan explicitly refers to it, a task is
ambiguous, or the plan and observed code conflict.

### 7.2 Task Implementation

For each incomplete task, the controller uses the existing Superpowers
`task-brief` helper. The implementer receives:

- one sentence explaining where the task fits;
- the task-brief path;
- only interface changes or decisions that the brief cannot know;
- the worktree path;
- the report-file path and compact return contract.

The implementer runs the plan-declared focused RED/GREEN commands and tests
affected by any later fix. It does not add an automatic full-suite run at task
completion. A task may run broader verification only when the approved plan
defines that verification as the task's deliverable.

The full implementation report remains in the report file. The returned
message stays within the existing fifteen-line implementer contract and
contains status, commits, one-line test evidence, concerns, and the report
path.

### 7.3 Task Review And Fixes

The controller uses the existing `review-package` helper so the diff never
enters controller context. The reviewer receives the task brief, implementer
report, review-package path, commit range, and binding global constraints.

For CPE runs, the reviewer writes its full report to a task-specific review
file and returns only:

- spec-compliance verdict;
- task-quality verdict;
- open finding IDs and severities;
- review-file path.

The reviewer does not rerun tests already evidenced by the implementer. It may
run one focused test only when a concrete doubt cannot be resolved from the
brief, report, and diff.

All Critical and Important findings from one review are handled by one fix
subagent. That subagent appends fix evidence to the task report and runs only
tests affected by its edits. Re-review checks the finding delta and updated
evidence; it does not replay the complete original task review. Minor findings
remain in the progress ledger for final triage.

### 7.4 Final Review And Verification

After every task is complete, the final reviewer reads one whole-branch review
package and checks only cross-task concerns: interface compatibility,
integration regressions, missed global constraints, and unresolved recorded
findings. It does not repeat task-scoped reviews.

The plan controller then runs the approved full verification at the final
worktree HEAD. A failed command may be rerun only after the revision changes or
an explicitly recorded transient infrastructure failure. The successful final
verification is bound to the exact commit reported to CPE.

### 7.5 Controller Context

The controller retains only:

- current task and progress-ledger location;
- task base and head commits;
- compact status and one-line test evidence;
- open finding IDs;
- decisions that differ from the approved plan;
- next action or blocker.

The controller does not retain full plans copied repeatedly, full
specifications, raw diffs, raw test output, full subagent work narratives,
prior logs, or cumulative summaries of completed tasks.

## 8. Verification Deduplication

The core invariant is:

> The same normalized command must not run more than once at the same Git HEAD
> in the CPE worktree.

The invariant applies across implementers, reviewers, fixers, final review,
and CPE. A command may run again when:

- code changed and the worktree HEAD is different;
- a recorded transient infrastructure failure made the first observation
  invalid;
- the command intentionally tests mutable external state and the approved plan
  requires the second observation.

Reviewers prefer existing evidence. CPE validates the final evidence but never
executes the command itself. A plan that lacks focused task commands or one
final verification command is not repaired by adding ad hoc broad tests at
runtime; the child reports a plan-contract blocker.

## 9. Compact Recovery

### 9.1 Recovery Capsule

Before a recovery launch, CPE writes a private regular JSON file under the
existing `results/` directory. It contains only:

```json
{
  "plan_id": "plan-01",
  "attempt": 1,
  "starting_commit": "0123456789012345678901234567890123456789",
  "current_head": "abcdefabcdefabcdefabcdefabcdefabcdefabcd",
  "completed_tasks": ["Task 1", "Task 2"],
  "current_task": "Task 3",
  "prior_status": "interrupted",
  "failure_signature": "verification:test_x_failed",
  "next_strategy": "resume Task 3 and inspect the parser boundary",
  "dirty_files": [],
  "prior_result_path": "/private/run/results/plan-01-attempt-1.json",
  "prior_log_path": "/private/run/logs/plan-01-attempt-1.log"
}
```

The capsule is CPE-owned, mode `0600`, and derived from current state, Git, the
prior result, and the Superpowers ledger. It is a recovery summary, not a task
graph or semantic plan parser.

### 9.2 Recovery Read Order

The fresh controller reads:

1. recovery capsule;
2. `.superpowers/sdd/progress.md`;
3. current Git log and status;
4. the current task brief and report;
5. targeted prior-result or prior-log sections only when the earlier evidence
   is insufficient.

Completed ledger tasks are never redispatched. Existing commits and reports
are reused. The recovery session changes strategy according to the capsule and
does not repeat the same failure signature without new evidence.

### 9.3 Retry Decision

Non-completed child results add three optional fields:

```json
{
  "retryable": true,
  "failure_signature": "verification:test_x_failed",
  "next_strategy": "inspect the parser boundary and resume Task 3"
}
```

Policy:

| Observation | Action |
|---|---|
| timeout or coordinator interruption | one fresh recovery attempt |
| child-reported retryable product failure | one fresh attempt with the changed strategy |
| blocked or operator-owned decision | stop without automatic retry |
| invalid result, wrong HEAD, broken ancestry, or dirty completed handoff | fail closed without product retry |
| repeated failure signature | stop without another automatic attempt |
| explicit `resume --retry-failed` | grant one operator-initiated attempt |

## 10. Filtered Usage Metrics

The launcher enables Codex JSON events only to extract the final
`turn.completed.usage` numbers. Raw JSON events are not copied into
`events.jsonl` or retained as a second transcript. Normal bounded stderr output
continues to use the existing attempt log.

The existing `plan.attempt_finished` event adds:

```json
{
  "duration_ms": 842000,
  "input_tokens": 42000,
  "cached_input_tokens": 31000,
  "output_tokens": 6200,
  "reasoning_output_tokens": 4100,
  "launcher_prompt_bytes": 912
}
```

Missing or malformed usage is recorded as unavailable and does not change a
product-quality verdict. The result must not interpret total usage as an exact
root-controller measurement. Context optimization is evaluated using both the
available session totals and structural invariants such as file handoffs,
bounded prompts, and absence of raw artifacts in controller messages.

## 11. Workflow Receipt

The strict child-result schema adds an optional `workflow_receipt` property.
New completed attempts launched under this contract must provide it; existing
accepted result files remain readable and are not rewritten.

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

For completed results CPE validates:

- `mode` is `subagent-driven-lean`;
- the progress ledger and final-review artifact resolve to regular,
  non-symlink files inside the worktree;
- task review and final review report complete and approved;
- `duplicate_verification` is `none`;
- the existing top-level `verification` array is non-empty and successful;
- the existing top-level result HEAD equals actual worktree HEAD.

CPE does not reread every review finding or rerun verification. Like the
existing verification array, the receipt is child-reported evidence bound to
the mechanically checked commit. Final verification is not copied into the
receipt; the existing top-level fields remain its single source of truth.

## 12. State And Compatibility

The authoritative state remains format version 1. No task records, context
packets, reviewer records, or metrics directory are added to state.

- usage totals are details on the existing attempt-finished event;
- recovery capsules live under the existing private results directory;
- the accepted result file contains the workflow receipt and remains sealed
  read-only after validation;
- existing completed plans and historical format-1 runs remain inspectable;
- an incomplete historical run resumed by the new launcher receives the new
  result contract on its next attempt.

The public CLI remains `run`, `resume`, and `inspect`. Default worktree,
locking, process-group, result-isolation, and log-bounding behavior does not
change.

## 13. Error Handling

- Missing plan-focused verification is a plan-contract blocker, not a reason
  to invent a package-wide command.
- Missing workflow receipt on a new completed attempt is an invalid completed
  handoff.
- Missing or unsafe receipt artifact paths reject completed status.
- Missing usage metrics are informational; malformed raw JSON cannot corrupt
  the accepted result.
- A reviewer concern that cannot be resolved from the task diff is recorded as
  a focused follow-up, not permission to crawl the repository.
- A final-review finding is fixed by one consolidated subagent, followed by
  affected tests, a delta review, and final verification at the new HEAD.
- An external authority requirement returns blocked without relaxing the
  approved plan or worktree boundary.

## 14. Deterministic Verification

The suite remains sequential, standard-library-only, network-free,
credential-free, and model-free. New focused fixtures prove:

1. the launcher prompt marks specs as lazy reference inputs and carries the
   lean execution and deduplication contract;
2. completed results without a valid workflow receipt are rejected;
3. receipt artifacts outside the worktree, symlinks, a duplicate-verification
   attestation other than `none`, and failed final review are rejected;
4. timeout and retryable failure produce one compact recovery capsule;
5. blocked, integrity failure, and repeated failure signatures do not launch a
   blind recovery attempt;
6. completed ledger tasks appear in the capsule and are declared non-dispatchable;
7. usage numbers are extracted while unrelated JSON events and raw content are
   discarded;
8. missing usage remains non-blocking;
9. completed handoffs that do not attest `duplicate_verification: none` are
   rejected without adding a second verification ledger.

Before adding those cases, existing fixtures are profiled and simplified:

- reuse repository and worktree setup where isolation semantics do not require
  a fresh fixture;
- replace fixed waits with ready files and bounded short polling;
- keep distinct POSIX process-group, signal, timeout, lock, and coordinator-loss
  cases rather than merging different failure boundaries;
- avoid invoking CLI help or full runner flows more than once for the same
  contract.

During implementation, run the smallest affected fixture after each change.
Run the complete gate once at the final revision:

```bash
cd skills/kws-codex-plan-executor
/usr/bin/time -p ./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
cd /Users/kws/source/private/Archive
git diff --check
```

The timed suite target is twelve seconds or less and the hard acceptance ceiling
is fifteen seconds on the development machine.

## 15. Implementation Boundaries

The implementation remains inside the current twelve tracked CPE files plus
the matching root design and plan documents. Expected runtime changes are
limited to:

- launcher prompt, filtered usage parsing, and process-stream separation;
- runner receipt validation, conditional retry, recovery-capsule creation, and
  attempt-event details;
- the strict result schema;
- focused deterministic fixtures;
- `SKILL.md` and `README.md` contract updates.

No new runtime module or tracked skill file is justified by this design. If
implementation makes one current module difficult to understand, a split
requires a separate design decision rather than silently expanding the tracked
inventory.

## 16. Rollout Order

1. Optimize existing deterministic fixture setup enough to restore timing
   headroom.
2. Add failing fixtures for the lean launcher contract and workflow receipt.
3. Implement prompt and receipt validation without changing retry behavior.
4. Add failing fixtures and implementation for recovery capsules and
   conditional retry.
5. Add filtered usage extraction and event fields.
6. Update skill documentation and run the complete final verification once.

Each stage preserves the existing public CLI and can be reviewed as a focused
contract change. Product review and verification remain owned by the launched
Superpowers session throughout the rollout.

## 17. Acceptance Criteria

The design is complete when:

1. CPE owns no implementation, mapper, reviewer, fixer, task queue, or final
   integrator role.
2. CPE plan sessions use file-backed task briefs, reports, diff packages,
   review reports, and the durable progress ledger.
3. Task implementers do not automatically run the full suite.
4. Reviewers do not repeat reported verification and re-review only changed
   findings after fixes.
5. Final review is cross-task only, and full verification is bound to the final
   HEAD.
6. The same command does not run twice at the same HEAD without an explicit
   transient exception.
7. Completed tasks are not redispatched during recovery.
8. Automatic recovery requires interruption or a structured retryable result,
   changes strategy, and stops on a repeated failure signature.
9. The controller receives compact statuses and artifact paths rather than raw
   plans, specifications, diffs, logs, or test output.
10. Completed results contain a valid workflow receipt, exact clean HEAD, and
    successful final verification evidence.
11. Attempt events record available usage totals without retaining raw Codex
    JSON events or claiming unsupported root/subagent attribution.
12. Existing state format, CLI, process safety, worktree safety, and twelve-file
    tracked inventory remain unchanged.
13. The complete deterministic suite passes below fifteen seconds, with a
    twelve-second target.

## 18. Residual Risks And Accepted Trade-offs

- The workflow receipt remains child-reported evidence. CPE mechanically binds
  it to files and the exact commit but does not independently recreate every
  review judgment.
- A plan with weak task boundaries or missing focused verification cannot be
  repaired cheaply at runtime; it must return a clear plan-contract blocker.
- Compact reviewer returns require a CPE-specific overlay on the generic
  Superpowers reviewer prompt. A future Superpowers update may require that
  overlay fixture to be adjusted.
- Filtered session totals reveal trend changes but may aggregate controller and
  subagent usage. Structural context rules remain the primary main-context
  guarantee.
- Removing per-task full-suite runs means an integration defect may be found
  later at final verification. Task-focused tests, task review, and the
  cross-task final review are accepted as the cheaper earlier gates.
- A fresh recovery controller still pays repository and plan bootstrap cost.
  The compact capsule and ledger are intended to prevent the much larger cost
  of rediscovering or redispatching completed work.

These trade-offs favor high-quality decisions with the least duplicated work,
not the largest number of agents, reviews, or verification commands.
