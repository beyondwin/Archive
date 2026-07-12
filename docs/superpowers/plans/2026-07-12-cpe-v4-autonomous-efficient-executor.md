# CPE 4.0 Autonomous Efficient Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CPE 3.1 with a clean-cut CPE 4.0 executor that preserves one lossless task contract across roles, checkpoints every verified task, caps same-root repair, runs with standing autonomy, and performs one final 5.6-only quality comparison.

**Architecture:** A lossless compiler produces content-addressed `TaskContractV4` inputs. A v4 event kernel drives candidate commits through disposable acceptance, scoped review, deterministic verification, and verified checkpoints; a supervisor resumes transient waits and records autonomous decisions. Final evidence compares production-faithful CPE 3.1 and CPE 4.0 prompt bundles on the same Sol 5.6 model while Terra remains a bounded read-only scout.

**Tech Stack:** Python 3 standard library, Git CLI/worktrees, JSON/JSONL, Codex CLI/App Server, Bash, Bun checks, Graphify.

## Global Constraints

- Source spec: `docs/superpowers/specs/2026-07-12-cpe-v4-autonomous-efficient-executor-design.md`.
- Implement Tasks 1-9 through normal Codex plan execution, not CPE 3.x. CPE 4.0 first executes itself in Task 9 deterministic E2E and Task 10 dogfood.
- Existing v3 runs are unsupported. Do not migrate, repair, resume, rewrite, or delete their external artifacts.
- Active routes are exactly `gpt-5.6-sol/high` for core work and `gpt-5.6-terra/high` for bounded read-only scouting.
- No fallback model, reasoning downgrade, legacy treatment, API-key billing, credit purchase, account-setting change, remote push, or protected-branch merge.
- Tasks 1-9 make no credentialed quality calls. Task 10 uses one immutable manifest with exactly 17 credentialed calls and seven deterministic policy outcomes.
- Docs, Graphify, baseline, version, and release-only changes never rerun Task 10 provider calls.
- Raw transcripts, credentials, absolute home paths, and hidden-oracle paths stay outside tracked or sanitized evidence.
- Same-root semantic repair is capped at two; generic non-blocking hardening becomes backlog.
- Use `apply_patch` for hand edits and stage exact task files only.
- Task 9 freezes one 40-hex code checkpoint. Task 11 is cost-free closeout bound to Task 10 evidence.
- Every test helper named in a snippet is defined in that named check file; snippets do not depend on undeclared shared test state.

## File Structure

- `scripts/cpe_runtime/task_contracts.py`: exact task source and canonical contract.
- `scripts/cpe_runtime/checkpoints.py`: candidate and verified Git checkpoints.
- `scripts/cpe_runtime/verification_workspace.py`: disposable acceptance worktrees.
- `scripts/cpe_runtime/command_evidence.py`: command/file-change normalization and RED/GREEN evidence.
- `scripts/cpe_runtime/autonomy.py`: standing-autonomy decisions and user-authority gates.
- `scripts/cpe_runtime/failure_policy.py`: failure classes, repair counters, blocker/backlog routing.
- `scripts/cpe_runtime/supervisor.py`: transient resume and deduplicated notifications.
- `scripts/cpe_runtime/prompt_bundles.py`: production-faithful control/candidate inputs.
- `scripts/cpe_runtime/runtime_upgrade.py`: v4-to-v4 runtime upgrade evidence.
- `evals/check_*_v4.py`: focused production-backed v4 checks.

---

### Task 1: Compile One Lossless TaskContractV4 Per Task

```yaml
task_type: tdd_implementation
dependencies: []
spec_refs: ["S1.6", "S1.17.1"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/parse_plan.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/task_contracts.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/plan_compiler.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/packets.py
  - skills/kws-codex-plan-executor/templates/task-contract-schema.json
  - skills/kws-codex-plan-executor/evals/parser-fixtures/20-v4-lossless-plan.md
  - skills/kws-codex-plan-executor/evals/check_task_contract_v4.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_task_contract_v4.py
operator_reviewed: true
```

**Files:** Create `scripts/cpe_runtime/task_contracts.py`, `templates/task-contract-schema.json`, `evals/parser-fixtures/20-v4-lossless-plan.md`, and `evals/check_task_contract_v4.py`; modify `scripts/parse_plan.py`, `scripts/cpe_runtime/plan_compiler.py`, and `scripts/cpe_runtime/packets.py`.

**Interfaces:** Produces `TaskContractV4`, `TaskType`, `TaskContractV4.body() -> dict[str, object]`, `canonical_contract_bytes()`, and `compile_task_contract()`. Every role consumes the same `contract_sha256`.

- [ ] **Step 1: Write the failing fixture and check**

The fixture contains a local YAML metadata block, interface prose, fenced RED test, fenced GREEN command, and acceptance. Assert:

```python
contract = compile_fixture("20-v4-lossless-plan.md")
assert contract.schema_version == "cpe.task-contract.v4"
assert contract.task_type == "tdd_implementation"
assert "def test_lossless_contract():" in contract.task_source
assert "python3 -m unittest" in contract.task_source
assert contract.acceptance_commands == ("python3 check_contract.py",)
assert contract.task_source_sha256 == sha256_bytes(contract.task_source.encode())
assert contract.contract_sha256 == sha256_bytes(canonical_contract_bytes(contract.body()))
```

- [ ] **Step 2: Run RED**

Run `python3 skills/kws-codex-plan-executor/evals/check_task_contract_v4.py`.

