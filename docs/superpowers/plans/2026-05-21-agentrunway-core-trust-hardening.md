# Implementation Plan: AgentRunway Core Trust Hardening

> **For implementer:** REQUIRED SUB-SKILLS: Use `superpowers:executing-plans` to execute this plan step-by-step and `superpowers:test-driven-development` before changing behavior.
> **For AgentRunway:** This plan is intentionally serial. The shared runner/status files are high-coordination surfaces, so tasks must execute in dependency order.

**Goal:** Harden AgentRunway so plan lint, dry runs, worker results, merge decisions, coverage, and AgentLens events tell the truth before the Trust Console work starts.

**Spec:** `docs/superpowers/specs/2026-05-21-agentrunway-core-trust-hardening-design.md`

**Context:** The comparison run showed that KWS Codex Plan Executor can parse the generic plan text but loses AgentRunway metadata, while AgentRunway has the right architecture but currently has trust gaps in spec reference resolution, preflight artifacts, fake-success semantics, merge evidence, coverage, and event fidelity.

**Non-Goals:**

- Do not implement the Trust Console UI in this plan.
- Do not reintroduce the old CPE/CME split.
- Do not make AgentLens required for local execution; degraded/no-sink mode must remain explicit.

**Execution Notes:**

- Keep every behavior change test-first.
- Prefer small pure helpers over widening `runner.py` conditionals.
- Preserve existing command names and JSON keys where possible; add new keys rather than silently changing old meanings.
- After code changes, run `graphify update .` per repo instructions.

## Task 0: Establish Baseline And Guard Rails

```yaml agentrunway-task
task_id: AR-TRUST-00
title: Establish baseline and guard rails
risk: low
phase: verification
dependencies: []
spec_refs: [S1.2, S1.9, S1.10]
file_claims:
  - {path: docs/superpowers/specs/2026-05-21-agentrunway-core-trust-hardening-design.md, mode: read_only}
  - {path: docs/superpowers/plans/2026-05-21-agentrunway-core-trust-hardening.md, mode: read_only}
acceptance_commands:
  - git status --short
  - python3 skills/agent-runway/scripts/agentrunway.py lint-plan --plan docs/superpowers/plans/2026-05-21-agentrunway-core-trust-hardening.md --spec docs/superpowers/specs/2026-05-21-agentrunway-core-trust-hardening-design.md --json
```

### Steps

1. Confirm the worktree is clean or contains only user-approved changes.
2. Run plan lint against this plan and the approved hardening spec.
3. Record the current expected failure modes from the old Trust Console comparison:

   ```bash
   python3 skills/agent-runway/scripts/agentrunway.py lint-plan \
     --plan docs/superpowers/plans/2026-05-21-agentlens-agentrunway-trust-console.md \
     --spec docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md \
     --json
   ```

4. Do not fix anything in this task. This task exists to make sure the executor starts from the documented state.

### Acceptance Criteria

- The new hardening plan lints.
- The baseline Trust Console command still demonstrates why spec reference handling must be fixed, or the executor records that it has already been fixed by a newer change.

## Task 1: Add A Canonical Spec Reference Resolver

```yaml agentrunway-task
task_id: AR-TRUST-01
title: Add canonical spec reference resolver
risk: medium
phase: implementation
dependencies: [AR-TRUST-00]
spec_refs: [S1.6.1, S1.8, S1.9.1, S1.10]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/spec_refs.py, mode: owned}
  - {path: skills/agent-runway/evals/test_spec_refs.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/plan_parser.py, mode: read_only}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_spec_refs.py -v
```

### Steps

1. Write failing tests first in `skills/agent-runway/evals/test_spec_refs.py`.

   Required cases:

   ```python
   def test_resolves_canonical_and_alias_refs(spec_path):
       resolver = SpecRefResolver.from_spec(spec_path)

       assert resolver.resolve_one("S1.6.3").canonical_ref == "S1.6.3"
       assert resolver.resolve_one("S6.3").canonical_ref == "S1.6.3"
       assert resolver.resolve_one("6.3").canonical_ref == "S1.6.3"
   ```

   ```python
   def test_unresolved_refs_include_suggestions(spec_path):
       resolver = SpecRefResolver.from_spec(spec_path)

       result = resolver.resolve_one("6.30")

       assert result.status == "unresolved"
       assert result.input_ref == "6.30"
       assert result.suggestion is not None
   ```

