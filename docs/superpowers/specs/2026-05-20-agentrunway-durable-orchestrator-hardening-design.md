# Design: AgentRunway Durable Orchestrator Hardening

Date: 2026-05-20
Status: Draft for user review
Owner: KWS
Parent Design:
- `docs/superpowers/specs/2026-05-20-agentrunway-durable-integration-orchestrator-design.md`

## 1. Summary

The recent AgentRunway durable integration work added the right foundation:
workflow events, activities, checkpoints, decision packets, failure
classification, immediate selected-candidate merge, and checkpoint-aware
scheduler helpers. The next hardening pass should turn those pieces into one
coherent durable orchestrator.

The target is:

```text
durable state
  -> checkpoint-aware dispatch
  -> activity lifecycle runner
  -> gate classification and decision packet
  -> immediate merge checkpoint
  -> executable resume from the next missing boundary
  -> consistent inspect and summarize views
```

AgentRunway no longer treats "task completed" as the release condition
for dependent work. A dependent task becomes ready only after its dependency
has a successful run-main checkpoint. Resume does not merely describe the
next activity; it should safely execute automatic recovery boundaries while
still stopping at human-decision classes.

## 2. Current Baseline

The current baseline at commit `9756075` has these delivered pieces:

- `WorkflowStore` and SQLite tables for workflow events, activities,
  checkpoints, and decision packets.
- `IntegrationManager` for merging the selected candidate into run main and
  creating a checkpoint.
- `FailureClassifier` for plan, gate, and merge failure classes.
- `plan_activity_resume()` for identifying the next durable activity boundary.
- `ready_tasks_after_checkpoints()` and `schedule_safe_wave()` helper coverage.
- `summarize` fields for latest checkpoint, activity graph counts, blocked
  node, failure class, next action, and human decision.

The remaining gaps are structural and behavioral:

- `runner.py` still owns the end-to-end activity flow, gate handling, merge
  integration, and status projection.
- the runner still computes static `schedule_waves(tasks)` up front instead of
  running from the checkpoint-aware scheduler helpers;
- `resume --dry-run` reports the next activity boundary, but non-dry-run resume
  only applies reconciliation and does not execute automatic boundaries;
- `inspect`, `summarize`, and `resume` derive overlapping state through
  separate paths, which can drift as the durable model grows.

## 3. Goals

- Make resume executable for automatic durable boundaries without rerunning
  completed activities.
- Integrate checkpoint-aware ready selection and safe-wave conflict detection
  into the runner dispatch loop.
- Keep all dependency release decisions based on checkpoint rows, not task
  status alone.
- Split the runner's durable behavior into small components with clear
  contracts.
- Make `inspect`, `summarize`, and `resume --dry-run` agree on latest
  checkpoint, blocked node, ready queue, and next action.
- Preserve AgentRunway's existing local-first model: SQLite state, local
  worktrees, artifacts, event journal, and AgentLens emission.

## 4. Non-Goals

- Do not rewrite AgentRunway into a remote workflow service.
- Do not replace the existing adapter contract for Codex, Claude, or local
  fake fixtures.
- Do not change source-checkout safety semantics or automatically apply run
  output to the source checkout.
- Do not add a UI surface in this slice.
- Do not remove existing event or task status fields until durable projections
  have proven stable.

## 5. Architecture

### 5.1 CheckpointScheduler

`CheckpointScheduler` owns runtime dispatch selection. It reads task specs,
task status, checkpoints, and file/resource claims, then returns the next safe
wave.

The scheduler replaces static `schedule_waves(tasks)` during execution.
The old helper can remain for planning-only display, but runtime scheduling
must recalculate after every checkpoint.

The scheduler contract:

```python
class CheckpointScheduler:
    def next_wave(self, *, projection: DurableProjection) -> list[TaskSpec]:
        ...
```

Rules:

- derive completed dependency ids from checkpoint rows whose reason is
  `merged:<task_id>`;
- exclude tasks already marked terminal, merged, or blocked;
- require every declared dependency to have a checkpoint;
- pass ready tasks through `schedule_safe_wave()`;
- serialize high-risk, serial, broad-claim, overlapping file-claim, and shared
  resource-key work;
- return an empty list only when no safe automatic progress is available.

### 5.2 ActivityRunner

`ActivityRunner` owns durable activity lifecycle execution. It starts and
completes activities for implement, review, verification, and merge work. The
runner should call this component instead of directly mixing workflow-store
calls with adapter and gate code.

The activity contract:

```text
start_activity
  -> execute adapter/gate/merge operation
  -> complete_activity(completed|failed|blocked)
  -> emit workflow event and event journal record
```

Every completed activity must include enough output refs to resume the next
boundary without rerunning it:

- implement: worker id, candidate id, worker result artifact;
- review: candidate id, review status, review mode, review artifact;
- verification: candidate id, verification status, verification artifact;
- merge: checkpoint id, post-merge commit SHA, selected candidate id.