Expected: `ModuleNotFoundError: No module named 'cpe_runtime.task_contracts'`.

- [ ] **Step 3: Implement the immutable contract**

```python
TaskType = Literal["tdd_implementation", "non_tdd_implementation", "documentation", "verification", "external_effect", "release_closeout"]

@dataclass(frozen=True)
class TaskContractV4:
    schema_version: str
    task_id: str
    title: str
    task_type: TaskType
    risk_class: str
    dependencies: tuple[str, ...]
    task_source: str
    task_source_sha256: str
    spec_sections: tuple[dict[str, str], ...]
    file_claims: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    acceptance_commands: tuple[str, ...]
    required_methods: tuple[str, ...]
    required_evidence: tuple[str, ...]
    checkpoint_message: str
    source_hashes: dict[str, object]
    contract_sha256: str
```

`parse_plan.py` uses visible Markdown only to discover headings. It stores the exact raw bytes from each task heading through the byte before the next heading as `task_source`.

- [ ] **Step 4: Put the same contract in every packet**

```python
payload = {
    "schema_version": "cpe.task-packet.v4",
    "task_id": contract.task_id,
    "task_contract": contract.body(),
    "task_contract_sha256": contract.contract_sha256,
    "role_policy": PACKET_ROLE_POLICY,
}
```

Reject canonical-byte, source, contract, spec, and role-visible digest mismatch.

- [ ] **Step 5: Run GREEN**

```bash
python3 skills/kws-codex-plan-executor/evals/check_task_contract_v4.py
python3 skills/kws-codex-plan-executor/evals/check_parse_plan.py
python3 skills/kws-codex-plan-executor/evals/check_task_packet.py
```

Expected: all pass with `lossless_source=true` and `role_digest_parity=true`.

- [ ] **Step 6: Commit**

```bash
git add -- skills/kws-codex-plan-executor/scripts/parse_plan.py skills/kws-codex-plan-executor/scripts/cpe_runtime/{task_contracts,plan_compiler,packets}.py skills/kws-codex-plan-executor/templates/task-contract-schema.json skills/kws-codex-plan-executor/evals/parser-fixtures/20-v4-lossless-plan.md skills/kws-codex-plan-executor/evals/check_task_contract_v4.py
git commit -m "feat(cpe): compile lossless v4 task contracts"
```

### Task 2: Cut State, Manifest, And Events Over To Schema V4

```yaml
task_type: tdd_implementation
dependencies: ["task_1"]
spec_refs: ["S1.4", "S1.11", "S1.16", "S1.17.2"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/events.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/runtime_upgrade.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py
  - skills/kws-codex-plan-executor/evals/check_v4_state_contract.py
  - skills/kws-codex-plan-executor/evals/check_event_kernel.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_v4_state_contract.py
operator_reviewed: true
```

**Files:** Create `scripts/cpe_runtime/runtime_upgrade.py` and `evals/check_v4_state_contract.py`; modify `events.py`, `manifest.py`, `projector.py`, `kernel.py`, `validation.py`, and `evals/check_event_kernel.py`.

**Interfaces:** Produces schema `4`, `unsupported_run_schema`, v4-only event types, `RuntimeIdentity`, and `validate_runtime_upgrade()`.

- [ ] **Step 1: Write failing schema tests**

```python
manifest = create_v4_manifest(task_contracts=[fixture_contract()])
assert manifest["schema_version"] == "4"
state = project(manifest, [])
assert state["attempt_budget"] == {"limit": 40, "used": 0}
with assert_raises_text(ValueError, "unsupported_run_schema"):
    load_manifest(write_manifest_fixture({"schema_version": "3"}))
```

Also reject the old `attempt.recorded` alias and accept a valid `runtime.upgraded` event.

- [ ] **Step 2: Run RED**

Run `python3 skills/kws-codex-plan-executor/evals/check_v4_state_contract.py`.

Expected: schema remains `3` and the check fails.

- [ ] **Step 3: Install one v4 event set**

```python
EVENT_TYPES = frozenset({"run.status_changed", "task.status_changed", "attempt.started", "attempt.completed", "verdict.recorded", "evidence.attached", "candidate.checkpoint_recorded", "task.checkpoint_verified", "blocker.opened", "blocker.resolved", "decision.recorded", "notification.requested", "runtime.upgraded", "completion.recorded"})
```

Remove v3 read aliases. Schema checks run before any other manifest/state access.

- [ ] **Step 4: Add v4 projection and runtime identity**

Initial state contains `runtime`, `candidate_checkpoints`, `verified_checkpoints`, `checkpoint_head`, `decisions`, `backlog`, `repair_roots`, `wait_reason`, and `attempt_budget`. Runtime upgrade requires compatibility epoch `cpe-v4`, a clean tree, and a verified checkpoint.

- [ ] **Step 5: Run GREEN**

```bash
python3 skills/kws-codex-plan-executor/evals/check_v4_state_contract.py
python3 skills/kws-codex-plan-executor/evals/check_event_kernel.py
python3 -m py_compile skills/kws-codex-plan-executor/scripts/cpe_runtime/{events,manifest,projector,kernel,runtime_upgrade,validation}.py
```

- [ ] **Step 6: Commit**

```bash
git add -- skills/kws-codex-plan-executor/scripts/cpe_runtime/{events,manifest,projector,kernel,runtime_upgrade,validation}.py skills/kws-codex-plan-executor/evals/{check_v4_state_contract,check_event_kernel}.py
git commit -m "feat(cpe): cut runtime state over to v4"
```

