# Design: AgentRunway Durable Integration Orchestrator

Date: 2026-05-20
Status: Draft for user review
Owner: KWS
Parent Designs:
- `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
- `docs/superpowers/specs/2026-05-20-agent-runway-production-supervisor-design.md`
- `docs/superpowers/specs/2026-05-20-agentrunway-operations-quality-engine-design.md`
- `docs/superpowers/specs/2026-05-20-agentrunway-quality-first-hybrid-worktree-design.md`

## 1. Summary

AgentRunway should evolve from a strict worker runner into a durable
integration orchestrator.

The current runner already provides useful product qualities: isolated
worktrees, frozen contracts, file-claim validation, reviewer and verifier
gates, SQLite state, local artifacts, and bounded summaries. The practical
quality gap is orchestration. A task can pass its own gates but still fail to
compose with earlier accepted work because the runner waits too long to
advance run main and retries failures with too little recovery strategy.

The target design is:

```text
plan contract
  -> durable task graph
  -> implement activity
  -> review activity
  -> verify activity
  -> select candidate
  -> merge selected candidate into run main immediately
  -> checkpoint
  -> schedule dependent tasks from the latest checkpoint
```

Every step writes durable evidence before the next step begins. Resume uses the
last completed artifact boundary instead of rerunning successful work.

The central rule:

```text
Run main advances only through selected, reviewed, verified candidates.
Dependent tasks always start from the latest successful run-main checkpoint.
```

## 2. Context

The 2026-05-20 AgentRunway hybrid worktree run showed the core failure mode.
Task 1 eventually passed review and verification, but later tasks were still
implemented against a base that did not include all accepted preceding work.
Reviewers then found integration problems such as CLI command tuple conflicts.
AgentRunway correctly blocked unsafe progress, but it did not recover with the
same judgement a human Codex or Claude orchestrator would apply.

Compared with the legacy KWS executors:

- KWS Codex has strong integration judgement because the main Codex session
  continuously sees the diff, tests, review feedback, and codebase state.
- KWS Claude has strong autonomous multi-agent execution because Opus owns
  orchestration and Sonnet agents perform bounded sub-work.
- AgentRunway has stronger replayability and gates, but its orchestration
  logic must become more adaptive before it can match their final-code quality.

This design keeps the AgentRunway product advantages and adds the missing
integration judgement as explicit runner behavior rather than hidden chat
context.

## 3. External Harness Patterns

This design borrows durable orchestration patterns from existing systems. It
does not copy their implementations.

- Temporal durable execution: model workflows as replayable state machines
  whose completed activities are not repeated after a crash.
- LangGraph durable execution and interrupts: persist step state and surface
  human decision points as resumable checkpoints instead of vague failures.
- Argo Workflows DAG and retry policy: schedule only dependency-ready nodes and
  make retry behavior task and failure-class specific.
- Bazel sandboxing: treat undeclared inputs and outputs as quality risks, not
  harmless shortcuts.

AgentRunway should apply these patterns to coding-agent work:

- model calls, git merges, review, verification, and summaries are activities;
- activity artifacts are the source of truth for resume;
- retry means "choose a recovery strategy", not "run the same prompt again";
- file claims and context claims define what a worker may rely on.

Reference links:

- https://docs.temporal.io/
- https://docs.langchain.com/oss/python/langgraph/durable-execution
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://argo-workflows.readthedocs.io/en/latest/walk-through/retrying-failed-or-errored-steps/
- https://bazel.build/versions/7.5.0/docs/sandboxing

## 4. Goals

- Improve final-code quality over the current AgentRunway runner.
- Preserve AgentRunway's deterministic contracts, artifacts, state, and gates.
- Merge verified selected candidates into run main as soon as each task passes.
- Ensure dependent tasks start from the latest run-main checkpoint.
- Allow parallelism only when dependency, file claim, resource, and risk policy
  prove it is safe.
- Make resume precise at every durable activity boundary.
- Replace generic gate retries with failure-class-specific recovery.
- Produce operator summaries that explain the current checkpoint, blocked node,
  failure class, next automatic action, and required human decision.
- Keep the source checkout unchanged until explicit `agentrunway apply`.

## 5. Non-Goals

- No rewrite into a remote workflow service.
- No automatic editing of merge conflicts in the user's source checkout.
- No removal of reviewer or verifier gates.
- No direct merge between worker worktrees.
- No dependence on hidden conversation state for correctness.
- No web dashboard in this slice.
- No compatibility bridge that makes KWS Codex or KWS Claude state authoritative
  for AgentRunway.

## 6. Core Architecture

AgentRunway v2 should execute a durable artifact graph, not a linear list of
workers.

The graph node types are:

```text
TaskReady
ImplementActivity
ReviewActivity
VerifyActivity
CandidateSelected
RunMainMerged
CheckpointCreated
TaskBlocked
HumanDecisionRequired
```

The happy path for each task is:

```text
TaskReady
  -> ImplementActivity
  -> ReviewActivity
  -> VerifyActivity
  -> CandidateSelected
  -> RunMainMerged
  -> CheckpointCreated