### 5.3 GateRunner

`GateRunner` owns review and verification interpretation. It combines
`FailureClassifier`, `quality_policy`, retry budgets, and decision packet
creation.

The gate runner returns one normalized result:

```text
continue
retry_implementer
redispatch_from_latest_checkpoint
await_human_decision
terminal_block
```

The caller should not duplicate failure-class branching. Human-decision classes
always produce decision packets.

### 5.4 ResumePlanner And ResumeExecutor

`ResumePlanner` extends `plan_activity_resume()` into a stable action plan.
`ResumeExecutor` applies only automatic actions from that plan.

Dry-run resume returns:

- reconciliation actions;
- last durable activity;
- next node;
- next automatic action;
- whether completed activity output will be reused;
- human decision packet, if any;
- commands or internal actions that non-dry-run resume would execute.

Non-dry-run resume:

- applies reconciliation first;
- re-reads durable state after reconciliation;
- executes only automatic actions;
- never reruns a completed activity;
- stops at `await_human_decision` and returns the decision packet.

The initial executable actions are:

- schedule review after completed implement;
- schedule verification after approved review;
- schedule merge after passed verification;
- verify or reconstruct checkpoint after completed merge;
- schedule implementer retry when policy and failure class allow it;
- redispatch from latest checkpoint for retryable rebase cases.

### 5.5 DurableStateReader

`DurableStateReader` provides one projection used by `inspect`, `summarize`,
and `resume --dry-run`.

The projection includes:

- latest checkpoint and checkpoint lineage;
- completed dependency checkpoint ids by task;
- ready queue and blocked queue;
- running or stale activities;
- blocked activity and decision packet;
- next automatic action;
- next human action;
- summary counts for activities, checkpoints, candidates, and decisions.

This reader prevents three command surfaces from inventing separate meanings
for the same run state.

## 6. Runtime Flow

### 6.1 Run Startup

1. Parse and lint the plan.
2. Persist run metadata, task specs, packets, and frozen contract.
3. Create run-main worktree.
4. Create `cp-000` from run-main HEAD.
5. Enter checkpoint dispatch loop.

### 6.2 Checkpoint Dispatch Loop

The dispatch loop repeatedly asks `CheckpointScheduler` for the next safe wave.
After every wave completes, it re-reads durable state from SQLite.

```text
while run can make progress:
  projection = DurableStateReader.read(run_id)
  wave = CheckpointScheduler.next_wave(projection)
  if wave is empty:
    stop as finished or blocked according to projection
  execute safe wave
  re-read checkpoints
```

A task is considered dependency-complete only when every dependency appears in
the completed checkpoint set. A task status of `merged` without a checkpoint is
not enough to release dependent work; that state should trigger checkpoint
verification or repair.

### 6.3 Task Execution

Each task still follows the existing quality path:

```text
implement candidate(s)
  -> review
  -> verification
  -> candidate ranking
  -> merge selected candidate
  -> checkpoint
```

The difference is that every step runs through `ActivityRunner`, and dependent
work does not dispatch until merge checkpoint creation succeeds.

### 6.4 Resume Flow

Resume is a state-machine continuation, not a second implementation path.

```text
load run
  -> plan reconciliation
  -> apply reconciliation if non-dry-run
  -> read durable projection
  -> plan next resume action
  -> execute automatic action if safe
  -> return updated projection
```

If a prior activity is completed, resume uses its output refs. If an activity
is started but has no valid output, reconciliation decides whether to recover
the artifact, retry from the latest checkpoint, or block.

## 7. Failure Policy

| Failure class | Default handling | Human decision |
|---|---|---|
| `needs_implementer_retry` | retry implementer within budget | no |
| `needs_rebase` | redispatch from latest checkpoint once | no unless repeated |
| `needs_full_context` | escalate review mode once | no unless exhausted |
| `needs_plan_fix` | block with decision packet | yes |
| `needs_split` | block with decision packet | yes |
| `needs_infra_fix` | block with decision packet | yes |
| `needs_human_decision` | block with decision packet | yes |
| `terminal_rejected` | block with decision packet | yes |

Merge conflict handling remains conservative:

1. first conflict: redispatch from latest checkpoint;
2. repeated conflict: create decision packet and block;
3. interrupted cherry-pick: abort or reconcile before any new dispatch.

Started activities are classified by observable evidence:

- valid result artifact exists: reconcile forward and complete the activity;
- process still alive: keep activity running;
- process dead and no valid result: retry if policy allows, otherwise block;
- merge completed but checkpoint missing: verify run-main HEAD and reconstruct
  the checkpoint if the selected candidate commit is present.

## 8. Data Model

The first hardening pass reuses the existing tables:

- `workflow_events`
- `activities`
- `checkpoints`
- `decision_packets`
- `tasks`
- `workers`
- `merge_queue`

Avoid new schema unless implementation proves an actual missing fact. The
expected additions are query helpers and projection objects, not new persistence
concepts.

