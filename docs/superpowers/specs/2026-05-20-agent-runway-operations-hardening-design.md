# Design: AgentRunway Operations Hardening

Date: 2026-05-20
Status: Draft for user review
Owner: KWS
Parent Design: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
Parent Plan: `docs/superpowers/plans/2026-05-20-agent-runway.md`
Previous Slice: `docs/superpowers/specs/2026-05-20-agent-runway-production-supervisor-design.md`

## Spec Manifest

- S1: Summary
- S2: Goals
- S3: Non-Goals
- S4: OpenSpec-Derived Design Inputs
- S5: Superpowers-to-AgentRunway Contract
- S6: Architecture
- S7: Component Boundaries
- S8: Run Evidence Bundle
- S9: Observability and AgentLens
- S10: Resume and Watchdog Reconciliation
- S11: Review and Verification Gates
- S12: Error Handling and Retry Policy
- S13: Testing Strategy
- S14: Acceptance Criteria
- S15: Risks and Trade-offs

## S1. Summary

Harden AgentRunway after the production supervisor merge by adding an
operations layer that makes every run inspectable, recoverable, and gateable.
This slice does not replace the Superpowers workflow. Humans still create and
review:

```text
docs/superpowers/specs/<topic>-design.md
docs/superpowers/plans/<topic>.md
```

AgentRunway's job begins after those documents exist. It freezes the supplied
spec and plan into a runner-owned contract, executes tasks, records local and
AgentLens evidence, reconciles interrupted runs, and only merges candidates
that pass review and verification gates.

The chosen implementation direction is a vertical operations core:

```text
observability -> resume/watchdog -> review/verify gates
```

Observability comes first because it is the diagnostic substrate for watchdog
recovery and gate failures.

## S2. Goals

- Freeze the submitted Superpowers spec and plan into a canonical run contract.
- Preserve self-contained run evidence under `~/.agentrunway/runs/...`.
- Provide stable human and JSON diagnostics for `status`, `inspect`, `events`,
  `resume`, and coverage-style reporting.
- Mirror runner-validated events to AgentLens through a best-effort outbox.
- Make `resume` produce and apply an idempotent reconciliation plan.
- Make the watchdog classify worker/process/artifact states from runner-owned
  evidence, not worker claims.
- Require real reviewer and verifier worker gates before a production adapter
  candidate enters `merge_ready`.
- Report which spec sections and task requirements were covered, partially
  covered, blocked, or unreferenced by the run.

## S3. Non-Goals

- No replacement of Superpowers `brainstorming` or `writing-plans`.
- No adoption of OpenSpec's `openspec/` directory as a source of truth.
- No automatic generation of Superpowers specs or plans.
- No web UI in this slice.
- No new runtime adapter such as Gemini or Aider.
- No GitHub PR, CI, or deployment automation.
- No mandatory AgentLens dependency; local runner evidence remains
  authoritative.
- No automatic source checkout modification beyond the existing explicit
  `agentrunway apply --run <run_id>` flow.

## S4. OpenSpec-Derived Design Inputs

OpenSpec is useful here as a set of operating ideas, not as a competing
documentation structure. The relevant inputs are:

1. **Self-contained change bundles** become AgentRunway run evidence bundles.
   OpenSpec keeps proposal, specs, design, and tasks together for review. In
   AgentRunway, the source documents stay in `docs/superpowers/`, while each run
   stores a complete manifest of the exact spec, plan, packets, results, logs,
   events, and coverage it executed.

2. **Delta-style thinking** becomes execution coverage. AgentRunway should not
   rewrite Superpowers specs into OpenSpec delta files. Instead, it reports what
   the run covered, partially covered, blocked, and left unreferenced.

3. **Behavior contracts stay separate from implementation plans.** Reviewer and
   verifier workers should receive spec behavior, scenarios, non-goals, and
   acceptance signals separately from plan file claims and implementation notes.
   The gates judge whether the candidate satisfies the behavior contract.

4. **Artifact DAG/status** becomes the run artifact graph. Operators should be
   able to inspect the state of `spec -> plan -> packet -> implementer_result ->
   review_result -> verification_result -> merge_candidate -> apply_record`.

