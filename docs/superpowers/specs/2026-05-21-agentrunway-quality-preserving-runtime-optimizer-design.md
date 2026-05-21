# Design: AgentRunway Quality-Preserving Runtime Optimizer

## 1. Summary

AgentRunway should reduce execution latency without weakening its quality
model. The current runtime already has the right safety primitives: durable
projection, safe-wave scheduling, failure barriers, local verification,
review/verification gates, merge evidence validation, and AgentLens trust
events. The next improvement should make those primitives run with less idle
time and less duplicated work.

The target is not "skip review" or "merge faster at any cost." The target is a
runtime that can answer:

```text
Which tasks can safely run now?
Which gates can run concurrently without lowering confidence?
Which evidence is deterministic enough to avoid waiting for an unnecessary
model gate?
Which optimization was applied, and how did it affect the trust trail?
```

The optimizer keeps `DurableProjection` as the source of truth. Tasks outside
the projected `safe_wave` never start. Human-decision barriers, missing
checkpoint repairs, stale activities, repeated rebase failures, merge evidence
validation, and dirty-worktree protections remain mandatory.

## 2. Evidence From Current Runtime

Recent AgentRunway work improved trust and safety, but the runtime still spends
time in avoidable waits:

- `runner.py` pre-starts implementers for a multi-task safe wave, but task
  gates still mostly follow `implement -> review -> verification -> merge`
  inside each task.
- The runner uses a fixed `DEFAULT_MAX_PARALLEL_IMPLEMENTERS = 4` before
  applying runtime caps, even though the effective config supports larger
  Codex and Claude worker caps.
- `candidate_count_for_task()` starts two implementer candidates for high-risk
  tasks, and both candidates can consume expensive downstream gate time before
  the system narrows to the best candidate.
- `_local_first_verification()` can run deterministic acceptance commands and
  populate the gate cache, but it is still entered from the sequential
  verification phase after review.
- `TaskExecutionClass` already separates independent, soft-overlap,
  shared-core, barrier, and blocked-dependent work. That classification can be
  reused to increase concurrency for safe tasks while keeping shared-core work
  conservative.
- AgentLens trust reporting now exposes whether a run should be trusted, but
  the optimized runtime also needs to emit why a fast path was safe.

## 3. Goals

- Preserve every existing quality invariant while reducing idle time.
- Run independent safe-wave work up to a runtime budget derived from runtime
  caps, task risk, lane, and gate type.
- Add an explicit execution lane above `TaskExecutionClass`:
  `fast_lane`, `standard_lane`, and `barrier_lane`.
- Start deterministic local verification as soon as a candidate commit exists
  when the task is eligible.
- Allow review and local acceptance verification to overlap for eligible tasks.
- Use deterministic local acceptance failure as actionable gate evidence,
  allowing retry or block without waiting for a model verifier when the
  failure is clear.
- Reduce high-risk two-candidate waste by adding a candidate ladder: rank from
  lightweight evidence first, then run full quality gates on the chosen
  candidate.
- Emit runtime trace evidence so `summarize`, `inspect`, events, and AgentLens
  trust artifacts show which optimization path was used.

## 4. Non-Goals

- No removal of reviewer or verifier roles from the default quality model.
- No merge without required review, verification, and merge evidence.
- No automatic dispatch outside `DurableProjection.safe_wave`.
- No broader rewrite of AgentRunway into a workflow service.
- No relaxation of shared-core, high-risk, schema/generated-surface, or human
  decision barriers.
- No trust claim based only on model text. Optimized evidence must still be
  runner-recorded and bounded.

## 5. Architecture

The optimizer is a bounded layer inside the existing runner:

```text
DurableProjection
  -> CheckpointScheduler.safe_wave
  -> ExecutionProfile
  -> RuntimeBudget
  -> GatePipeline
  -> CandidateLadder
  -> RuntimeTrace
  -> existing review, verification, merge, summary, and AgentLens events
```

`DurableProjection` remains authoritative. The optimizer can only schedule
tasks and gates that the projection already permits. If projection state
changes, the optimizer must re-read the projection and downgrade the task lane
or stop.

`ExecutionProfile` classifies safe-wave tasks into:

- `fast_lane`: low or medium risk, not shared-core, not broad claim, not
  schema/generated, owned-file work, and has deterministic acceptance commands.
- `standard_lane`: safe to run but still requires the normal serialized gate
  flow because evidence is not strong enough for overlap.
- `barrier_lane`: high-risk, shared-core, broad claim, schema/generated
  surface, serial task, blocked-dependent, or human-decision-adjacent work.