```

The scheduler may release dependent tasks only after `CheckpointCreated` for
every declared dependency.

Run main is the single integration branch for the run. Implementer, reviewer,
and verifier worktrees never merge into each other. A candidate commit is
trusted only after:

- worker result schema validation passes;
- changed files match file claims;
- reviewer approves or a policy-approved review path is satisfied;
- verifier passes acceptance commands or approved substitutes;
- candidate selection chooses it when multiple candidates exist.

Once selected and verified, the candidate is merged into run main immediately.
This differs from the current delayed integration model and is the main quality
fix.

## 7. Components

### 7.1 WorkflowStore

`WorkflowStore` is the single durable state boundary. It owns SQLite records,
event append, artifact references, and activity idempotency keys.

Required records:

- run metadata and current run-main checkpoint;
- task graph nodes and edges;
- activity attempts and terminal activity artifacts;
- selected candidate decisions;
- run-main merge attempts;
- checkpoint records;
- blocked node and human decision packets.

Events should be append-only. Derived views such as status, inspect, resume,
and summarize may be rebuilt from the event log plus artifact files.

### 7.2 TaskScheduler

`TaskScheduler` decides what can run next.

Inputs:

- task dependencies;
- file claims;
- resource keys;
- risk level;
- run-main checkpoint;
- active worker set;
- prior failure classifications.

Rules:

- A task is ready only when all dependencies have successful checkpoints.
- Tasks with overlapping owned claims are serialized unless dependency order
  already serializes them.
- Broad globs, high-risk tasks, migrations, generated files, and schema changes
  default to conservative scheduling.
- Independent tasks may run in parallel only when their write and resource
  surfaces are disjoint.
- If run main advances while a task is queued but not started, the task starts
  from the new checkpoint.

### 7.3 ActivityRunner

`ActivityRunner` executes idempotent activities:

- implement;
- review;
- verify;
- merge to run main;
- checkpoint;
- summarize.

Each activity has:

- deterministic idempotency key;
- input artifact references;
- output artifact references;
- terminal status;
- retry policy;
- failure classification.

If a process dies after an activity completes but before the runner schedules
the next node, resume must reuse the completed artifact instead of rerunning the
activity.

### 7.4 IntegrationManager

`IntegrationManager` owns run-main mutation.

Responsibilities:

- cherry-pick selected candidate commits into run main;
- detect interrupted cherry-pick state;
- record merge attempts and conflicts;
- create checkpoint records after successful merge;
- advance the run-main checkpoint pointer;
- notify the scheduler that dependent tasks can become ready.

Merge is an activity. It is not a side effect hidden inside task completion.

### 7.5 FailureClassifier

`FailureClassifier` converts raw gate and merge failures into recovery classes.

Initial classes:

```text
needs_rebase
needs_full_context
needs_plan_fix
needs_split
needs_implementer_retry
needs_infra_fix
needs_human_decision
terminal_rejected
```

Examples:

- Review says the candidate missed earlier accepted work:
  `needs_rebase`.
- Review says diff mode lacks enough context:
  `needs_full_context`.
- Verifier command fails due code in claimed files:
  `needs_implementer_retry`.
- Verifier cannot run due adapter, sandbox, or environment setup:
  `needs_infra_fix`.
- File claims, spec refs, or acceptance commands are wrong:
  `needs_plan_fix`.
- Task is too large or repeatedly produces partial fixes:
  `needs_split`.
- Merge conflict on latest run main:
  `needs_rebase`; repeated conflict becomes `needs_human_decision`.

### 7.6 OperatorSummary

`OperatorSummary` produces bounded operational summaries.

It should answer:

- What is the latest run-main checkpoint?
- Which task graph nodes are complete, running, blocked, or ready?
- Which candidate was selected and why?
- Which activity failed?
- What is the failure class?
- What will AgentRunway do automatically next?
- What exact human decision is needed, if any?
- Which artifact files contain the evidence?

Normal host operation should start with `summarize`, not raw logs.

## 8. Data Flow

### 8.1 Run Start

1. Resolve plan and spec.
2. Run `lint-plan`.
3. Freeze contract with hashes, parsed tasks, file claims, spec refs, and
   acceptance commands.
4. Create run main from the base commit.
5. Create initial checkpoint for run main.
6. Build durable task graph.
7. Schedule ready tasks.

### 8.2 Task Execution

For each ready task:

1. Read the current run-main checkpoint.
2. Create implementer candidate worktree from that checkpoint.
3. Run implement activity and collect `worker_result.json`.
4. Validate schema, method audit, commits, and changed files.
5. Run review activity.
6. If review requests more context, classify and escalate before retrying
   implementation.
7. Run verifier activity from the candidate head.
8. Select candidate.
9. Merge selected candidate into run main.
10. Create a new checkpoint.
11. Release dependent tasks.

### 8.3 Resume

Resume does not ask "which worker should I run again?" first. It asks:

```text
What is the latest durable activity boundary?
```

Examples:

- If implement completed and review did not start, schedule review.
- If review approved and verification did not start, schedule verification.
- If verification passed and merge did not start, schedule merge.
- If merge succeeded but checkpoint did not write, reconstruct or create the
  checkpoint after verifying run main.
- If checkpoint exists, release dependents.

## 9. Recovery Policy

Retries must be strategy-driven.

### 9.1 Rebase Recovery

Use when a candidate was based on an old checkpoint or conflicts with accepted
work.

Action:

- start a fresh implementer attempt from latest run-main checkpoint;
- include structured prior feedback and selected accepted changes;
- keep previous candidate as evidence;
- do not count this as a generic review retry if the root cause was stale base.

### 9.2 Full-Context Recovery

Use when a reviewer or verifier cannot make a safe judgement from bounded diff
context.

Action:

- escalate review or verification to full-tree context once;
- record why diff mode was insufficient;
- if full-tree still lacks enough context, block with `needs_human_decision`.

### 9.3 Implementer Retry

Use when review or verification identifies concrete fixable issues inside the
task scope.

Action:

- start a new implementer attempt from the latest checkpoint;
- include structured findings, failing commands, artifacts, and changed files;
- preserve retry budget by failure class, not just by role.

### 9.4 Plan Fix

Use when the plan is wrong.

Examples:

- missing or incorrect file claims;
- unresolved spec refs;
- acceptance command impossible to run;
- dependency graph missing a true dependency.

Action:

- block before more model calls;
- produce a decision packet with proposed plan edits;
- require user or planning workflow approval.

### 9.5 Split Recovery

Use when a task is too broad for reliable execution.

Action:

- block with `needs_split`;
- generate a proposed split into smaller task packets;
- do not silently execute the generated split until approved by a plan update.

### 9.6 Infra Fix

Use when failure is caused by adapter, sandbox, git, environment, or artifact
write issues.

Action:

- block as infrastructure;
- do not spend implementer retry budget;
- surface exact preflight or command evidence.

## 10. State and Artifact Model

The existing SQLite and artifact layout should be extended rather than
replaced.

New or extended concepts:

- `workflow_events`: append-only event stream.
- `activities`: activity attempts with idempotency key, input refs, output refs,
  status, and failure class.
- `checkpoints`: run-main commit SHA, parent checkpoint, merged candidate id,
  and created_at.
- `task_graph_nodes`: task node state derived from dependencies and checkpoints.
- `decision_packets`: human-readable and machine-readable blocked-state
  packets.

Artifacts remain file-based:

```text
runs/<workspace>/<run_id>/
  contract.json
  state.sqlite
  events.jsonl
  workflow_events.jsonl
  checkpoints/<checkpoint_id>.json
  activities/<activity_id>/
  decisions/<decision_id>.json
  artifacts/<task_id>/<worker_id>/