5. **Agent/script-friendly JSON** becomes a stable diagnostics contract. Human
   summaries remain concise, while `--json` output is structured enough for
   AgentLens, future automation, and other agents.

Reference inputs:

- `https://github.com/Fission-AI/OpenSpec/blob/main/docs/getting-started.md`
- `https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md`
- `https://github.com/Fission-AI/OpenSpec/blob/main/docs/opsx.md`
- `https://raw.githubusercontent.com/Fission-AI/OpenSpec/main/schemas/spec-driven/schema.yaml`

## S5. Superpowers-to-AgentRunway Contract

AgentRunway consumes, but does not author, the Superpowers design and plan
documents. On `agentrunway run --spec <spec.md> --plan <plan.md>`, preflight
creates `contract.json` with:

- spec path, hash, title, and manifest sections,
- plan path, hash, parsed tasks, and task fences,
- base commit and workspace identity,
- task dependencies, file claims, acceptance commands, and required skills,
- `spec_refs` coverage from each task to stable spec sections,
- runtime adapter, model profile, and policy settings.

Preflight should fail before dispatch when:

- a task references a missing spec section,
- a task has no acceptance command,
- file claims conflict in the same wave,
- a task has no file claims for a code-changing phase,
- the source checkout is dirty without explicit allowance,
- the plan cannot be parsed into deterministic task packets.

Warnings should not block dispatch when they are useful but not fatal:

- a spec section is unreferenced by any task,
- a task references broad file globs,
- AgentLens is unavailable in best-effort mode,
- optional reviewer/verifier model overrides are absent.

## S6. Architecture

The runner remains the only owner of execution state.

```text
Superpowers spec + plan
  -> preflight contract
  -> SQLite run state
  -> artifact graph
  -> local event journal
  -> AgentLens outbox
  -> worker dispatch
  -> watchdog reconciliation
  -> review / verify gates
  -> merge queue
  -> explicit apply
```

The host session stays thin. It invokes the runner, surfaces summaries, and
does not coordinate worker state from conversation context.

The source of truth order is:

1. SQLite and run evidence files under `~/.agentrunway/runs/...`.
2. Git refs and worktrees under `~/.agentrunway/worktrees/...`.
3. AgentLens mirrored events.
4. Host conversation summaries.

AgentLens is an observability sink, not the authority for recovery.

## S7. Component Boundaries

`runner.py` remains the high-level command flow for `run`, `resume`, `cancel`,
`apply`, `status`, `inspect`, and `events`. It delegates operational details to
focused modules.

`events.py` becomes the event journal and AgentLens outbox boundary:

- build canonical event payloads,
- redact home paths and secret-like values,
- write local JSONL events,
- store event/outbox rows in SQLite,
- attempt best-effort AgentLens emission,
- expose event query helpers for `events --run`.

`status.py` becomes the operator diagnostics boundary:

- summarize run/task/worker/merge/apply state,
- format failure reasons and blockers,
- return stable JSON shapes for automation,
- derive artifact progress and coverage summaries.

`watchdog.py` becomes the reconciliation planner:

- read SQLite, run files, git refs, process handles, logs, artifacts, and
  worktree state,
- classify evidence,
- return a dry-run action plan,
- apply actions idempotently when `resume` is not dry-run.

`supervisor.py` becomes role-generic worker orchestration:

- run implementer, reviewer, and verifier attempts through one worker lifecycle
  path,
- keep role-specific prompt materialization and result validation explicit,
- derive candidate changed files from git, not worker claims.

`db.py` gains repository methods for existing tables before adding new tables.
The current `workers`, `merge_queue`, `agentlens_events`, `watchdog_events`,
`artifacts`, and `applied_commits` tables should be used as the primary state
surface.

`models.py` may add small dataclasses for run contracts, artifact graph nodes,
coverage rows, reconciliation actions, and event outbox records.

## S8. Run Evidence Bundle

Each run should preserve enough evidence to answer: what was requested, what ran,
what changed, what passed, what failed, and what was applied.

```text
~/.agentrunway/runs/<workspace_id>/<run_id>/
  run.json
  state.sqlite
  contract.json
  artifact_graph.json
  coverage.json
  events.jsonl
  packets/
  prompts/
  logs/
  artifacts/
```