This lane does not replace `TaskExecutionClass`; it composes with it. The
existing classifier still determines whether a task is independent,
soft-overlap, shared-core, barrier, or blocked-dependent. The execution lane
only decides how aggressively the allowed task can use runtime capacity.

## 6. Components

### 6.1 ExecutionProfile

`ExecutionProfile` consumes `TaskSpec`, `TaskExecutionClass`, acceptance
commands, file claims, and risk. It returns a small record:

```json
{
  "task_id": "task_001",
  "lane": "fast_lane",
  "reasons": ["owned_files", "low_or_medium_risk", "deterministic_acceptance"],
  "review_mode": "diff",
  "allow_gate_overlap": true,
  "allow_model_verifier_skip_on_local_failure": true
}
```

The profile must be deterministic and visible in summary output. If any
required signal is missing, the task becomes `standard_lane` or `barrier_lane`.

### 6.2 RuntimeBudget

`RuntimeBudget` replaces the fixed mental model of "up to four implementers"
with a calculated budget:

- read the effective runtime cap for Codex or Claude;
- apply safe-wave size;
- reserve capacity for review and verification gates already in flight;
- force width 1 for barrier-lane tasks;
- keep shared-core and high-risk task gates serial in the first
  implementation;
- expose the final budget and reason in `RuntimeTrace`.

The default can remain conservative for the first implementation. The important
change is that the budget is explicit, inspectable, and testable.

### 6.3 GatePipeline

`GatePipeline` models per-candidate gate work as a small pipeline instead of a
single blocking chain.

For a fast-lane candidate:

1. implementer produces a candidate commit;
2. local acceptance verification starts from the candidate commit;
3. reviewer starts from the same candidate evidence;
4. successful merge requires the accepted review and accepted verification
   evidence;
5. local verification failure with command evidence routes into `GateRunner`
   retry/block policy without waiting for a model verifier;
6. unclear local verification, timeout, mutation, or missing evidence falls
   back to the standard model verifier path.

For standard-lane and barrier-lane candidates, the current gate order remains
the safe default.

### 6.4 CandidateLadder

High-risk tasks can still create multiple candidates, but the optimizer should
avoid full downstream gate work for every candidate. The ladder has two stages:

1. lightweight candidate evidence: changed files, commit presence, claimed
   commands, file-claim compliance, and optional local acceptance signal;
2. full gates only for the selected candidate, unless the first selected
   candidate fails and policy allows retry.

This keeps the current quality bar for the candidate that may merge while
reducing review/verifier time spent on candidates that are unlikely to win.

### 6.5 RuntimeTrace

`RuntimeTrace` records optimization decisions as first-class evidence:

- task lane and reasons;
- computed runtime budget;
- gate overlap enabled or disabled;
- local verification source: local, cache, model, fallback, or skipped;
- whether a model verifier was skipped because local command evidence was
  already actionable;
- candidate ladder stage and selected candidate;
- fallback reason when an optimized path downgrades.

Trace evidence should appear in `summarize`, `inspect --json`, local
`events.jsonl`, and AgentLens v2 event payloads.

## 7. Data Flow

1. Runner reads `DurableProjection`.
2. `CheckpointScheduler` returns `safe_wave`.
3. `ExecutionProfile` classifies each task in the safe wave.
4. `RuntimeBudget` decides how many implementers and gates can run.
5. Implementers start only for tasks in the projected safe wave.
6. When a candidate commit exists, `GatePipeline` decides whether local
   acceptance verification can start immediately.
7. Reviewer starts from candidate evidence according to the task's review mode.
8. If local verification passes, the result can satisfy verification evidence.
   If local verification fails clearly, the result becomes gate failure
   evidence for retry/block policy.
9. If local verification cannot produce trustworthy evidence, the model
   verifier path runs as it does today.
10. `CandidateLadder` avoids full gate work for non-selected high-risk
    candidates where lightweight evidence is enough to rank candidates.
11. Merge remains blocked until merge evidence validation succeeds.
12. `RuntimeTrace` is written before final summary and event projection.

## 8. Error Handling

No optimization path may bypass an existing safety barrier:

- If a task leaves the safe wave, stop or downgrade before starting new work.
- If a task is shared-core, high-risk, serial, broad-claim, schema/generated,
  or blocked-dependent, default to barrier-lane behavior.
- If local verification mutates tracked files, times out, has missing command
  evidence, or fails for infrastructure reasons, it cannot replace model
  verification.
- If review and local verification disagree, the stricter outcome wins and the
  run records the contradiction as trace evidence.
- If a local failure is actionable, route it through `GateRunner`; do not invent
  a separate retry policy.
- If a parallel gate fails after another gate passes, merge remains blocked
  until the failing evidence is resolved.