### Task 3: Add Candidate Commits And Disposable Acceptance Worktrees

```yaml
task_type: tdd_implementation
dependencies: ["task_2"]
spec_refs: ["S1.8", "S1.17.2"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/checkpoints.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/verification_workspace.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/git_delta.py
  - skills/kws-codex-plan-executor/evals/check_checkpoint_lifecycle_v4.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_checkpoint_lifecycle_v4.py
operator_reviewed: true
```

**Files:** Create `checkpoints.py`, `verification_workspace.py`, and `check_checkpoint_lifecycle_v4.py`; modify `git_delta.py`.

**Interfaces:** Produces `CandidateCheckpoint`, `VerifiedCheckpoint`, `create_candidate_checkpoint()`, `promote_verified_checkpoint()`, `verification_worktree()`, and `run_acceptance()`.

- [ ] **Step 1: Write failing checkpoint isolation tests**

```python
candidate = create_candidate_checkpoint(kernel, contract, product_worktree)
assert re.fullmatch(r"[0-9a-f]{40}", candidate.commit)
with verification_worktree(repo, candidate.commit, run_dir, contract.task_id) as root:
    results = run_acceptance(("python3 build.py",), root, os.environ)
assert results[0].exit_code == 0
assert not (product_worktree / "dist").exists()
verified = promote_verified_checkpoint(kernel, contract, candidate, results)
assert verified.predecessor == source_head
```

Reject out-of-claim candidates, dirty product trees, non-direct children, and cleanup failure.

- [ ] **Step 2: Run RED**

Run `python3 skills/kws-codex-plan-executor/evals/check_checkpoint_lifecycle_v4.py`.

Expected: `cpe_runtime.checkpoints` is missing.

- [ ] **Step 3: Implement checkpoint types**

```python
@dataclass(frozen=True)
class CandidateCheckpoint:
    task_id: str
    predecessor: str
    commit: str
    tree: str
    patch_sha256: str
    changed_files: tuple[str, ...]

@dataclass(frozen=True)
class VerifiedCheckpoint:
    task_id: str
    predecessor: str
    commit: str
    tree: str
    contract_sha256: str
    acceptance_sha256: str
    review_sha256: str
```

Stage only contract claims, use deterministic CPE Git identity, and require a clean tree after commit.

- [ ] **Step 4: Implement disposable acceptance**

Add a detached worktree under the run directory, run commands with bounded environment, store sanitized output digests, and remove the worktree in `finally`. Cleanup failure is `evidence_integrity_failure`.

- [ ] **Step 5: Run GREEN and commit**

```bash
python3 skills/kws-codex-plan-executor/evals/check_checkpoint_lifecycle_v4.py
python3 skills/kws-codex-plan-executor/evals/check_run_diffs.py
git diff --check
git add -- skills/kws-codex-plan-executor/scripts/cpe_runtime/{checkpoints,verification_workspace,git_delta}.py skills/kws-codex-plan-executor/evals/check_checkpoint_lifecycle_v4.py
git commit -m "feat(cpe): verify task candidate checkpoints"
```

### Task 4: Capture Command-Level RED And GREEN Evidence

```yaml
task_type: tdd_implementation
dependencies: ["task_3"]
spec_refs: ["S1.7", "S1.17.1"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/command_evidence.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/worker.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py
  - skills/kws-codex-plan-executor/templates/worker-result-schema.json
  - skills/kws-codex-plan-executor/evals/check_method_evidence_v4.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_method_evidence_v4.py
operator_reviewed: true
```

**Files:** Create `command_evidence.py` and `check_method_evidence_v4.py`; modify `worker.py`, `evidence.py`, and `worker-result-schema.json`.

**Interfaces:** Produces `CommandObservation`, `MethodEvidence`, `normalize_codex_items()`, and `build_method_evidence()`.

- [ ] **Step 1: Write failing method-evidence checks**

```python
observations = normalize_codex_items(events)
evidence = build_method_evidence("tdd_implementation", observations)
assert evidence.red.exit_code == 1
assert evidence.red.before_first_mutation is True
assert evidence.green.exit_code == 0
```

Reject summary-only claims, RED after mutation, missing GREEN, raw home paths, and contradictory exit status.

- [ ] **Step 2: Run RED**

Run `python3 skills/kws-codex-plan-executor/evals/check_method_evidence_v4.py`.

Expected: command evidence module is missing.

- [ ] **Step 3: Normalize command and mutation events**

```python
@dataclass(frozen=True)
class CommandObservation:
    command: str
    status: str
    exit_code: int | None
    output_sha256: str
    sequence: int
    before_first_mutation: bool

@dataclass(frozen=True)
class MethodEvidence:
    method: str
    red: CommandObservation | None
    green: CommandObservation | None
    observations_sha256: str
```

Treat `item.completed` `command_execution` as a command and `file_change` as the mutation boundary. Store bounded sanitized output hashes, not raw output.

- [ ] **Step 4: Bind evidence to WorkerResult**

Add `method_evidence_ref` to the result schema. TDD completion requires valid RED/GREEN; explicit non-TDD types reject fabricated RED fields.

- [ ] **Step 5: Run GREEN and commit**

