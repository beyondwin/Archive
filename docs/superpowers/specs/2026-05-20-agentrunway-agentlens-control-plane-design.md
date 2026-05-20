# Design: AgentRunway AgentLens Control Plane

Date: 2026-05-20
Status: Implemented
Owner: KWS

## 1. Summary

AgentRunway is now the only supported execution path for new plan execution
workflows. This design hardens AgentRunway as the operational control plane and
aligns AgentLens around AgentRunway-only observability.

The key boundary is intentional:

- AgentRunway remains the source of truth for execution state, resume, review,
  verification, merge, apply, and cleanup.
- AgentLens records, projects, and evaluates AgentRunway evidence.
- AgentLens and AgentRunway do not add, preserve, or extend CPE/CME integration
  paths.
- The CPE and CME skill directories may remain in the repository, but they are
  independent legacy workflows and are not connected to AgentRunway or AgentLens
  in this design.

Event names use the existing lower-case AgentRunway namespace:

```text
agentrunway.*
```

This design does not introduce `kws.orchestrator.*`, `kws-cpe.*`, or
`kws-cme.*` as supported AgentLens/AgentRunway surfaces.

## 1.5 Code Audit Findings (2026-05-20)

A read of `skills/agent-runway/scripts/agentrunway/*.py` and
`AgentLens/src/agentlens/**/*.py` against this design surfaced the following
gaps. They are recorded here so the implementation plan and downstream tasks
can address them explicitly.

### 1.5.1 Event coverage gap

`skills/agent-runway/scripts/agentrunway/runner.py` emits
`agentrunway.run_started`, `agentrunway.contract_created`,
`agentrunway.review_dispatched`, `agentrunway.review_result`,
`agentrunway.verification_dispatched`, `agentrunway.verification_result`,
`agentrunway.gate_retry`, `agentrunway.merge_ready`, and
`agentrunway.run_finished`. Section 5.1 of this design also lists
`agentrunway.worker_dispatched`, `agentrunway.worker_result`,
`agentrunway.merge_conflict`, and `agentrunway.run_blocked` as core events,
but the runner does not emit them. The implementation plan must either emit
those events (preferred) or narrow §5.1 to the events the runner actually
produces.

The merge-loop path that already detects `MergeConflictError` and the path
that calls `db.set_task_status(task.task_id, "blocked")` after exhausted
retries are the natural emit sites for `agentrunway.merge_conflict` and
`agentrunway.run_blocked`. `agentrunway.worker_dispatched` and
`agentrunway.worker_result` should bracket each `run_implementer_attempt`
call so AgentLens can observe attempt-level evidence, not only gate-level
evidence.

### 1.5.2 Outcome semantics

`build_event_payload()` in `events.py` derives `severity` from `outcome` and
defaults `outcome="success"` for every routine emit, including gate
dispatches and gate results. The actual pass/fail of a gate is carried in
the event-specific `status` field (`approved`, `changes_requested`,
`passed`, `failed`). AgentLens projections that branch on `outcome` will
therefore see every event as `success` even when the underlying gate
failed.

The design adopts the following convention so projections can be written
without re-interpreting per-event fields:

- `outcome="success"` only when the event represents a successful outcome
  of the action it names (e.g. `verification_result` with `status="passed"`,
  `merge_ready`, `run_finished` for a non-blocked run).
- `outcome="partial"` for retries, blocked review/verification, and merge
  conflicts.
- `outcome="failed"` for terminal failures, e.g. `run_blocked` and
  `run_finished` for a run that ended with any blocked tasks.
- Dispatch events (`*_dispatched`) keep `outcome="success"` because the
  dispatch itself succeeded; the gate's verdict is reported on the matching
  `*_result` event.

### 1.5.3 AgentLens emit health is split across two stores

`db.agentlens_summary()` only reads `agentlens_events`. The
`runs.agentlens_status` column (set by `set_run_agentlens` in the plan) is
not surfaced. A run with `agentlens_status="disabled"` and a run with
`agentlens_status="active"` whose emits all succeeded are indistinguishable
from a single-row event view. Plan Task 5 and Task 6 must extend
`agentlens_summary()` to also return `run_status` from the `runs` table so
`status`/`inspect` can answer "is AgentLens active, disabled, or failing"
correctly.