Implement two naming cleanups during implementation:

- rename helper-local `completed_checkpoints` concepts to
  `completed_checkpoint_tasks` when the values are task ids;
- keep checkpoint ids (`cp-001`) distinct from task ids (`task_001`) in
  payload keys.

## 9. Testing Strategy

### 9.1 Focused Tests

Add or extend tests for:

- runner dispatch waits for dependency checkpoints, not task status alone;
- independent low-risk tasks can share a safe wave;
- overlapping file claims and resource keys serialize;
- completed implement resumes by scheduling review only;
- approved review resumes by scheduling verification only;
- passed verification resumes by scheduling merge only;
- completed merge with missing checkpoint repairs or reports the checkpoint
  boundary;
- human-decision failure classes stop with decision packets;
- stale started activity reconciles valid result artifacts forward;
- `inspect`, `summarize`, and `resume --dry-run` report the same next action.

### 9.2 End-To-End Regressions

Keep the existing dependent-task regression and add:

- a three-task graph where task 3 waits for checkpoints from task 1 and task 2;
- a safe parallel wave with disjoint file claims;
- a conflict wave where two otherwise-ready tasks are serialized;
- a resume-after-crash fixture for each automatic boundary.

### 9.3 Final Verification

Before landing implementation:

```bash
cd skills/agent-runway && ./evals/run.sh
python -m py_compile scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py
git diff --check
graphify update .
```

`graphify update .` is required after code changes so the project graph stays
current.

## 10. Implementation Slices

### Slice 1: Durable Projection And Resume Plan

Create `DurableStateReader` and extend resume dry-run output to use the shared
projection. This gives `inspect`, `summarize`, and `resume` one vocabulary
before behavior changes.

Acceptance:

- no command surface reports a conflicting next action for the same run;
- blocked decision packets are visible through all three surfaces;
- existing evals still pass.

### Slice 2: Executable Automatic Resume

Add `ResumeExecutor` for automatic boundaries. Keep human-decision classes
blocked.

Acceptance:

- resume after completed implement schedules review without rerunning
  implement;
- resume after approved review schedules verification;
- resume after passed verification schedules merge;
- resume after completed merge verifies or reconstructs checkpoint state;
- dry-run remains side-effect free.

### Slice 3: Checkpoint Scheduler Runner Integration

Replace runtime use of static `schedule_waves(tasks)` with
`CheckpointScheduler`. Recompute ready waves after every checkpoint.

Acceptance:

- dependent tasks dispatch only after dependency checkpoint rows exist;
- safe disjoint work can run in the same wave;
- risky or conflicting work is serialized;
- run status is `blocked` only when no automatic progress remains and at least
  one blocking state exists.

### Slice 4: ActivityRunner And GateRunner Extraction

Move implement/review/verification/merge lifecycle code out of `runner.py`.
This is a behavior-preserving extraction after the durable semantics are
covered by tests.

Acceptance:

- `runner.py` remains the CLI orchestration shell;
- activity lifecycle behavior is covered in focused unit tests;
- gate decision packet creation is not duplicated across review and
  verification code paths.

## 11. Open Risks

Risk: executable resume can accidentally rerun expensive or mutating work.

Mitigation: resume only executes from explicit missing boundaries and requires
idempotency keys plus completed-activity output refs before reusing state.

Risk: checkpoint-based dispatch can reduce parallelism.

Mitigation: start conservative; allow safe waves only when file claims,
resource keys, risk, and serial flags prove compatibility.

Risk: extraction can hide behavior regressions in a large runner change.

Mitigation: land semantic changes behind focused tests first, then extract
ActivityRunner and GateRunner as behavior-preserving slices.

Risk: status projections drift.

Mitigation: force `inspect`, `summarize`, and `resume --dry-run` through
`DurableStateReader`.

## 12. Acceptance Criteria

The hardening effort is complete when:

- AgentRunway releases dependent work from checkpoint evidence only.
- Runner-integrated safe waves support disjoint ready tasks while serializing
  risky or conflicting tasks.
- Resume can execute automatic durable boundaries without rerunning completed
  activities.
- Human-decision failures consistently produce decision packets and stop.
- `inspect`, `summarize`, and `resume --dry-run` agree on next action and
  blocked state.
- `runner.py` no longer owns detailed activity lifecycle and gate policy
  mechanics directly.
- Full AgentRunway evals, py_compile, diff check, and graphify update pass
  after implementation.

## 13. Implementation Note

This design is implemented by
`docs/superpowers/plans/2026-05-21-agentrunway-durable-orchestrator-hardening.md`.
The implementation plan preserves the design goals while extracting activity
and gate boundaries before executable resume, so fresh runs and resume use the
same durable execution path.

Resume execution includes handler-gated automatic actions. Handler-less write
actions block instead of being recorded as executed. Verified merge boundaries
can be resumed into run main, and completed merge activities can reconstruct
missing checkpoint rows from durable output refs.
