# Design: AgentRunway Core Trust Hardening

Date: 2026-05-21
Status: Approved for implementation planning
Owner: KWS
Related Work:
- `docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md`
- `docs/superpowers/specs/2026-05-21-agentrunway-only-cpe-cme-removal-design.md`
- `docs/superpowers/specs/2026-05-21-agentrunway-hybrid-scheduler-failure-recovery-design.md`

## 1. Summary

AgentRunway should be hardened before the AgentLens Trust Console slice is
implemented. The Trust Console can only be useful if AgentRunway records the
execution truth precisely: plan failures are inspectable, spec references point
to real spec text, simulated runs cannot look like real merges, and success is
backed by worker, review, verification, and merge evidence.

The target is a runner that can answer four questions without manual SQLite or
artifact inspection:

```text
Did this run execute for real or only simulate success?
Which spec sections did each task actually receive?
Which evidence allows this task to be called merged?
Why did the run stop, and what can the operator do next?
```

This is a prerequisite hardening slice. It does not build the AgentLens
dashboard or the full Trust Console projection. It makes AgentRunway's own
state, artifacts, and events trustworthy enough for AgentLens to evaluate.

## 2. Evidence From The Comparison Run

The AgentLens AgentRunway Trust Console plan exposed four problems:

- The original plan failed lint because it used bare numeric `spec_refs` such
  as `6.3` and `10.1`; AgentRunway expected `S...` references.
- Rewriting those references to `S6.3` made lint pass, but task packets still
  received empty spec text because the runner packetizer did not canonicalize
  aliases back to manifest ids such as `S1.6.3`.
- A local `--fake-success` run reported `status=finished` and tasks as
  `merged` even though worker results had no changed files, no commit, and no
  commands run.
- A pre-contract plan lint failure wrote only weak run evidence. It did not
  have a usable state database, so follow-up inspection was less reliable than
  post-contract runs.

The KWS Codex Plan Executor path was not a better fallback. It accepted the
same plan as generic Markdown, but it ignored the fenced
`yaml agentrunway-task` metadata that contains AgentRunway's task ids,
dependencies, risks, file claims, spec refs, and acceptance commands. The
active repository direction is AgentRunway-only, so the right fix is to harden
AgentRunway instead of keeping CPE as a parallel execution path.

## 3. Goals

- Normalize all supported spec reference spellings into one canonical manifest
  id before lint, contract creation, coverage, packet generation, and prompts.
- Preserve durable evidence for plan-lint and preflight failures.
- Distinguish simulated local adapter success from real execution success in
  run status, task status, summaries, and apply behavior.
- Require evidence before a task can be called `merged`.
- Emit enough `agentrunway.*` events for AgentLens to evaluate trust later.
- Separate spec-reference coverage from implementation-evidence coverage.
- Keep AgentRunway as the single active execution path connected to AgentLens.

## 4. Non-Goals

- No revival of KWS Codex Plan Executor or KWS Claude Multi Agent Executor as
  supported fallback paths.
- No implementation of the AgentLens dashboard Trust Console in this slice.
- No migration of historical AgentRunway, CPE, or CME runs.
- No broad rewrite of the scheduler, quality policy, or process adapters.
- No attempt to make local fake adapter output count as verified work.
- No AgentLens write path from workers. The AgentRunway runner remains the only
  emitter of accepted execution facts.

## 5. Architecture

AgentRunway should use a single execution-evidence pipeline:

```text
plan/spec inputs
  -> canonical spec ref resolver
  -> lint result and immutable contract
  -> task packets with real spec slices
  -> worker/review/verification/merge evidence
  -> task status projection
  -> run summary, inspect, events, apply
  -> AgentLens agentrunway.* event stream
```

The important boundary is between "accepted evidence" and "operator
convenience." A fake adapter result is useful for smoke testing the runner, but
it is not accepted implementation evidence. A spec reference can be convenient
to write as `6.3`, but the runner must store the canonical section id and the
actual section text used by the worker.