### 1.5.4 Worktree cleanup is in scope but unimplemented in the plan

Section 5.4 lists "orphan worker worktrees" as a cleanup target. The
implementation plan only classifies `runs/<workspace>/<run_id>` directories.
`worktrees/<workspace>/<run_id>` is allocated by `_state_paths()` and is
not deleted when a run directory is removed. The plan must also classify
and clean orphan worktree roots when their matching run directory is gone
or older than the retention window.

### 1.5.5 Payload size is unbounded above `summary`

`build_event_payload()` caps the `summary` string at 1200 characters but
does not cap the total payload byte size. Gate-retry events embed
`previous_candidate`, `gate_result`, and `changed_files` via
`_retry_context()`; large diffs or long gate reports can produce payloads
well above the 4096-byte threshold that
`AgentLens/src/agentlens/evaluator/agentrunway_events.py` flags as
`oversized`. The emitter should either truncate large extras at write time
or accept that AgentLens may downgrade `payload_safety` for legitimate
runs.

### 1.5.6 Cleanup safety vs. concurrent access

`agentrunway clean` removes `runs/<workspace>/<run_id>` directories that
contain `state.sqlite`. A detached run that is still alive holds that
SQLite file open. The retention planner must refuse to remove a run
directory whose `run.json` reports `status="running"` regardless of age,
and should additionally treat the presence of a lock file (or `pidfile`
under `.agentrunway-detached`) as a hard block.

### 1.5.7 Detach re-entry must not re-resolve plan/spec across cwds

The detached subprocess re-executes `agentrunway run --plan ... --spec ...`
with the original (possibly relative) argv. If the parent and the
subprocess have the same cwd this is fine, but the launcher sets
`cwd=repo_root`, which may differ from the operator's invocation cwd. The
plan must require the launcher to absolute-ize `--plan` and `--spec` in
the rebuilt argv before launching the detached process.

### 1.5.8 Reconciliation cherry-pick guard

`plan_reconciliation()` will be extended to detect interrupted cherry-pick
state on `run.json.main_worktree`. `Path("")` evaluates to `Path(".")`,
which is truthy, so a missing or empty `main_worktree` would silently
check the current process cwd. The implementation must guard explicitly on
the *string* value before constructing a `Path`.

## 2. Goals

- Make AgentRunway the only supported plan-executor integration target for
  AgentLens.
- Emit AgentRunway events to AgentLens through `agentrunway.*` while keeping the
  local event journal authoritative.
- Add AgentLens projection and evaluation for AgentRunway runs: timeline, gate
  results, blocked reasons, retry evidence, artifact coverage, and evidence
  strength.
- Improve AgentRunway operator UX across `run`, `status`, `inspect`, `events`,
  `resume`, `apply`, and `clean`.
- Strengthen long-running run stability with detach, resume planning, watchdog
  recovery, safe cleanup, and conflict-aware apply behavior.
- Remove active AgentLens/AgentRunway references to CPE/CME and KWS common
  observability plans.

## 3. Non-Goals

- No CPE/CME skill directory deletion.
- No compatibility bridge from CPE/CME into AgentRunway.
- No `kws.orchestrator.*` common KWS event contract.
- No legacy fallback parser for `kws-cpe.*` or `kws-cme.*` in new AgentLens
  AgentRunway support.
- No event-sourced replacement for AgentRunway SQLite state.
- No web dashboard in this slice. CLI and JSON projection are enough.
- No automatic source checkout modification. `agentrunway apply` remains
  explicit.

## 4. Architecture

AgentRunway owns execution. AgentLens observes and evaluates.

```text
agentrunway run
  -> ~/.agentrunway/runs/<workspace>/<run_id>/
     -> state.sqlite
     -> run.json
     -> contract.json
     -> events.jsonl
     -> artifact_graph.json
     -> coverage.json
  -> AgentLens
     -> agentrunway.* events
     -> AgentRunway timeline projection
     -> AgentRunway evidence coverage
```

AgentRunway local state is authoritative. AgentLens failures never decide
whether a task is merged, blocked, retried, resumed, or applied. AgentLens is a
durable observation layer that helps inspect and compare runs after the fact.

## 5. Components

### 5.1 AgentRunway Emitter

AgentRunway keeps its local event journal and SQLite outbox. A concrete
AgentLens emitter is added behind the existing `EventJournal` abstraction.