```bash
python3 skills/kws-codex-plan-executor/evals/check_method_evidence_v4.py
python3 skills/kws-codex-plan-executor/evals/check_runtime_safety.py
git add -- skills/kws-codex-plan-executor/scripts/cpe_runtime/{command_evidence,worker,evidence}.py skills/kws-codex-plan-executor/templates/worker-result-schema.json skills/kws-codex-plan-executor/evals/check_method_evidence_v4.py
git commit -m "feat(cpe): attest command-level method evidence"
```

### Task 5: Add Standing Autonomy, Failure Routing, And Supervision

```yaml
task_type: tdd_implementation
dependencies: ["task_2"]
spec_refs: ["S1.9", "S1.10", "S1.11", "S1.17.3"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/autonomy.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/failure_policy.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/supervisor.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/operator_decisions.py
  - skills/kws-codex-plan-executor/evals/check_autonomy_supervisor_v4.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_autonomy_supervisor_v4.py
operator_reviewed: true
```

**Files:** Create `autonomy.py`, `failure_policy.py`, `supervisor.py`, and `check_autonomy_supervisor_v4.py`; modify `operator_decisions.py`.

**Interfaces:** Produces `AutonomyDecision`, `FailureDecision`, `decide()`, `classify_failure()`, `needs_user_input()`, and `supervise()`.

- [ ] **Step 1: Write the failing decision table**

```python
assert classify("review_scope_expansion").action == "backlog_and_continue"
assert classify("provider_transient").action == "wait_external"
assert classify("evidence_integrity_failure").action == "block_release"
assert classify_same_root(2, release_impact=False).action == "backlog_and_continue"
assert classify_same_root(2, release_impact=True).action == "block_release"
assert needs_user_input(Action(remote_push=True)) is True
assert needs_user_input(Action(reversible=True, external=False)) is False
```

Simulate one waiting-user task plus an independent task and two identical decision notifications.

- [ ] **Step 2: Run RED**

Run `python3 skills/kws-codex-plan-executor/evals/check_autonomy_supervisor_v4.py`.

Expected: autonomy modules are missing.

- [ ] **Step 3: Implement evidence-backed decisions**

```python
@dataclass(frozen=True)
class AutonomyDecision:
    decision_id: str
    selected: str
    alternatives: tuple[str, ...]
    basis: str
    confidence: str
    reversible: bool
    affected_tasks: tuple[str, ...]
    approval_basis: str = "standing_autonomy_policy"
    user_input_required: bool = False
```

Rank approved documents, security/integrity/privacy, acceptance, smallest reversible change, repository pattern, then time/token/external-call economy.

- [ ] **Step 4: Implement failure budgets and supervision**

Store `repair_roots[root_cause_key]`. Counts 0 and 1 may repair; count 2 routes only approved release-impact classes to blocker and other hardening to backlog. `supervise()` resumes recovered external waits, schedules independent tasks, preserves run ID, and deduplicates decision IDs.

- [ ] **Step 5: Run GREEN and commit**

```bash
python3 skills/kws-codex-plan-executor/evals/check_autonomy_supervisor_v4.py
python3 skills/kws-codex-plan-executor/evals/check_recovery_policy.py
git add -- skills/kws-codex-plan-executor/scripts/cpe_runtime/{autonomy,failure_policy,supervisor,operator_decisions}.py skills/kws-codex-plan-executor/evals/check_autonomy_supervisor_v4.py
git commit -m "feat(cpe): supervise standing-autonomy runs"
```

### Task 6: Replace The Scheduler With The Bounded V4 Lifecycle

```yaml
task_type: tdd_implementation
dependencies: ["task_3", "task_4", "task_5"]
spec_refs: ["S1.5", "S1.8", "S1.9", "S1.10", "S1.11"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/attempt_controller.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py
  - skills/kws-codex-plan-executor/evals/check_scheduler_v4.py
  - skills/kws-codex-plan-executor/evals/check_fault_injection.py
  - skills/kws-codex-plan-executor/evals/check_execution_runtime.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_scheduler_v4.py
  - python3 skills/kws-codex-plan-executor/evals/check_fault_injection.py
operator_reviewed: true
```

**Files:** Create `check_scheduler_v4.py`; modify `attempt_controller.py`, `scheduler.py`, `reconciliation.py`, `repair.py`, `check_fault_injection.py`, and `check_execution_runtime.py`.

**Interfaces:** Produces `TaskPhase`, `TaskCycleResult`, `ReviewScope`, `run_task_cycle_v4()`, and `run_tasks_v4()`.

- [ ] **Step 1: Write failing lifecycle and budget tests**

```python
result = run_fixture("one-task-first-pass")
assert result.phases == ("preflight", "implementation", "candidate", "acceptance", "task_review", "verification", "verified_checkpoint")
assert result.model_attempts == 2
assert result.state["attempt_budget"] == {"limit": 40, "used": 2}
```

Add fixtures for one repair, two same-root repairs, a forbidden third repair, scope expansion, quota resume, runtime upgrade, dirty acceptance output, and delta-only repair review.

- [ ] **Step 2: Run RED**

Run `python3 skills/kws-codex-plan-executor/evals/check_scheduler_v4.py`.

Expected: existing v3 phases fail the assertion.

- [ ] **Step 3: Implement the state machine**

```python
TaskPhase = Literal["preflight", "implementation", "candidate", "acceptance", "task_review", "verification", "verified_checkpoint", "repair", "waiting_external", "waiting_user", "blocked"]
```