2. Add `skills/agent-runway/scripts/agentrunway/spec_refs.py` with a pure resolver.

   Target shape:

   ```python
   @dataclass(frozen=True)
   class SpecRefResolution:
       input_ref: str
       canonical_ref: str | None
       status: Literal["resolved", "unresolved"]
       title: str | None = None
       text: str = ""
       suggestion: str | None = None
   ```

   ```python
   class SpecRefResolver:
       @classmethod
       def from_spec(cls, spec_path: Path) -> "SpecRefResolver":
           manifest = parse_spec_manifest(spec_path)
           return cls(manifest.sections)
   ```

3. Build aliases from the manifest sections, not from ad hoc regex alone.

   Required aliases:

   - `S1.6.3` resolves to `S1.6.3`.
   - `S6.3` resolves to `S1.6.3` when the manifest has root-wrapper IDs.
   - `6.3` resolves to `S1.6.3`.
   - Heading-number IDs such as `S10.3` remain supported.

4. Return structured unresolved results rather than throwing from the resolver. Callers decide whether unresolved refs are lint errors.

### Acceptance Criteria

- `evals/test_spec_refs.py` passes.
- The resolver preserves both `input_ref` and `canonical_ref`.
- The resolver can provide title and text for the canonical section.

## Task 2: Wire Canonical Refs Through Lint, Contract, And Packets

```yaml agentrunway-task
task_id: AR-TRUST-02
title: Wire canonical refs through lint contract and packet slices
risk: high
phase: implementation
dependencies: [AR-TRUST-01]
spec_refs: [S1.6.1, S1.7, S1.8, S1.9.1, S1.10]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/plan_lint.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/contract.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_plan_lint.py, mode: owned}
  - {path: skills/agent-runway/evals/test_contract_preflight.py, mode: owned}
  - {path: skills/agent-runway/evals/test_packetizer.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_spec_refs.py evals/test_plan_lint.py evals/test_contract_preflight.py evals/test_packetizer.py -v
```

### Steps

1. Extend `evals/test_plan_lint.py` before implementation.

   Add a case that uses bare numeric refs:

   ```python
   def test_bare_numbered_spec_refs_resolve(plan_path, spec_path):
       # A task with spec_refs: [6.3] should resolve against S1.6.3.
       errors = lint_plan(plan_path, spec_path)
       assert not [e for e in errors if e.code == "unresolved_spec_ref"]
   ```

2. Extend `evals/test_contract_preflight.py`.

   Required assertion:

   ```python
   assert contract.tasks[0].spec_refs == ["S1.6.3"]
   assert contract.coverage["covered"] == ["S1.6.3"]
   ```

3. Extend packet or runner slice coverage so the worker packet uses non-empty spec text when the plan says `6.3` or `S6.3`.

   Required assertion:

   ```python
   packet = packets[0]
   assert packet.spec_refs[0]["id"] == "S1.6.3"
   assert packet.spec_refs[0]["text"].strip()
   assert packet.spec_refs[0]["input_ref"] in {"6.3", "S6.3"}
   ```

4. Replace duplicated alias logic in `plan_lint.py` and `contract.py` with `SpecRefResolver`.

5. Canonicalize task refs before constructing `RunContract`, packet spec slices, and coverage summaries.

   Keep original user input visible in packet metadata by adding `input_ref` alongside canonical `id`.

6. Keep unresolved lint messages operator-friendly:

   ```text
   unresolved_spec_ref task=TASK_ID ref=6.30 suggestion=S1.6.3
   ```

### Acceptance Criteria

- Bare refs, shorthand refs, and canonical refs produce the same canonical ID.
- Contract coverage uses canonical IDs only.
- Worker packets include non-empty spec text.
- No old test that used `S10.3` or `S12` regresses.