The emitter records only runner-validated facts. Worker text output and
worker-claimed status do not become trusted AgentLens evidence unless the runner
validated the corresponding artifact, git state, and gate result.

Core events include:

```text
agentrunway.run_started
agentrunway.contract_created
agentrunway.worker_dispatched
agentrunway.worker_result
agentrunway.review_dispatched
agentrunway.review_result
agentrunway.verification_dispatched
agentrunway.verification_result
agentrunway.gate_retry
agentrunway.merge_ready
agentrunway.merge_conflict
agentrunway.run_finished
agentrunway.run_blocked
```

Payloads remain bounded and redacted. Home paths are made home-relative, secret
like keys are redacted, and long summaries are capped before local write and
before AgentLens emit.

### 5.2 AgentLens AgentRunway Projection

AgentLens gains AgentRunway-specific projection for `agentrunway.*` events. The
projection is additive and does not change existing evaluator status semantics.

Projected facts include:

- run lifecycle status
- task lifecycle status
- implementer, reviewer, and verifier attempt counts
- gate retry count and reason
- blocked task reasons
- merge readiness and merge conflict evidence
- contract and artifact graph availability
- coverage state for covered, partial, blocked, and unreferenced spec refs
- AgentLens emit health

The projection explicitly does not parse or score `kws.orchestrator.*`,
`kws-cpe.*`, or `kws-cme.*` as part of AgentRunway support.

### 5.3 AgentRunway CLI Control Plane

The CLI becomes the operator-facing control plane:

```bash
agentrunway run --topic <topic> --adapter codex --detach
agentrunway status --last
agentrunway inspect --last --json
agentrunway events --last --type agentrunway.gate_retry
agentrunway resume --last --dry-run --json
agentrunway apply --last
agentrunway clean --older-than 14d --dry-run
```

Human output should answer:

- What is the run id?
- Is it still running, finished, blocked, cancelled, or missing?
- Which task is blocked and why?
- Which gate failed?
- Was a retry attempted?
- Is AgentLens active, disabled, or failing?
- What should the operator do next?

JSON output remains stable for scripts and tests.

### 5.4 Cleanup and Retention

`agentrunway clean` stops being a stub. It classifies retained files before
removing anything:

- successful runs older than the retention window
- blocked or failed runs older than the retention window
- orphan worker worktrees
- orphan run directories
- stale AgentRunway branches
- interrupted cherry-pick state that needs operator review

The default behavior should be conservative. `--dry-run` shows candidates,
reasons, and expected writes. Deletion requires an explicit non-dry-run command.

### 5.5 CPE/CME Cleanup Boundary

CPE and CME skill directories remain on disk, but AgentLens and AgentRunway no
longer treat them as supported integration targets.

Cleanup targets:

- delete
  `docs/superpowers/plans/2026-05-20-agentlens-kws-common-observability-contract.md`
  from the active implementation-plan path
- delete
  `AgentLens/docs/spec/2026-05-20-agentlens-kws-common-observability-contract-design.md`
  from the active AgentLens design path
- remove active AgentLens docs/tests that describe CPE/CME or
  `kws.orchestrator.*` as the forward path
- avoid creating new KWS common parser, importer, or evaluator modules
- keep CPE/CME skill internals independent and out of AgentRunway design

No archival migration is part of this cleanup. If a historical copy is needed
later, it should be requested separately rather than kept in the active
AgentLens/AgentRunway planning surface.

## 6. Data Flow

### 6.1 Run Start

1. Operator starts `agentrunway run`.
2. AgentRunway resolves plan/spec inputs.
3. AgentRunway creates local run state and frozen `contract.json`.
4. AgentRunway records `agentrunway.run_started` and
   `agentrunway.contract_created` locally.
5. If AgentLens is available, those events are emitted to AgentLens. If not,
   the local outbox records disabled or failed status.

### 6.2 Worker and Gate Flow

1. AgentRunway dispatches implementer workers.
2. Runner validates worker result artifacts, commits, changed files, and method
   audit evidence.
3. Runner dispatches reviewer and verifier gates.
4. Reviewer `changes_requested` and verifier `failed` may create bounded
   implementer retries.
5. Gate outcomes are recorded as `agentrunway.review_result`,
   `agentrunway.verification_result`, and `agentrunway.gate_retry`.