The cycle obtains one contract, runs implementation, creates a candidate, executes disposable acceptance, reviews only the task diff, runs deterministic verification, and promotes the checkpoint. Semantic verification runs only when declared.

- [ ] **Step 4: Enforce attempt and repair budgets**

Increment model budget only after a model turn starts. Deterministic commands and pre-turn interruption cost zero attempts. Stop at 40. After repair, review previous findings plus rejected-to-repaired delta; reopen a full task diff only for security, state, or evidence-boundary changes.

- [ ] **Step 5: Run GREEN and commit**

```bash
python3 skills/kws-codex-plan-executor/evals/check_scheduler_v4.py
python3 skills/kws-codex-plan-executor/evals/check_fault_injection.py
python3 skills/kws-codex-plan-executor/evals/check_execution_runtime.py
git diff --check
git add -- skills/kws-codex-plan-executor/scripts/cpe_runtime/{attempt_controller,scheduler,reconciliation,repair}.py skills/kws-codex-plan-executor/evals/{check_scheduler_v4,check_fault_injection,check_execution_runtime}.py
git commit -m "feat(cpe): bound the v4 task lifecycle"
```

### Task 7: Pin 5.6 Routes And Build Production-Faithful Prompt Bundles

```yaml
task_type: tdd_implementation
dependencies: ["task_1", "task_6"]
spec_refs: ["S1.12", "S1.13", "S1.15"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/model_policy.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_bundles.py
  - skills/kws-codex-plan-executor/templates/cpe-v4-worker-prefix.txt
  - skills/kws-codex-plan-executor/evals/control-bundles/cpe-3.1.0-production.json
  - skills/kws-codex-plan-executor/evals/check_model_policy.py
  - skills/kws-codex-plan-executor/evals/check_prompt_bundle_v4.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_model_policy.py
  - python3 skills/kws-codex-plan-executor/evals/check_prompt_bundle_v4.py
operator_reviewed: true
```

**Files:** Create `prompt_bundles.py`, `cpe-v4-worker-prefix.txt`, `cpe-3.1.0-production.json`, and `check_prompt_bundle_v4.py`; modify `model_policy.py` and `check_model_policy.py`.

**Interfaces:** Produces `PromptBundle`, `build_control_bundle()`, `build_candidate_bundle()`, `CORE_ROUTE`, and `SCOUT_ROUTE`.

- [ ] **Step 1: Write failing route and paired-bundle checks**

```python
assert policy_payload() == {"version": "cpe.model-policy.v4", "core": {"model": "gpt-5.6-sol", "reasoning": "high"}, "scout": {"model": "gpt-5.6-terra", "reasoning": "high"}}
control, candidate = paired_bundles(fixture_contract())
assert control.model == candidate.model == "gpt-5.6-sol"
assert control.case_sha256 == candidate.case_sha256
assert control.output_schema_sha256 == candidate.output_schema_sha256
assert control.prompt_sha256 != candidate.prompt_sha256
```

Reject fallback, Terra write/verdict, prompt drift, absolute paths, and a label-only control.

- [ ] **Step 2: Run RED**

Run both `check_model_policy.py` and `check_prompt_bundle_v4.py`.

Expected: policy version is not v4 and prompt bundle module is missing.

- [ ] **Step 3: Implement exact routes and bundle type**

```python
@dataclass(frozen=True)
class PromptBundle:
    schema_version: str
    treatment_id: str
    model: str
    reasoning: str
    role: str
    prompt: str
    prompt_sha256: str
    task_contract_sha256: str
    case_sha256: str
    output_schema_sha256: str
```

The control freezes normalized production input from commit `344f6112a7254b87cfa25fe0f6d6f3acbc964487`: scheduler instruction, packet bytes, selected spec, prior evidence, result contract. Replace dynamic paths with `$WORKTREE` and `$RUN_DIR`. Candidate contains complete TaskContractV4 and bounded prior-finding delta/context.

- [ ] **Step 4: Generate and validate the control fixture**

Generate the control in a disposable detached worktree at the pinned commit. Fail on commit, scheduler, packet, or output-schema drift. Store no transcript or local path.

- [ ] **Step 5: Run GREEN and commit**

```bash
python3 skills/kws-codex-plan-executor/evals/check_model_policy.py
python3 skills/kws-codex-plan-executor/evals/check_prompt_bundle_v4.py
python3 skills/kws-codex-plan-executor/evals/check_prompt.py
git add -- skills/kws-codex-plan-executor/scripts/cpe_runtime/{model_policy,prompt_bundles}.py skills/kws-codex-plan-executor/templates/cpe-v4-worker-prefix.txt skills/kws-codex-plan-executor/evals/control-bundles/cpe-3.1.0-production.json skills/kws-codex-plan-executor/evals/{check_model_policy,check_prompt_bundle_v4}.py
git commit -m "feat(cpe): compare production-faithful 5.6 prompts"
```

### Task 8: Compile And Resume The V4 Quality Matrix

```yaml
task_type: tdd_implementation
dependencies: ["task_7"]
spec_refs: ["S1.14", "S1.15", "S1.17.4"]
file_claims:
  - skills/kws-codex-plan-executor/evals/live-migration/matrix-v4.json
  - skills/kws-codex-plan-executor/evals/live-migration/current-v2-prompt.txt
  - skills/kws-codex-plan-executor/evals/live_migration/contracts.py
  - skills/kws-codex-plan-executor/evals/live_migration/compiler.py
  - skills/kws-codex-plan-executor/evals/live_migration/runner.py
  - skills/kws-codex-plan-executor/evals/live_migration/ledger.py
  - skills/kws-codex-plan-executor/evals/live_migration/oracle.py
  - skills/kws-codex-plan-executor/evals/live_model_runner.py
  - skills/kws-codex-plan-executor/evals/check_quality_matrix_v4.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_quality_matrix_v4.py
operator_reviewed: true
operator_decision: The approved v4 clean cut removes the historical matrix label fixture and replaces it with a production-faithful same-model control.
```