`contract.json` is immutable after dispatch starts. If a user edits the spec or
plan while a run is active, the run still refers to the frozen hashes from
preflight. A later run can use the updated documents.

`artifact_graph.json` is derived state and can be regenerated from SQLite and
filesystem evidence. It records nodes such as `spec`, `plan`, `task_packet`,
`worker_result`, `review_result`, `verification_result`, `merge_candidate`, and
`apply_record`, each with status `missing`, `ready`, `running`, `done`, or
`failed`.

`coverage.json` summarizes `spec_refs` by task and final outcome:

```json
{
  "covered": ["S1", "S2"],
  "partial": ["S6"],
  "blocked": ["S8"],
  "unreferenced": ["S14"]
}
```

Coverage is evidence for humans and reviewers. It is not a proof system.

## S9. Observability and AgentLens

The local event journal records runner-validated facts. Every event should be
written locally before any AgentLens emission attempt.

Core event types:

```text
agentrunway.run_started
agentrunway.contract_created
agentrunway.worker_dispatched
agentrunway.worker_result
agentrunway.worker_rejected
agentrunway.review_dispatched
agentrunway.review_result
agentrunway.verification_dispatched
agentrunway.verification_result
agentrunway.merge_ready
agentrunway.merge_applied
agentrunway.merge_conflict
agentrunway.resume_planned
agentrunway.resume_action
agentrunway.apply_started
agentrunway.apply_finished
agentrunway.run_finished
agentrunway.run_blocked
```

The `agentlens_events` table acts as an outbox with statuses:

```text
local_recorded
agentlens_emitted
agentlens_failed
agentlens_disabled
```

`inspect` should show AgentLens status, last successful emission, failed event
count, and the local event file path. AgentLens failure does not fail the run
unless a future strict mode explicitly requires it.

Diagnostics commands:

- `status --run <run_id>`: concise human summary.
- `inspect --run <run_id>`: detailed human summary.
- `inspect --run <run_id> --json`: stable artifact graph, task, worker, merge,
  coverage, and AgentLens state.
- `events --run <run_id>`: event list with redacted payloads.
- `events --run <run_id> --json`: stable event stream for automation.
- `resume --run <run_id> --dry-run --json`: reconciliation plan without writes.

## S10. Resume and Watchdog Reconciliation

`resume` should first plan, then apply. The planning phase is always safe to run
and should be exposed through `--dry-run`.

Example action plan:

```json
{
  "run_id": "example-run",
  "actions": [
    {
      "target": "task_001-implementer-001",
      "action": "reconcile_forward",
      "reason": "valid_result_artifact_exists"
    },
    {
      "target": "task_002-implementer-001",
      "action": "retry",
      "reason": "dead_process_missing_result"
    },
    {
      "target": "merge_candidate:3",
      "action": "abort_cherry_pick",
      "reason": "merge_in_progress"
    }
  ]
}
```

Reconciliation evidence:

- SQLite worker, task, merge, artifact, and applied commit rows,
- `run.json`, `contract.json`, `artifact_graph.json`, and `events.jsonl`,
- worker output paths and result JSON files,
- stdout/stderr mtimes and bounded excerpts,
- process liveness when a PID exists,
- git branch heads, worktree existence, and cherry-pick state.

Idempotency rules:

- Terminal tasks are not re-run.
- Already-merged candidates are not cherry-picked again.
- Already-applied commits are skipped by `apply`.
- A valid result artifact without a matching DB transition is reconciled
  forward once.
- Dead non-reattachable workers with no valid result are retried within budget.
- Orphan worktrees are either reclaimed into DB state or retained as diagnostic
  artifacts; they are not silently deleted.

## S11. Review and Verification Gates

Production adapter candidates must pass review and verification before merge.
The implementer path no longer marks a candidate `merge_ready` directly.

Reviewer input:

- relevant spec sections and scenarios,
- task packet and file claims,
- candidate diff and changed files,
- worker result and method audit evidence,
- non-goals and acceptance signals.

Reviewer outcomes:

- `approved`: continue to verifier,
- `changes_requested`: create a new implementer attempt with reviewer findings,
- `rejected`: block the task unless a future policy explicitly allows recovery.

Verifier input:

- relevant spec sections and acceptance signals,
- candidate commit list,
- changed files,
- acceptance commands,
- reviewer result,
- bounded command output policy.