## 6. Components

### 6.1 Canonical Spec Reference Resolver

Add one shared resolver used by lint, contract, runner packet slicing, coverage,
artifact graph, and prompt generation.

The resolver accepts these spellings when the spec has numbered headings:

```text
6.3
S6.3
S1.6.3
```

All three resolve to the same canonical manifest id, for example `S1.6.3`.
The canonical id is what AgentRunway stores in `contract.json`,
`coverage.json`, task packets, prompts, and SQLite. The original spelling may
be retained as `input_ref` for diagnostics, but it must not drive downstream
lookup.

Unknown refs should fail with a targeted diagnostic:

```text
task_003 references missing spec section 6.3.
Known numbered refs include 6.2, 6.3, 7.2, 7.3.
Use 6.3, S6.3, or S1.6.3.
```

### 6.2 Preflight Failure Evidence

Plan lint, contract preflight, adapter preflight, and dirty-source blockers
should create a minimal durable run record before returning to the operator.

Minimum artifacts:

- `run.json`
- `state.sqlite`
- `events.jsonl`
- `decision_packet.json`

Minimum events:

- `agentrunway.run_started`
- `agentrunway.preflight_failed`
- `agentrunway.run_blocked`

This makes `status`, `inspect`, `summarize`, and `events` work consistently for
both early blockers and post-dispatch failures.

### 6.3 Simulation Status

The local fake adapter should produce explicit simulation evidence:

```json
{
  "simulation": true,
  "status": "simulated_success",
  "changed_files": [],
  "commit": null,
  "commands_run": []
}
```

Runner projections should expose simulation separately:

- run status: `simulated_finished`
- task status: `simulated_completed`
- summary next action: `inspect simulation artifacts`
- apply: refused by default for simulated runs

The fake adapter should not claim TDD red/green success. It may report that the
TDD workflow was not exercised because the run was simulated.

### 6.4 Evidence-Based Merge Gate

A code-changing implementation task can become normal `merged` only when the
selected candidate has accepted implementation evidence. These evidence classes
must be present together:

- worker evidence: a commit produced by the worker candidate with changed files
  validated against file claims;
- review evidence: a review gate result that explicitly references the
  candidate;
- verification evidence: verifier acceptance commands or an honest substitute
  result that explicitly references the candidate.

Non-code planning or verification tasks may be marked `completed` when their
acceptance command or documented artifact exists. They should not create a
normal `merged:<task_id>` checkpoint unless they produce an accepted commit.

If required evidence is missing, the task is simulated, blocked, or rejected.
It must not create a normal `merged:<task_id>` checkpoint.

### 6.5 Coverage Split

AgentRunway should write two coverage views:

- `spec_ref_coverage`: which spec sections are referenced by tasks;
- `implementation_evidence_coverage`: which tasks have accepted worker,
  review, verification, and merge evidence.

The existing `coverage.json` may remain as a compatibility summary, but
operator output should make clear which coverage type is being displayed.

### 6.6 Trust-Ready Event Stream

AgentRunway should emit first-class events for every trust boundary:

```text
agentrunway.run_started
agentrunway.contract_created
agentrunway.preflight_failed
agentrunway.worker_dispatched
agentrunway.worker_result
agentrunway.worker_rejected
agentrunway.review_result
agentrunway.verification_result
agentrunway.gate_retry
agentrunway.quality_decision
agentrunway.candidate_ranked
agentrunway.merge_ready
agentrunway.merge_applied
agentrunway.simulation_result
agentrunway.run_blocked
agentrunway.run_finished
```

AgentLens emission remains best-effort. Local state and `events.jsonl` are
authoritative when AgentLens is disabled.

## 7. Operator Output

`status`, `summarize`, `inspect`, and `events` should expose these fields:

- canonical spec ref coverage and unresolved ref diagnostics;
- whether the run is real or simulated;
- task counts separated by real and simulated states;
- implementation evidence coverage;
- AgentLens observability state;
- preflight failure decision packet path;
- next safe operator action.