**Files:** Create `matrix-v4.json` and `check_quality_matrix_v4.py`; modify live-migration contracts/compiler/runner/ledger/oracle and `live_model_runner.py`; delete `current-v2-prompt.txt`.

**Interfaces:** Produces `cpe-quality-manifest.v4`, 24 slots, 17 credentialed calls, seven policy outcomes, sentinel reuse, and one corrected terminal rerun maximum.

- [ ] **Step 1: Write failing count and resume tests**

```python
manifest = compile_v4_manifest(commit="a" * 40, run_id="v4-test")
assert len(manifest["slots"]) == 24
assert manifest["credentialed_call_count"] == 17
assert manifest["expected_policy_failure_count"] == 7
assert {s["model"] for s in manifest["slots"] if s["credentialed"]} == {"gpt-5.6-sol", "gpt-5.6-terra"}
```

Run a fake sentinel then resume; assert 17 provider invocations, not 18. Assert a second terminal full failure blocks release.

- [ ] **Step 2: Run RED**

Run `python3 skills/kws-codex-plan-executor/evals/check_quality_matrix_v4.py`.

Expected: v4 matrix contract is missing.

- [ ] **Step 3: Define exact treatments**

```json
{"schema_version":"4","treatments":[{"id":"sol_v31_control","model":"gpt-5.6-sol","reasoning":"high"},{"id":"sol_v4_candidate","model":"gpt-5.6-sol","reasoning":"high"},{"id":"terra_v4","model":"gpt-5.6-terra","reasoning":"high"}]}
```

Compile eight control, eight candidate, one credentialed Terra read-only, and seven deterministic Terra policy slots.

- [ ] **Step 4: Implement sentinel reuse and rerun count**

Commit sentinel to the same ledger. Resume derives only pending slots. Projection stores `terminal_full_runs`; initial plus one corrected run is the maximum.

- [ ] **Step 5: Run GREEN and commit**

```bash
python3 skills/kws-codex-plan-executor/evals/check_quality_matrix_v4.py
python3 skills/kws-codex-plan-executor/evals/check_live_matrix_ledger.py
python3 skills/kws-codex-plan-executor/evals/check_live_matrix_oracle.py
python3 skills/kws-codex-plan-executor/evals/check_live_model_runner.py
git add -- skills/kws-codex-plan-executor/evals/live-migration/matrix-v4.json skills/kws-codex-plan-executor/evals/live_migration/{contracts,compiler,runner,ledger,oracle}.py skills/kws-codex-plan-executor/evals/live_model_runner.py skills/kws-codex-plan-executor/evals/check_quality_matrix_v4.py
git rm -- skills/kws-codex-plan-executor/evals/live-migration/current-v2-prompt.txt
git commit -m "feat(cpe): compile the v4 quality matrix"
```

### Task 9: Wire The V4 CLI, Maintained Evals, And Ten-Task E2E

```yaml
task_type: tdd_implementation
dependencies: ["task_6", "task_8"]
spec_refs: ["S1.17", "S1.19"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe.py
  - skills/kws-codex-plan-executor/scripts/inspect_runs.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/inspection.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/public_result.py
  - skills/kws-codex-plan-executor/evals/parser-fixtures/21-v4-ten-task-plan.md
  - skills/kws-codex-plan-executor/evals/dogfood/waygent-p0-task1-contract.json
  - skills/kws-codex-plan-executor/evals/check_cpe_v4_e2e.py
  - skills/kws-codex-plan-executor/evals/check_cpe_v4_release_evidence.py
  - skills/kws-codex-plan-executor/evals/maintained-checks.json
  - skills/kws-codex-plan-executor/evals/check_eval_harness.py
  - skills/kws-codex-plan-executor/evals/run.sh
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_cpe_v4_e2e.py
  - cd skills/kws-codex-plan-executor && ./evals/run.sh
operator_reviewed: true
```

**Files:** Create the ten-task plan, P0 dogfood contract, `check_cpe_v4_e2e.py`, and `check_cpe_v4_release_evidence.py`; modify the public CLI, inspection/result modules, maintained inventory, harness check, and `run.sh`.

**Interfaces:** Produces `cpe.py run|resume|supervise|inspect` for v4, public checkpoint/decision/budget summaries, and a ten-task fake-provider run capped at 40 attempts.

- [ ] **Step 1: Write failing CLI and E2E tests**

The fixture contains first-pass tasks, one repair, one transient resume, one backlog finding, and one runtime upgrade:

```python
result = run_v4_fixture("21-v4-ten-task-plan.md")
assert result["status"] == "completed"
assert result["run_ids_created"] == 1
assert result["model_attempts"] <= 40
assert len(result["verified_checkpoints"]) == 10
assert result["max_same_root_repairs"] <= 2
```

Invoke resume with a schema-3 fixture and require `unsupported_run_schema` rather than migration or traceback.

