# Design: AgentRunway Operations + Quality Engine

Date: 2026-05-20
Status: Approved for implementation planning
Owner: KWS

## 1. Summary

AgentRunway now has a working control plane: deterministic run state, worker
supervision, review and verification gates, bounded gate retries, resume
planning, safe cleanup, explicit apply, and AgentLens `agentrunway.*`
observability. The next improvement should make that control plane more
operationally intelligent and improve execution quality for risky tasks.

This design adds an Operations + Quality Engine on top of the existing runner.
It does not replace AgentRunway. It adds shared diagnosis, policy, candidate
selection, and decision evidence so `run`, `status`, `inspect`, and `resume`
answer the same questions in the same way:

- What state is this run actually in?
- Which actions are safe to automate?
- Which actions need an operator?
- Which candidate should be trusted when more than one exists?
- Why did AgentRunway retry, select, block, or redispatch work?

The design combines two priorities:

- Operational stability: better run diagnosis, resume planning, conflict
  classification, and next operator action.
- Execution quality: high-risk multi-candidate execution, deterministic
  candidate ranking, policy-owned retry budgets, and AgentLens evidence for
  quality decisions.

## 2. Context

Recent AgentRunway commits added:

- production worker supervision for Codex and Claude adapters
- review and verification gates
- bounded redispatch after reviewer or verifier failure
- merge queue state and explicit source apply
- run diagnostics through `status`, `inspect`, and `events`
- resume planning for interrupted or stale worker state
- retention cleanup safety checks
- AgentLens emission and AgentLens projection for `agentrunway.*` events

The remaining product gap is not a missing executor. It is the judgement layer
between execution evidence and the next action. Today that judgement is split
across `runner.py`, `reconciliation.py`, `retention.py`, `status.py`, and
AgentLens projection code. This makes the system work, but it makes it harder
to explain repeated failures, compare multiple candidates, or safely automate
recovery.

The next slice should centralize that judgement while preserving the existing
state authority:

- AgentRunway SQLite, run artifacts, and git state remain authoritative.
- AgentLens remains an observation and evaluation layer.
- The source checkout is only modified through explicit `agentrunway apply`.
- Merge conflicts are not auto-edited.

## 3. Goals

- Add a shared run diagnosis model used by `status`, `inspect`, `resume`, and
  cleanup planning.
- Move retry and high-risk execution decisions out of ad hoc runner branches
  into an explicit quality policy module.
- Support high-risk multi-candidate execution with deterministic candidate
  ranking.
- Plan safe conflict redispatch when a merge conflict can be retried from a new
  run-main base.
- Stop repeated conflicts and unsafe recovery paths with clear manual actions.
- Emit local and AgentLens decision evidence for candidate ranking, retries,
  blocks, and conflict redispatch plans.
- Keep dry-run recovery side-effect free and make non-dry-run recovery
  idempotent.

## 4. Non-Goals

- No new executor or rewrite of the AgentRunway runner.
- No web dashboard in this slice.
- No automatic source checkout modification.
- No automatic merge-conflict editing.
- No remote execution service.
- No replacement of SQLite or JSON artifacts as AgentRunway's source of truth.
- No CPE/CME compatibility layer or legacy event bridge.

## 5. Architecture

The design adds four focused modules under the existing AgentRunway package:

```text
agentrunway run/status/inspect/resume/clean
  -> diagnostics.py
     -> RunDiagnosis
  -> quality_policy.py
     -> task candidate count, retry budget, redispatch budget
  -> candidate_selection.py
     -> deterministic candidate ranking
  -> decision_events.py
     -> local journal + AgentLens evidence events
```

The modules have strict responsibilities:

- `diagnostics.py` answers "what state is the run in now?"
- `quality_policy.py` answers "what execution or recovery options are allowed?"
- `candidate_selection.py` answers "which validated candidate should be used?"
- `decision_events.py` answers "how do we record why a decision was made?"

`diagnostics` and `quality_policy` must not become a single mixed module.
Diagnosis is read-only and state-derived. Policy is forward-looking and
configuration-derived. Keeping them separate lets status and dry-run resume
share the same diagnosis without accidentally scheduling work.

## 6. Components

### 6.1 Diagnostics

`diagnostics.py` reads:

- `run.json`
- `state.sqlite`
- local `events.jsonl`
- merge candidates
- worker records and handles
- main and worker worktree git state
- detach pidfile state
- AgentLens emit summary

It returns a `RunDiagnosis` shape:

```json
{
  "run_id": "example-run",
  "status": "needs_resume",
  "reason": "dead_worker_missing_result",
  "next_action": "agentrunway resume --run example-run",
  "safe_actions": ["resume", "inspect"],
  "manual_actions": [],
  "blocked_tasks": [],
  "conflict": null,
  "agentlens_health": {
    "status": "active",
    "last_error": null
  }
}
```