```

SQLite is authoritative for queries. JSON artifacts are authoritative evidence
for audit and recovery.

## 11. Visibility

`summarize` should become the normal operator interface.

Required fields:

```json
{
  "run_id": "example",
  "status": "blocked",
  "latest_checkpoint": {"id": "cp-003", "commit": "abc123"},
  "graph": {"complete": 3, "ready": 1, "running": 0, "blocked": 1},
  "blocked_node": "task_004.review",
  "failure_class": "needs_plan_fix",
  "next_automatic_action": null,
  "required_human_decision": "approve plan claim update",
  "selected_candidates": [],
  "artifact_refs": {}
}
```

`inspect` remains available for deep diagnosis. It should point to exact
activity, checkpoint, candidate, and decision artifacts.

## 12. Testing Strategy

The test suite must prove orchestration, not only helper functions.

Required coverage:

- scheduler serializes overlapping file claims and high-risk broad claims;
- scheduler runs independent disjoint tasks in parallel where safe;
- dependent task starts from checkpoint created by its dependency;
- selected candidate merges into run main immediately after verification;
- resume after implement completion schedules review only;
- resume after review approval schedules verification only;
- resume after verification success schedules merge only;
- resume after merge success creates or verifies checkpoint;
- failure classifier maps review, verification, merge, plan, and infra failures
  to the correct recovery class;
- stale-base candidate triggers `needs_rebase` and fresh implementer attempt
  from latest checkpoint;
- diff reviewer `needs_context` triggers one full-context escalation;
- verifier environment failure blocks as `needs_infra_fix` without consuming
  implementer retry budget;
- repeated merge conflict produces a decision packet;
- `summarize` reports checkpoint, blocked node, failure class, next automatic
  action, human decision, and artifact refs;
- self-hosting fake-adapter regression reproduces the previous task_001 to
  task_003 integration pattern and proves the conflict is avoided.

## 13. Implementation Slices

This design should be implemented in slices.

1. Add workflow event and checkpoint data model.
2. Make selected verified candidates merge into run main immediately.
3. Change scheduler to release dependents only after checkpoints.
4. Add idempotent activity records and resume from activity boundaries.
5. Add failure classifier and recovery classes.
6. Route review, verification, merge, and plan failures through classifier.
7. Upgrade `summarize` and `inspect` around checkpoints and failure classes.
8. Add fake-adapter integration tests for dependent-task integration quality.

The first implementation plan should not attempt a full rewrite. It should keep
existing modules working and move one boundary at a time behind tests.

## 14. Risks and Mitigations

Risk: immediate run-main merge can make rollback harder.

Mitigation: run main is still isolated from source checkout, every merge is a
cherry-pick activity, and checkpoints preserve the pre- and post-merge SHAs.

Risk: activity/event model adds complexity.

Mitigation: introduce it incrementally and keep old status fields as derived
views during migration.

Risk: over-conservative scheduling reduces speed.

Mitigation: start conservative for correctness, then enable parallel waves only
when file claims and dependencies prove safety.

Risk: failure classifier can misclassify early.

Mitigation: keep classifier decisions explicit in summaries and decision
events, with tests for every known failure class.

Risk: plan-fix and split recovery may interrupt automation.

Mitigation: this is intentional. AgentRunway should stop before spending model
calls on an invalid plan or too-broad task.

## 15. Acceptance Criteria

- AgentRunway can run a dependent multi-task plan where task 2 reads task 1's
  accepted change from run main.
- A verified selected candidate is merged into run main before dependent tasks
  start.
- Resume restarts from the last durable activity boundary without rerunning
  completed worker calls.
- Gate and merge failures produce failure classes and strategy-specific next
  actions.
- `summarize` reports checkpoints, blocked graph node, failure class, and
  artifact references without requiring raw log inspection.
- The previous AgentRunway failure pattern involving sequential CLI changes is
  covered by a fake-adapter integration regression.