Create `check_cpe_v4_release_evidence.py` in this task. It validates commit/tree/manifest/result binding, 17+7 counts, privacy audit, and the P0 dogfood limits; against an empty evidence root it exits nonzero with `release_evidence_missing`.

- [ ] **Step 2: Run RED**

Run `python3 skills/kws-codex-plan-executor/evals/check_cpe_v4_e2e.py`.

Expected: CLI has no v4 supervise path.

- [ ] **Step 3: Wire the v4 commands**

Public JSON contains schema, run ID, status, current task, checkpoint head, attempt limit/used, next safe action, and `user_input_required`. `supervise` polls the same run. `inspect` reports decisions, backlog, repair roots, and checkpoint lineage without reading v3 state.

- [ ] **Step 4: Register production-backed checks**

Add the nine v4 checks from Tasks 1-9 to `maintained-checks.json`. The harness must prove an actual production entrypoint or subprocess sentinel for each check. Do not extend general AST control-flow analysis beyond this inventory.

- [ ] **Step 5: Run the complete cost-free gate**

```bash
python3 skills/kws-codex-plan-executor/evals/check_cpe_v4_e2e.py
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
cd ../..
bun run check
git diff --check
```

Expected: all commands pass; one ten-task run uses at most 40 attempts.

- [ ] **Step 6: Commit the final code checkpoint**

```bash
git add -- skills/kws-codex-plan-executor/scripts/cpe.py skills/kws-codex-plan-executor/scripts/inspect_runs.py skills/kws-codex-plan-executor/scripts/cpe_runtime/{inspection,public_result}.py skills/kws-codex-plan-executor/evals/parser-fixtures/21-v4-ten-task-plan.md skills/kws-codex-plan-executor/evals/dogfood/waygent-p0-task1-contract.json skills/kws-codex-plan-executor/evals/{check_cpe_v4_e2e,check_cpe_v4_release_evidence}.py skills/kws-codex-plan-executor/evals/{maintained-checks.json,check_eval_harness.py,run.sh}
git commit -m "feat(cpe): complete the v4 execution path"
git rev-parse HEAD
git rev-parse HEAD^{tree}
```

Task 10 binds its evidence to this immutable validator-inclusive checkpoint.

### Task 10: Run One Final Quality Matrix And Disposable Waygent Dogfood

```yaml
task_type: external_effect
dependencies: ["task_9"]
spec_refs: ["S1.14", "S1.15", "S1.18", "S1.19", "S1.20"]
file_claims:
  - skills/kws-codex-plan-executor/evals/check_cpe_v4_release_evidence.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_cpe_v4_release_evidence.py --evidence-root "$CPE_V4_EVIDENCE_ROOT" --implementation-commit "$CPE_V4_IMPLEMENTATION_COMMIT"
operator_reviewed: true
operator_decision: Execute one approved 17-call subscription matrix, retain seven policy outcomes, and dogfood P0 Task 1 without merging its product commit.
```

**Files:** Read `evals/check_cpe_v4_release_evidence.py`. Keep quality and dogfood artifacts only under external CPE evidence roots.

**Interfaces:** Produces one terminal quality ledger, aggregate, privacy audit, and dogfood report bound to commit/tree/patch. Makes no tracked release-metadata edit.

- [ ] **Step 1: Confirm the release-evidence validator fails on missing evidence**

```python
assert report["credentialed_call_count"] == 17
assert report["policy_outcome_count"] == 7
assert report["dogfood"]["run_ids_created"] == 1
assert report["dogfood"]["model_attempts"] <= 6
assert report["dogfood"]["elapsed_seconds"] <= 3600
assert report["privacy_audit"]["passed"] is True
```

Run against an empty root and expect `release_evidence_missing`.

- [ ] **Step 2: Freeze and reverify the Task 9 code checkpoint**

```bash
export CPE_V4_IMPLEMENTATION_COMMIT="$(git rev-parse HEAD)"
export CPE_V4_EVIDENCE_ROOT="$HOME/.codex/evals/cpe-v4-live/$CPE_V4_IMPLEMENTATION_COMMIT"
cd skills/kws-codex-plan-executor && ./evals/run.sh && cd ../..
```

No code change is allowed after this point until Task 10 evidence is terminal.

- [ ] **Step 3: Run preflight and sentinel slot**

```bash
python3 skills/kws-codex-plan-executor/evals/live_model_runner.py dry-run --matrix v4 --implementation-commit "$CPE_V4_IMPLEMENTATION_COMMIT" --output "$CPE_V4_EVIDENCE_ROOT/plan.json"
python3 skills/kws-codex-plan-executor/evals/live_model_runner.py start --matrix v4 --billing-mode chatgpt_subscription --sentinel-only --implementation-commit "$CPE_V4_IMPLEMENTATION_COMMIT" --evidence-root "$CPE_V4_EVIDENCE_ROOT"
```

Expected: exact ChatGPT auth and both 5.6 routes attest; one Sol candidate slot is committed.

- [ ] **Step 4: Resume the remaining immutable matrix**

```bash
python3 skills/kws-codex-plan-executor/evals/live_model_runner.py resume --evidence-root "$CPE_V4_EVIDENCE_ROOT" --wave-size 5
python3 skills/kws-codex-plan-executor/evals/live_model_runner.py aggregate --evidence-root "$CPE_V4_EVIDENCE_ROOT" --output "$CPE_V4_EVIDENCE_ROOT/aggregate.json"
```