Initial diagnosis statuses:

```text
healthy
running
finished
blocked
needs_resume
blocked_by_gate
needs_conflict_redispatch
needs_manual_action
cleanup_safe
cleanup_blocked
missing
```

Initial diagnosis reasons:

```text
none
dead_worker_valid_result
dead_worker_missing_result
gate_budget_exhausted
review_changes_requested
verification_failed
verification_blocked
merge_conflict
repeated_merge_conflict
interrupted_cherry_pick
dirty_source_checkout
agentlens_degraded
active_detached_run
```

### 6.2 Quality Policy

`quality_policy.py` owns execution policy that is currently implicit in runner
branches.

Default policy:

- low-risk task: 1 implementer candidate
- medium-risk task: 1 implementer candidate
- high-risk task: 2 implementer candidates
- reviewer `changes_requested`: retry once if feedback is actionable
- reviewer non-approved terminal status: block
- verifier `failed`: retry once if failure is actionable
- verifier `blocked`: block
- first merge conflict: allow one conflict redispatch from the current run-main
  base when the task has not already conflict-redispatched
- repeated merge conflict: stop with manual action

Actionable gate feedback requires at least one concrete signal:

- reviewer findings with changed-file or acceptance-command context
- verifier checks that name failing commands or artifacts
- changed files from the previous candidate
- task acceptance commands that can be re-run

The policy should be pure and testable. It should accept task metadata, gate
result, retry history, and conflict history, then return a decision object.

### 6.3 Candidate Selection

`candidate_selection.py` ranks validated candidates. It only ranks candidates
whose worker result and gate artifacts have already been validated by the
runner.

Ranking signals, in order:

1. verifier result is `passed`
2. reviewer result is `approved`
3. no file claim violation
4. required artifacts exist
5. acceptance evidence exists
6. diff scope matches task file claims
7. lower unexpected changed-file count
8. deterministic tie-breaker by candidate id

The output includes both the selected candidate and a score table for all
candidates, so AgentLens can explain why a candidate won or lost.

### 6.4 Decision Events

`decision_events.py` records decisions locally and, when available, emits them
to AgentLens.

New event types:

```text
agentrunway.quality_decision
agentrunway.candidate_ranked
agentrunway.conflict_redispatch_planned
```

Event payloads follow the existing AgentRunway event constraints:

- bounded payload size
- home-relative paths
- redacted secret-like values
- `agentrunway_run_id` alias for AgentLens correlation
- explicit `outcome`

Example `candidate_ranked` payload:

```json
{
  "run_id": "example-run",
  "agentrunway_run_id": "example-run",
  "task_id": "task_002",
  "decision": "select_candidate",
  "selected_candidate_id": 7,
  "scores": [
    {"candidate_id": 7, "rank": 1, "score": 96, "reasons": ["verifier_passed", "reviewer_approved"]},
    {"candidate_id": 8, "rank": 2, "score": 72, "reasons": ["reviewer_approved", "missing_acceptance_evidence"]}
  ]
}
```

## 7. Data Flow

### 7.1 Run Flow

1. Runner parses tasks and risk levels.
2. `quality_policy` determines candidate count and retry budgets per task.
3. Runner dispatches candidate workers.
4. Runner validates worker artifacts and file claims.
5. Reviewer and verifier gates run for each viable candidate.
6. `candidate_selection` ranks candidates that passed the required gates.
7. `decision_events` records the ranking and selected candidate.
8. Runner marks the selected candidate `merge_ready`.
9. Runner attempts merge into the run main worktree.
10. On conflict, `diagnostics` and `quality_policy` classify whether a
    conflict redispatch is safe.

### 7.2 Status and Inspect Flow

1. CLI resolves `--run` or `--last`.
2. `diagnostics` reads run state and returns `RunDiagnosis`.
3. `status` renders the diagnosis summary and next action.
4. `inspect --json` returns diagnosis details plus quality decisions and
   candidate ranking history.

### 7.3 Resume Flow

1. `resume --dry-run` computes diagnosis.
2. Recovery planning derives actions from diagnosis and policy.
3. Dry-run returns the plan without writes.
4. Non-dry-run applies idempotent actions only.
5. Applied actions are recorded as decision events.

### 7.4 AgentLens Flow

AgentLens remains downstream. It projects the new decision events into
evidence coverage without changing AgentRunway's execution authority.

Projected facts:

- selected candidate
- candidate ranking reasons
- retry budget decisions
- conflict redispatch plans
- blocked reason
- manual-action reason
- diagnosis status at decision time

## 8. Error Handling and Safety