Verifier outcomes:

- `passed`: candidate enters `merge_ready`,
- `failed`: retry implementer if actionable and within budget,
- `blocked`: stop the task with evidence.

Review and verification workers use the same worker lifecycle contract as
implementers: isolated worktree, prompt path, output path, result schema,
stdout/stderr logs, and runner-owned validation.

## S12. Error Handling and Retry Policy

Default retry budgets are role-specific and persisted in SQLite:

- implementer retry budget: 1,
- review changes-requested budget: 1,
- verifier retry budget: 1,
- merge conflict redispatch budget: 1.

Default classifications:

- launch failure or nonzero exit: `adapter_crashed`, retry once,
- timeout: cancel process group, mark `timeout`, retry once,
- stalled worker: record observe/nudge evidence, then cancel/retry when timeout
  policy allows,
- missing or invalid result JSON: `malformed_result`, retry once,
- method audit failure: `method_audit_failed`, block by default,
- diff scope failure: `diff_scope_failed`, block by default,
- reviewer `changes_requested`: retry implementer once with findings,
- reviewer `rejected`: block,
- verifier `failed`: retry once only when evidence is actionable,
- merge conflict: retry once from updated run main, then block,
- AgentLens emit failure: mark outbox failure and continue.

Retries always create a new worker id and a new worktree. Resume must never
reset retry counters.

## S13. Testing Strategy

Tests must remain deterministic by default and must not require real model
calls. Fake Codex and Claude CLI fixtures should continue to exercise the real
process adapter path.

Required eval additions:

- preflight writes `contract.json` and rejects missing `spec_refs`,
- preflight rejects tasks without acceptance commands,
- `events --run --json` returns local event rows and AgentLens outbox status,
- AgentLens failure records `agentlens_failed` and does not fail the run,
- `inspect --run --json` returns artifact graph and coverage summaries,
- dead worker with missing result produces a retry reconciliation plan,
- valid result artifact with missing DB transition reconciles forward,
- cherry-pick in progress produces an abort/requeue action,
- orphan worktree is retained or reclaimed with diagnostic evidence,
- `resume --dry-run` performs no writes,
- running `resume` twice does not duplicate workers, candidates, merges, or
  applied commits,
- implementer success dispatches reviewer instead of entering `merge_ready`,
- reviewer approved dispatches verifier,
- reviewer changes_requested creates a bounded implementer retry,
- verifier passed moves candidate to `merge_ready`,
- verifier failed follows retry/block policy.

## S14. Acceptance Criteria

- A run can be understood from `status`, `inspect`, and `events` without reading
  the host conversation.
- Every production run has a frozen `contract.json` linking exact spec and plan
  hashes to parsed tasks.
- Every production run has local event evidence even when AgentLens is
  unavailable.
- AgentLens emission state is visible in `inspect` and `events`.
- `inspect --json` exposes a stable artifact graph and coverage summary.
- `resume --dry-run --json` shows the planned recovery actions.
- `resume` is idempotent for terminal tasks, valid artifacts, merge candidates,
  and applied commits.
- Implementer candidates cannot merge until reviewer and verifier gates pass.
- Review and verification failures carry enough evidence for an operator to
  decide whether to retry, revise the plan, or block.
- Existing local and fake production adapter evals continue to pass.

## S15. Risks and Trade-offs

- **Risk: Observability scope grows into a UI project.** Mitigation: keep this
  slice CLI- and JSON-first; defer web UI.
- **Risk: Coverage summary is mistaken for formal proof.** Mitigation: label it
  as runner evidence derived from `spec_refs`, gate results, and task outcomes.
- **Risk: AgentLens availability affects execution.** Mitigation: local journal
  is authoritative and AgentLens remains best-effort by default.
- **Risk: Review/verify gates double runtime cost.** Mitigation: gates are
  production-adapter behavior; deterministic fake tests remain default.
- **Risk: Runner modules become tangled.** Mitigation: keep event recording,
  diagnostics formatting, reconciliation planning, worker lifecycle, and command
  flow in separate modules with small public APIs.

There are no open design questions for this slice. The implementation plan can
choose task boundaries, but should preserve the milestone order:
observability, resume/watchdog, then review/verify gates.