## Task 3: Persist Durable Preflight Failure State

```yaml agentrunway-task
task_id: AR-TRUST-03
title: Persist durable preflight failure state
risk: high
phase: implementation
dependencies: [AR-TRUST-02]
spec_refs: [S1.6.2, S1.7, S1.8, S1.9.2, S1.10]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/events.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/run_summary.py, mode: owned}
  - {path: skills/agent-runway/evals/test_preflight_failure_state.py, mode: owned}
  - {path: skills/agent-runway/evals/test_lifecycle_cli.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_preflight_failure_state.py evals/test_lifecycle_cli.py -v
```

### Steps

1. Add failing coverage for lint failure durability.

   Test intent:

   ```python
   def test_lint_failure_writes_state_db_and_events(tmp_path):
       payload = run_agentrunway_with_invalid_plan(tmp_path)

       assert payload["status"] == "plan_lint_failed"
       assert payload["state_db"]
       assert Path(payload["state_db"]).exists()
       assert payload["artifacts"]["decision_packet"]
       assert events_cli(payload["run_id"]).returncode == 0
   ```

2. Add equivalent coverage for post-lint preflight failures.

3. Introduce a small helper rather than duplicating early-failure setup in multiple branches.

   Target behavior:

   - Create `state.sqlite`.
   - Persist a run row with failed status.
   - Persist a decision packet with machine-readable issues.
   - Record `agentrunway.preflight_failed` or `agentrunway.plan_lint_failed`.
   - Include `state_db`, `events_jsonl`, and decision packet paths in `run.json`.

4. Make `events` and `inspect` commands tolerate early-failure runs without reconstructing incomplete state.

5. Ensure early failure output distinguishes:

   - `plan_lint_failed`
   - `preflight_failed`
   - `blocked`
   - `failed`

### Acceptance Criteria

- Every run ID has a durable run directory and a durable `state.sqlite`.
- `agentrunway events <run-id>` works after lint failure.
- `agentrunway inspect <run-id>` shows the failure reason without crashing.

## Task 4: Separate Simulation From Real Success

```yaml agentrunway-task
task_id: AR-TRUST-04
title: Separate simulated local adapter outcomes from real success
risk: high
phase: implementation
dependencies: [AR-TRUST-03]
spec_refs: [S1.6.3, S1.7, S1.8, S1.9.3, S1.10]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/models.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/adapters/local.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/status.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/run_summary.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/durable_projection.py, mode: owned}
  - {path: skills/agent-runway/evals/test_adapters.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_fake_e2e.py, mode: owned}
  - {path: skills/agent-runway/evals/test_status_watchdog_cost.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_adapters.py evals/test_runner_fake_e2e.py evals/test_status_watchdog_cost.py -v
```

### Steps

1. Update adapter tests first so `LocalAdapter(fake_success=True)` no longer returns `status="success"`.

   Required assertion:

   ```python
   assert result.status == "simulated_success"
   assert result.method_audit["simulation"] is True
   assert result.changed_files == []
   assert result.commit is None
   ```

2. Add explicit statuses where they are modeled.

   Suggested values:

   - Worker result: `simulated_success`
   - Task status: `simulated_completed`
   - Run status: `simulated_finished`

3. Update local fake execution in `runner.py`:

   - Do not create merge checkpoints with `reason="merged:<task_id>"`.
   - Do not set task status to `merged`.
   - Do not enqueue or apply merge candidates.
   - Emit a simulation event.

4. Update status and summary output so operators see simulation clearly:

   ```json
   {
     "status": "simulated_finished",
     "simulation": true,
     "next_operator_action": "run without --fake-success before applying artifacts"
   }
   ```

5. Keep non-fake local execution behavior unchanged unless a test proves it was relying on fake-success semantics.

### Acceptance Criteria

- `--fake-success` can never produce `finished` or `merged`.
- Simulated runs are visibly successful simulations, not real implementation runs.
- Existing status/watchdog output remains parseable.

## Task 5: Add Evidence-Based Merge Gate