Automatic resume may apply:

- `reconcile_forward` when a dead worker left a valid result artifact
- `retry` when a worker died without a result and retry budget remains
- `conflict_redispatch` when the first merge conflict can be retried from the
  current run-main base
- candidate selection when at least one candidate passed required gates

Automatic resume must stop for:

- interrupted cherry-pick
- repeated merge conflict
- file-claim violations across all candidates
- verifier `blocked`
- dirty source checkout before apply
- missing or corrupt authoritative artifacts

AgentLens emit failure is not an execution failure. It degrades evidence health
and appears in diagnosis, but it does not block runner progress.

## 9. CLI Behavior

Human `status` should include:

- run id
- diagnosis status
- reason
- next action
- AgentLens health
- blocked task, when present
- selected candidate or pending candidate decision, when present

JSON `inspect` should include:

- `diagnosis`
- `quality_policy`
- `candidate_rankings`
- `decision_events`
- `safe_actions`
- `manual_actions`

`resume --dry-run --json` should return the same plan shape used by non-dry-run
`resume`.

## 10. Testing Strategy

### 10.1 Unit Tests

- `diagnostics`:
  - finished healthy run
  - running detached run
  - dead worker with valid result
  - dead worker without result
  - interrupted cherry-pick
  - first merge conflict
  - repeated merge conflict
  - AgentLens degraded health

- `quality_policy`:
  - high-risk task gets two candidates
  - low and medium task get one candidate
  - reviewer actionable feedback allows one retry
  - reviewer non-actionable failure blocks
  - verifier failed with acceptance evidence allows one retry
  - verifier blocked does not retry
  - first conflict allows redispatch
  - repeated conflict requires manual action

- `candidate_selection`:
  - verifier-passed candidate beats non-passed candidate
  - reviewer-approved candidate beats changes-requested candidate
  - file-claim violation loses
  - missing required artifact loses
  - tie breaks deterministically by candidate id

### 10.2 Integration Tests

- `status --last` renders diagnosis and next action.
- `inspect --last --json` includes diagnosis and ranking evidence.
- `resume --dry-run` is side-effect free.
- `resume` is idempotent for recovery actions.
- high-risk runner flow dispatches multiple candidates.
- gate failure retry uses policy decisions rather than hard-coded loop checks.
- first merge conflict creates a redispatch plan.
- repeated merge conflict blocks with manual action.
- AgentLens projection includes new decision events.

### 10.3 Verification Commands

Implementation completion should verify:

```bash
( cd skills/agent-runway && ./evals/run.sh )
python3 -m py_compile skills/agent-runway/scripts/agentrunway.py skills/agent-runway/scripts/agentrunway/*.py skills/agent-runway/scripts/agentrunway/adapters/*.py skills/agent-runway/evals/*.py
bash -n skills/agent-runway/evals/run.sh
python3 skills/agent-runway/evals/check_skill_contract.py
```

It should also run the relevant AgentLens focused tests for
`agentrunway.*` event projection and the repository-level checks:

```bash
git diff --check
graphify update .
```

## 11. Rollout Plan

1. Add pure policy and ranking modules with unit tests.
2. Add read-only diagnostics and route `status` and `inspect` through it.
3. Wire decision events into the local event journal.
4. Extend AgentLens AgentRunway projection for the new decision events.
5. Use quality policy in the runner's gate retry decisions.
6. Add high-risk multi-candidate execution and deterministic selection.
7. Extend resume planning with safe conflict redispatch and repeated-conflict
   manual action.
8. Update README and reference docs.

## 12. Acceptance Criteria

- `agentrunway status --last` shows diagnosis, reason, next action, and
  AgentLens health.
- `agentrunway inspect --last --json` includes quality decisions and candidate
  ranking evidence.
- High-risk tasks can produce two candidates by policy.
- Candidate selection is deterministic and evidence-backed.
- Gate retry budgets are computed by `quality_policy`, not hard-coded in the
  runner loop.
- First merge conflict can become a safe redispatch plan.
- Repeated merge conflict becomes a manual-action block.
- `resume --dry-run` and `resume` share the same diagnosis and planning engine.
- AgentLens can project why AgentRunway selected, retried, blocked, or planned
  redispatch.
- Existing AgentRunway and AgentLens focused tests remain passing.

## 13. Design Review Notes

This scope intentionally combines operations and execution quality because the
same evidence drives both. A gate failure, merge conflict, or weak candidate is
not just an execution event; it is also the reason `status`, `inspect`, and
`resume` should recommend a different next action.

The implementation should keep changes incremental. The first useful slice is
diagnosis plus policy extraction. Multi-candidate execution and conflict
redispatch should come after the shared decision model is tested.