6. Only verifier `passed` can promote a fresh candidate to merge ready.

### 6.3 Resume and Recovery

`resume --dry-run --json` produces a reconciliation plan without writes.
Non-dry-run `resume` applies the plan idempotently.

The existing actions remain:

- `reconcile_forward`: valid artifact exists but DB state is behind
- `retry`: dead worker has no valid result artifact

The next recovery layer adds real handling for reserved actions:

- `abort_cherry_pick`: run main has an interrupted cherry-pick
- `retain_orphan`: unmatched worktree is kept for diagnostics
- `block`: retry budget is exhausted or operator action is required

### 6.4 Apply

`agentrunway apply` remains explicit. It refuses unsafe source checkouts by
default, avoids duplicate commit application, reports already-applied commits,
and aborts cleanly on cherry-pick conflict.

## 7. Error Handling

AgentLens is best effort. AgentRunway never fails a run only because AgentLens
is unavailable.

Failure states:

- `agentlens_disabled`: no emitter configured or AgentLens unavailable
- `agentlens_failed`: AgentLens emit attempted and failed
- `agentlens_emitted`: AgentLens emit succeeded

`status` and `inspect` summarize:

- total local events
- emitted events
- failed events
- disabled events
- last AgentLens status
- last AgentLens error when available

Worker, gate, merge, and apply errors continue to use AgentRunway task and
worker states. AgentLens mirrors those facts but does not author them.

## 8. Testing Strategy

### 8.1 AgentRunway Tests

- AgentLens CLI missing does not block runs.
- AgentLens emitter failure records local evidence and continues.
- `agentrunway.*` events are written to local `events.jsonl`, SQLite, and the
  emitter with the same event type and redacted payload.
- `status`, `inspect`, and `events` expose AgentLens health.
- `resume --dry-run` is side-effect free.
- `resume` is idempotent for reconciliation actions.
- `clean --dry-run` does not delete files.
- `clean` removes only classified, safe candidates.
- `apply` avoids duplicate commits and reports conflicts clearly.

### 8.2 AgentLens Tests

- AgentLens parses and projects `agentrunway.*` event streams.
- Projection includes timeline, gate outcomes, retry reasons, blocked status,
  and coverage.
- Evidence coverage is additive and does not alter existing evaluator pass or
  fail status.
- CPE/CME and `kws.orchestrator.*` are not introduced as AgentRunway support
  paths.

### 8.3 Cleanup Tests

- Active KWS common observability specs/plans are deleted from the
  AgentLens/AgentRunway planning surface.
- AgentLens active docs no longer recommend CPE/CME as the forward executor
  integration path.
- CPE/CME skill directories remain untouched unless a separate user request
  targets them directly.

## 9. Rollout Plan

1. Remove active CPE/CME/KWS common observability plan and spec surfaces from
   AgentLens/AgentRunway planning paths.
2. Add AgentRunway AgentLens emitter integration behind `EventJournal`.
3. Add AgentLens `agentrunway.*` projection and evidence coverage.
4. Improve `status`, `inspect`, and `events` output around AgentLens health and
   next operator actions.
5. Implement detach support for long-running AgentRunway runs.
6. Expand resume reconciliation actions beyond the current initial slice.
7. Implement safe `clean` retention behavior.
8. Harden `apply` output and conflict reporting.
9. Update README, skill docs, and tests to make AgentRunway the only supported
   AgentLens executor integration.

## 10. Acceptance Criteria

- New AgentRunway runs emit `agentrunway.*` locally and, when available, to
  AgentLens.
- AgentLens can project an AgentRunway timeline with review, verification,
  retry, merge, blocked, and finish evidence.
- AgentLens/AgentRunway active docs no longer present CPE/CME or
  `kws.orchestrator.*` as supported forward paths.
- CPE/CME skill directories remain present and independent.
- `agentrunway status --last` shows AgentLens health and next operator action.
- `agentrunway resume --last --dry-run --json` reports planned recovery without
  writes.
- `agentrunway clean --older-than 14d --dry-run` classifies cleanup candidates
  without deleting them.
- Verification covers AgentRunway evals, relevant AgentLens tests, py_compile,
  shell syntax, `git diff --check`, and `graphify update .` after code changes.