```yaml agentrunway-task
task_id: AR-TRUST-05
title: Add evidence-based merge gate
risk: high
phase: implementation
dependencies: [AR-TRUST-04]
spec_refs: [S1.6.4, S1.8, S1.9.4, S1.10]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/evidence.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/integration_manager.py, mode: owned}
  - {path: skills/agent-runway/evals/test_merge_evidence.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_merge_evidence.py evals/test_runner_production_e2e.py -v
```

### Steps

1. Add tests for merge denial before writing the gate.

   Required denial cases:

   - Candidate has no commit.
   - Candidate has no changed files for an implementation task.
   - Acceptance commands did not run or did not pass.
   - Review did not approve.
   - Verification did not approve.
   - Result is simulated.

2. Add `skills/agent-runway/scripts/agentrunway/evidence.py`.

   Suggested public function:

   ```python
   def validate_merge_evidence(
       *,
       task: PlanTask,
       candidate: MergeCandidate,
       worker_result: WorkerResult | None,
       review_status: str | None,
       verification_status: str | None,
   ) -> EvidenceDecision:
       ...
   ```

3. Use the gate immediately before every merge path:

   - Initial production run merge path.
   - Resume merge path.
   - Any direct `apply` path that can materialize a selected candidate.

4. Persist denials as structured evidence:

   ```json
   {
     "event": "agentrunway.merge_blocked",
     "task_id": "AR-TRUST-05",
     "reasons": ["missing_commit", "verification_not_passed"]
   }
   ```

5. Do not make fake-success pass the gate. Simulation should stop before the merge gate, but the gate must still reject it if reached.

### Acceptance Criteria

- A task reaches `merged` only after implementation, review, and verification evidence exists.
- Merge-blocked reasons are visible in events and summary output.
- Production e2e tests still pass with real candidate evidence.

## Task 6: Split Spec Coverage From Implementation Evidence Coverage

```yaml agentrunway-task
task_id: AR-TRUST-06
title: Split spec coverage from implementation evidence coverage
risk: medium
phase: implementation
dependencies: [AR-TRUST-05]
spec_refs: [S1.6.5, S1.7, S1.9.4, S1.10]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/artifact_graph.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/status.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/run_summary.py, mode: owned}
  - {path: skills/agent-runway/evals/test_artifact_graph_status.py, mode: owned}
  - {path: skills/agent-runway/evals/test_evidence_coverage.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_artifact_graph_status.py evals/test_evidence_coverage.py -v
```

### Steps

1. Add tests that distinguish planning coverage from implementation evidence.

   Required state:

   - A task references `S1.6.4`.
   - The task is only `planned` or `simulated_completed`.
   - Spec coverage marks the ref as planned/covered-by-plan.
   - Implementation evidence coverage does not mark the ref as implemented.

2. Preserve backward compatibility by keeping existing `coverage.json` readable.

   Acceptable options:

   - Add an `implementation_evidence_coverage` key to the existing JSON.
   - Or write `evidence_coverage.json` and reference it from the run summary.

   Prefer additive output over replacing the current structure.

3. Base implementation evidence on task status and merge evidence, not only `contract.coverage`.

   Suggested classification:

   - `planned`: task references the spec ref.
   - `simulated`: only simulated task results exist.
   - `implemented`: task has merge evidence and status `merged`.
   - `blocked`: task failed, blocked, or merge evidence was denied.

4. Update operator summaries to show both views clearly:

   ```text
   Spec refs planned: 12/12
   Spec refs implemented with evidence: 0/12
   ```

### Acceptance Criteria

- A dry run cannot inflate implementation evidence coverage.
- Existing artifact graph consumers can still read the old coverage fields.
- Run summary makes the distinction visible without needing raw JSON inspection.

## Task 7: Expand Trust-Ready AgentRunway Events

```yaml agentrunway-task
task_id: AR-TRUST-07
title: Expand trust-ready AgentRunway events
risk: medium
phase: implementation
dependencies: [AR-TRUST-06]
spec_refs: [S1.6.6, S1.7, S1.8, S1.9.5, S1.10]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/events.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_event_journal_agentlens.py, mode: owned}
  - {path: skills/agent-runway/evals/test_trust_ready_events.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_event_journal_agentlens.py evals/test_trust_ready_events.py -v
```