The operator should not need to infer from empty `changed_files`, `commit=null`,
or `commands_run=[]` that a run was simulated.

## 8. Error Handling

- Unknown spec ref: stop before dispatch with canonicalization suggestions.
- Ref alias resolves but section text is empty: block contract creation. This
  prevents a lint-pass packet-empty run.
- Plan lint failure: persist minimal durable state and mark the run blocked.
- Fake adapter success: mark simulated status and refuse normal apply.
- Missing merge evidence: block normal merge and emit `worker_rejected` or
  `run_blocked` with a concrete evidence code.
- AgentLens unavailable: continue local execution, emit local degraded
  observability evidence, and let future AgentLens import or projection report
  the gap.

## 9. Testing Strategy

### 9.1 Spec Reference Tests

- `6.3`, `S6.3`, and `S1.6.3` resolve to the same canonical id.
- Lint, contract, packet generation, and coverage use the same canonical ids.
- Unknown refs produce actionable suggestions.
- Packet spec slices are non-empty for valid refs.

### 9.2 Preflight Failure Tests

- Plan-lint failure writes `run.json`, `state.sqlite`, `events.jsonl`, and a
  decision packet.
- `status`, `summarize`, `inspect`, and `events` work for preflight failures.

### 9.3 Simulation Tests

- `--adapter local --fake-success` reports simulated run and task statuses.
- Simulated runs do not produce normal merged checkpoints.
- `apply` refuses simulated runs unless an explicit future override is added.
- Fake worker results do not claim TDD red/green success.

### 9.4 Merge Evidence Tests

- A real worker candidate with commit, changed files, and passing verifier can
  be merged.
- Empty worker evidence cannot produce normal `merged`.
- Implementation evidence coverage distinguishes missing worker, review,
  verification, and merge evidence.

### 9.5 Event Tests

- Preflight, worker, review, verification, merge, simulation, blocked, and
  finished events are present in `events.jsonl`.
- AgentLens disabled state is recorded without blocking local execution.

## 10. Acceptance Criteria

- One shared resolver canonicalizes `6.3`, `S6.3`, and `S1.6.3` before all
  downstream use.
- Valid spec refs produce task packets with non-empty spec text.
- Plan-lint failures are fully inspectable through normal AgentRunway commands.
- Local fake-success runs are labelled as simulated, not normal finished runs.
- Normal `merged` requires accepted implementation evidence.
- Operator summaries separate spec-reference coverage from implementation
  evidence coverage.
- `events.jsonl` contains trust-ready `agentrunway.*` events for preflight,
  worker, review, verification, merge, simulation, blocked, and finish
  boundaries.
- AgentLens disabled state is represented as degraded observability evidence.

## 11. Rollout Plan

1. Add the canonical spec ref resolver and migrate lint, contract, coverage,
   and runner packet slicing to use it.
2. Add tests proving packets contain real spec text for numeric and `S...`
   aliases.
3. Persist minimal durable state for preflight and plan-lint failures.
4. Split fake adapter results into simulated statuses and block normal apply.
5. Add evidence gates before normal task merge and checkpoint creation.
6. Split coverage into spec-reference and implementation-evidence views.
7. Expand local event emission with trust-ready `agentrunway.*` boundaries.
8. Re-run the AgentLens AgentRunway Trust Console plan through AgentRunway and
   verify that failures, simulations, and real work are distinguishable.

## 12. References

- `skills/agent-runway/scripts/agentrunway/plan_lint.py`
- `skills/agent-runway/scripts/agentrunway/contract.py`
- `skills/agent-runway/scripts/agentrunway/runner.py`
- `skills/agent-runway/scripts/agentrunway/adapters/local.py`
- `skills/agent-runway/scripts/agentrunway/events.py`
- `docs/superpowers/plans/2026-05-21-agentlens-agentrunway-trust-console.md`