- If RuntimeTrace cannot be written, continue local safety state but mark
  observability degraded in summary and AgentLens event evidence.

## 9. Trust And Observability

Speed optimizations must be visible to operators and to AgentLens:

- `summarize` should show lane counts, active budget, gate overlap, local
  verification cache hits, and skipped model verifier waits.
- `inspect --json` should expose per-task runtime trace records.
- `events.jsonl` should include bounded `agentrunway.runtime_optimized`
  events.
- AgentLens trust projection should distinguish local deterministic evidence,
  cached evidence, model verifier evidence, and fallback evidence.
- Trust report strength should not silently increase because a fast path was
  used. The trust layer should treat fast-path evidence as strong only when it
  is deterministic, bounded, and tied to the candidate commit.

## 10. Testing Strategy

### 10.1 Execution Profile Tests

- Low/medium owned-file tasks with acceptance commands become `fast_lane`.
- Shared-core, high-risk, broad-claim, schema/generated, serial, or
  blocked-dependent tasks become `barrier_lane`.
- Tasks without deterministic acceptance commands become `standard_lane`.

### 10.2 Runtime Budget Tests

- Runtime caps are respected.
- Barrier-lane tasks force width 1.
- Safe-wave independent tasks can use wider concurrency.
- Gate capacity is included in budget diagnostics.

### 10.3 Gate Pipeline Tests

- Fast-lane candidates start local verification and review without unnecessary
  sequential wait.
- Local verification pass records verification evidence tied to the candidate
  commit.
- Local verification failure with command evidence triggers existing
  `GateRunner` retry/block behavior.
- Timeout, mutation, or ambiguous local failure falls back to model verifier.

### 10.4 Candidate Ladder Tests

- High-risk two-candidate tasks rank lightweight evidence before full gates.
- Only the selected candidate must pass full review, verification, and merge
  evidence before merge.
- If the selected candidate fails and policy allows retry, the next candidate
  can enter full gates with trace evidence.

### 10.5 Trust And Trace Tests

- `summarize` and `inspect --json` expose runtime trace.
- AgentRunway emits bounded runtime optimization events.
- AgentLens projection can distinguish local, cached, model, fallback, and
  skipped-wait gate sources.
- Trust report remains degraded or partial when optimized evidence is missing
  or ambiguous.

## 11. Acceptance Criteria

- Independent fast-lane tasks reduce avoidable gate wait without dispatching
  outside `safe_wave`.
- Shared-core and high-risk work remain conservative by default.
- Deterministic acceptance failure can trigger retry/block without waiting for
  a model verifier.
- A fast-path success still records review, verification, merge, and runtime
  trace evidence.
- High-risk multi-candidate work avoids full gates for non-selected candidates
  unless policy needs them.
- `summarize`, `inspect`, local events, and AgentLens trust artifacts expose
  optimization decisions.
- Existing AgentRunway evals pass.
- The implementation plan validates with:

```bash
python3 skills/agent-runway/scripts/agentrunway.py lint-plan --plan docs/superpowers/plans/2026-05-21-agentrunway-quality-preserving-runtime-optimizer.md --spec docs/superpowers/specs/2026-05-21-agentrunway-quality-preserving-runtime-optimizer-design.md --json
```

## 12. Rollout Plan

1. Add deterministic `ExecutionProfile` and focused tests.
2. Add explicit `RuntimeBudget` diagnostics while keeping conservative
   defaults.
3. Add `RuntimeTrace` storage and summary/inspect exposure.
4. Introduce local verification overlap for fast-lane candidates.
5. Route actionable local verification failure through existing `GateRunner`.
6. Add candidate ladder ranking for high-risk multi-candidate tasks.
7. Emit bounded runtime optimization events for AgentLens.
8. Run focused tests, full AgentRunway evals, py_compile, diff check, plan
   lint, and `graphify update .` after code changes.

## 13. References

- `docs/superpowers/specs/2026-05-21-agentrunway-hybrid-scheduler-failure-recovery-design.md`
- `docs/superpowers/specs/2026-05-21-agentrunway-core-trust-hardening-design.md`
- `docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md`
- `skills/agent-runway/scripts/agentrunway/runner.py`
- `skills/agent-runway/scripts/agentrunway/durable_projection.py`
- `skills/agent-runway/scripts/agentrunway/checkpoint_scheduler.py`
- `skills/agent-runway/scripts/agentrunway/task_classifier.py`
- `skills/agent-runway/scripts/agentrunway/quality_policy.py`
- `skills/agent-runway/scripts/agentrunway/gate_runner.py`
- `AgentLens/src/agentlens/evaluator/trust.py`