Expected: 17 credentialed results, seven policy outcomes, zero duplicate and zero pending. If safe waves are unavailable, use sequential resume under the same manifest.

- [ ] **Step 5: Run disposable Waygent P0 Task 1 dogfood**

Run the pinned dogfood contract with CPE 4.0 `supervise` in a disposable worktree. Retain external evidence but do not merge the Waygent commit. Require one run, no runtime patch, at most six attempts, same-root repair at most two, one verified checkpoint, clean source, and at most 3,600 seconds.

- [ ] **Step 6: Validate and privacy-audit evidence**

```bash
python3 skills/kws-codex-plan-executor/evals/check_cpe_v4_release_evidence.py --evidence-root "$CPE_V4_EVIDENCE_ROOT" --implementation-commit "$CPE_V4_IMPLEMENTATION_COMMIT"
```

Expected: hard gates pass; context reduction is reported as a target result; sanitized surfaces contain no transcript, home path, credential, or oracle path.

### Task 11: Publish CPE 4.0.0 And Perform Cost-Free Closeout

```yaml
task_type: release_closeout
dependencies: ["task_10"]
spec_refs: ["S1.16", "S1.17.4", "S1.19", "S1.20"]
file_claims:
  - skills/kws-codex-plan-executor/SKILL.md
  - skills/kws-codex-plan-executor/README.md
  - skills/kws-codex-plan-executor/ARCHITECTURE.md
  - skills/kws-codex-plan-executor/HISTORY.md
  - skills/kws-codex-plan-executor/docs/**
  - skills/kws-codex-plan-executor/evals/baselines/v3.1.0.json
  - skills/kws-codex-plan-executor/evals/baselines/v4.0.0.json
  - skills/kws-codex-plan-executor/evals/live-migration/release-status.json
  - skills/kws-codex-plan-executor/evals/check_release_contract.py
  - graphify-out/GRAPH_REPORT.md
  - graphify-out/graph.json
acceptance:
  - cd skills/kws-codex-plan-executor && ./evals/run.sh && python3 evals/check_release_contract.py && python3 evals/check_docs_contract.py
operator_reviewed: true
operator_decision: Publish one 4.0.0 release from immutable evidence without rerunning provider calls for docs or Graphify.
```

**Files:** Modify CPE skill metadata, README, architecture, history, focused docs, release status, release checker, and Graphify; replace baseline `v3.1.0.json` with `v4.0.0.json`.

**Interfaces:** Produces version `4.0.0`, one active v4 baseline, reviewed evidence refs, truthful residual risks, and Graphify freshness. Makes zero provider calls.

- [ ] **Step 1: Write failing release assertions**

```python
checks = {
    "version_is_400": version == "4.0.0",
    "exactly_one_v4_baseline": active_baselines == ["v4.0.0.json"],
    "schema_is_v4": release_status["run_schema"] == "4",
    "quality_evidence_bound": release_status["implementation_commit"] == evidence["implementation_commit"],
    "credentialed_calls_are_17": evidence["credentialed_call_count"] == 17,
    "policy_outcomes_are_7": evidence["policy_outcome_count"] == 7,
    "dogfood_passed": evidence["dogfood"]["passed"] is True,
    "release_only_no_provider_calls": release_status["release_only_provider_calls"] == 0,
}
```

Run the release checker and expect failure on version 3.1.0.

- [ ] **Step 2: Update version, docs, baseline, and status**

Set version 4.0.0, remove the v3 baseline, and record implementation commit/tree, manifest/report/privacy/dogfood digests, 17+7 counts, actual metrics, context target result, billing observability boundary, and residual risks. Do not copy raw evidence into Git.

- [ ] **Step 3: Run the complete cost-free release gate**

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_docs_contract.py
python3 scripts/cpe.py --help
cd ../..
bun run check
git diff --check
```

Expected: all pass; record exact counts in `docs/verification-log.md`.

- [ ] **Step 4: Commit release metadata**

```bash
git add -- skills/kws-codex-plan-executor
git commit -m "release(cpe): publish autonomous executor 4.0.0"
```

- [ ] **Step 5: Refresh Graphify cost-free**

```bash
graphify update . --force
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran --output /tmp/cpe-v4-graphify.json
git diff --check
git add -- graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs(graphify): refresh map for CPE 4.0.0"
```

Do not rerun Task 10.

- [ ] **Step 6: Produce merge-ready evidence**

Report commits, cost-free results, evidence digests, dogfood result, residual risks, and clean status. Protected/local-main integration requires direct user approval. After approval, integrate in a separate main worktree and rerun release contract, docs contract, Graphify freshness, and `git diff --check`.

## Final Acceptance Summary

- All eleven task gates and every planned code/release commit pass review.
- TaskContractV4 source and role digest parity pass.
- Schema-3 input returns `unsupported_run_schema`.
- Acceptance cannot dirty the product worktree.
- RED/GREEN evidence comes from runtime command events.
- Same-root semantic repair cannot exceed two.
- Ordinary decisions continue under `standing_autonomy_policy`.
- Transient and runtime-upgrade paths resume the same v4 run.
- The ten-task E2E creates one run and uses at most 40 attempts.
- Final quality evidence contains 17 credentialed and seven policy outcomes without duplicates.
- Waygent P0 dogfood creates one run, at most six attempts, and one checkpoint within one hour.
- Exactly one CPE 4.0.0 baseline is active.
- Release-only docs and Graphify make zero provider calls.
- Merged-main cost-free verification passes after explicit approval.