### Steps

1. Add event tests before implementation.

   Required events:

   - `agentrunway.plan_lint_failed`
   - `agentrunway.preflight_failed`
   - `agentrunway.worker_dispatched`
   - `agentrunway.worker_result`
   - `agentrunway.review_result`
   - `agentrunway.verification_result`
   - `agentrunway.merge_blocked`
   - `agentrunway.merge_applied`
   - `agentrunway.simulation_completed`
   - `agentrunway.run_finished`

2. Extend event payloads without breaking `agentrunway.event.v1`.

   Add optional fields:

   ```json
   {
     "schema": "agentrunway.event.v1",
     "event_name": "agentrunway.merge_blocked",
     "task_id": "AR-TRUST-05",
     "worker_id": "worker-1",
     "spec_refs": ["S1.6.4"],
     "evidence": {
       "status": "blocked",
       "reasons": ["verification_not_passed"]
     }
   }
   ```

3. Emit AgentLens degraded-mode evidence explicitly when no sink is available:

   ```json
   {
     "event_name": "agentrunway.agentlens_sink_unavailable",
     "evidence": {"sink": "disabled", "local_journal": ".../events.jsonl"}
   }
   ```

4. Ensure all new events are written to both local JSONL and SQLite `agentlens_events`.

5. Do not require network or AgentLens service availability in tests.

### Acceptance Criteria

- Event stream can reconstruct why a task is simulated, merged, blocked, or failed.
- AgentLens disabled mode is visible as degraded evidence, not silent success.
- Existing event journal tests still pass.

## Task 8: Final Verification, Graph Update, And Commit

```yaml agentrunway-task
task_id: AR-TRUST-08
title: Final verification graph update and commit
risk: medium
phase: verification
dependencies: [AR-TRUST-07]
spec_refs: [S1.10, S1.11, S1.12]
file_claims: []
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_spec_refs.py evals/test_plan_lint.py evals/test_contract_preflight.py evals/test_packetizer.py evals/test_preflight_failure_state.py evals/test_adapters.py evals/test_runner_fake_e2e.py evals/test_merge_evidence.py evals/test_evidence_coverage.py evals/test_trust_ready_events.py -v
  - python3 skills/agent-runway/scripts/agentrunway.py lint-plan --plan docs/superpowers/plans/2026-05-21-agentlens-agentrunway-trust-console.md --spec docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md --json
  - python3 skills/agent-runway/scripts/agentrunway.py run --plan docs/superpowers/plans/2026-05-21-agentlens-agentrunway-trust-console.md --spec docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md --adapter local --fake-success
  - git diff --check
  - graphify update .
  - git status --short
```

### Steps

1. Run the focused AgentRunway suite listed in the task metadata.
2. Re-run the original Trust Console plan lint. It should now accept the plan's numeric spec refs and report no unresolved spec ref errors.
3. Re-run the original local fake-success Trust Console execution.

   Expected result:

   ```json
   {
     "status": "simulated_finished",
     "simulation": true
   }
   ```

   It must not report `finished` or any task as `merged`.

4. Run `git diff --check`.
5. Run `graphify update .` because this plan changes code files.
6. Inspect `git status --short` and commit only in-scope changes.

### Acceptance Criteria

- All focused tests pass.
- The original AgentRunway comparison failure is fixed.
- Fake-success output is clearly simulated.
- Graphify is updated after code edits.
- The final commit contains only AgentRunway hardening code/tests/docs and generated graph updates caused by those code changes.

## Self-Review Checklist

- [ ] Spec refs are canonicalized once and reused everywhere.
- [ ] Early failures produce durable state and event artifacts.
- [ ] Simulation cannot be mistaken for implementation.
- [ ] Merge requires evidence from implementation, review, and verification.
- [ ] Coverage separates planned spec coverage from implementation evidence.
- [ ] AgentLens unavailable mode is explicit and degraded, not silently successful.
- [ ] Tests prove both the old failure and the new behavior.
