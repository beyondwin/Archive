# CPE vNext Plan 2 Runtime And Multi-Plan Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace v3/v4 execution branches with one vNext PlanGraph-driven runtime supporting one spec with one or many plans.

**Architecture:** `DocumentSetCompiler` snapshots the spec, optional program plan, and implementation plans; `PlanGraphCompiler` emits qualified tasks and plan checkpoints. A pure `TransitionKernel` chooses commands, `PhaseExecutor` performs one command, and canonical validation reads evidence through one resolver.

**Tech Stack:** Python 3 standard library, Git worktrees, JSON/JSONL, existing plan parser and CPE eval harness.

## Global Constraints

- Source spec sections: S1.7, S1.9, S1.12, S1.13.1, and S1.13.2.
- Consume the exact Plan 1 trust checkpoint and preserve its `TrustRoot` binding.
- One `--plan` and repeated `--plan` are both native vNext inputs; `--program-plan` is optional.
- Old runs return `unsupported_version` after header inspection and are never migrated or rewritten.
- The kernel is the only lifecycle decision and durable-event writer.
- Write-capable tasks are sequential; only independent read-only scouts may run concurrently.
- No credentialed calls occur in this plan.

## File Structure

- `scripts/cpe_runtime/document_set.py`: canonical input documents and hashes.
- `scripts/cpe_runtime/plan_graph.py`: graph, ownership, coverage, invalidation.
- `scripts/cpe_runtime/transition_kernel.py`: pure state/event-to-command table.
- `scripts/cpe_runtime/phase_executor.py`: one-command execution adapter.
- `scripts/cpe_runtime/evidence_resolver.py`: canonical evidence interpretation.
- `evals/fixtures/canvas-program-6d41fb9/`: pinned public multi-plan fixture.

---

### Task 1: Compile Single And Multi-Plan Document Sets

```yaml
task_type: tdd_implementation
dependencies: []
spec_refs: ["S1.7.1", "S1.7.2", "S1.7.3"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/document_set.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/plan_compiler.py
  - skills/kws-codex-plan-executor/evals/check_document_set_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_document_set_vnext.py
operator_reviewed: true
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces `InputDocument`, `DocumentSet`, and `compile_document_set(spec, plans, program_plan, docs)`. Changes `compile_run(plan: Path, ...)` to `compile_run(plans: tuple[Path, ...], program_plan: Path | None, ...)`.

- [ ] **Step 1: Write failing CLI and identity checks**

```python
args = build_parser().parse_args(["run", "--spec", "spec.md", "--plan", "a.md", "--plan", "b.md", "--program-plan", "program.md", "--workspace", "."])
assert args.plan == ["a.md", "b.md"]
documents = compile_document_set(spec, (plan_a, plan_b), program, ())
assert [item.kind for item in documents.documents] == ["spec", "program", "plan", "plan"]
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_document_set_vnext.py`

Expected: FAIL because `--plan` is scalar and `document_set.py` is missing.

- [ ] **Step 3: Implement repeatable arguments and immutable documents**

```python
@dataclass(frozen=True)
class InputDocument:
    document_id: str
    kind: Literal["spec", "program", "plan", "doc"]
    path: Path
    sha256: str
    content: bytes

run.add_argument("--plan", action="append", required=True)
run.add_argument("--program-plan")
```

- [ ] **Step 4: Run GREEN**

Run: `python3 skills/kws-codex-plan-executor/evals/check_document_set_vnext.py`

Expected: PASS for single, repeated, optional-program, duplicate-identity, unreadable, and reordered-input cases.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe.py skills/kws-codex-plan-executor/scripts/cpe_runtime/document_set.py skills/kws-codex-plan-executor/scripts/cpe_runtime/plan_compiler.py skills/kws-codex-plan-executor/evals/check_document_set_vnext.py
git commit -m "feat(cpe): compile vnext document sets"
```

### Task 2: Build PlanGraph With Canvas Program Coverage

```yaml
task_type: tdd_implementation
dependencies: ["T1"]
spec_refs: ["S1.7.3", "S1.7.4", "S1.7.5", "S1.7.6", "S1.7.7"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/plan_graph.py
  - skills/kws-codex-plan-executor/evals/check_plan_graph_vnext.py
  - skills/kws-codex-plan-executor/evals/fixtures/canvas-program-6d41fb9/**
  - skills/kws-codex-plan-executor/evals/fixtures/cpe-vnext-self-dogfood.json
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_plan_graph_vnext.py
operator_reviewed: true
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces `QualifiedTaskId`, `PlanGraph`, `compile_plan_graph(document_set)`, and `invalidated_nodes(old, new) -> tuple[str, ...]`.

- [ ] **Step 1: Pin the public fixture and write graph RED cases**

```python
graph = compile_fixture("canvas-program-6d41fb9")
assert graph.plan_count == 12
assert graph.global_integration_gate.plan_id.endswith("wave-6-integration-evidence")
assert all("::" in task_id for task_id in graph.tasks)
assert invalidated_nodes(graph, changed_wave_b2) == graph.downstream_of("wave-b2")
self_graph = compile_tracked_self_dogfood("evals/fixtures/cpe-vnext-self-dogfood.json")
assert self_graph.plan_count == 3
assert self_graph.program_document_id is not None
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_plan_graph_vnext.py`

Expected: FAIL because `plan_graph.py` is missing.

- [ ] **Step 3: Implement canonical graph validation**

```python
@dataclass(frozen=True)
class PlanGraph:
    document_hashes: Mapping[str, str]
    tasks: Mapping[str, Mapping[str, object]]
    edges: tuple[tuple[str, str], ...]
    spec_coverage: Mapping[str, tuple[str, ...]]
    file_ownership: Mapping[str, tuple[str, ...]]
    global_integration_gate: Mapping[str, object]
    graph_sha256: str
```

Reject cycles, orphan tasks, missing required coverage, ambiguous ownership, duplicate task IDs, and absent multi-plan final gates.

- [ ] **Step 4: Run GREEN**

Run: `python3 skills/kws-codex-plan-executor/evals/check_plan_graph_vnext.py`

Expected: PASS for single plan, ordered multi-plan fallback, Canvas program,
the tracked program-plus-three-plans self-dogfood fixture, ownership transfer,
and downstream-only invalidation.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/plan_graph.py skills/kws-codex-plan-executor/evals/check_plan_graph_vnext.py skills/kws-codex-plan-executor/evals/fixtures/canvas-program-6d41fb9 skills/kws-codex-plan-executor/evals/fixtures/cpe-vnext-self-dogfood.json
git commit -m "feat(cpe): compile vnext multi-plan graphs"
```

### Task 3: Bind Qualified Tasks, Plans, And Checkpoints

```yaml
task_type: tdd_implementation
dependencies: ["T2"]
spec_refs: ["S1.7.5", "S1.7.7", "S1.9.3"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/task_contracts.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/packets.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/checkpoints.py
  - skills/kws-codex-plan-executor/evals/check_multiplan_contract_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_multiplan_contract_vnext.py
operator_reviewed: true
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** `TaskContractVNext` includes `plan_id`, `qualified_task_id`, `document_sha256`, and `upstream_graph_sha256`; every `PlanCheckpoint` binds commit, tree, plan hash, spec hash, and upstream checkpoint.

- [ ] **Step 1: Add failing qualified-identity assertions**

```python
assert contract.qualified_task_id == f"{contract.plan_id}::{contract.task_id}"
assert manifest["plan_graph"]["graph_sha256"] == graph.graph_sha256
assert checkpoint.upstream_graph_sha256 == graph.upstream_digest(plan_id)
assert checkpoint.spec_sha256 == document_set.spec.sha256
assert checkpoint.upstream_checkpoint == previous_plan_checkpoint.identity()
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_multiplan_contract_vnext.py`

Expected: FAIL because current contracts contain only local task IDs.

- [ ] **Step 3: Add vNext fields and plan checkpoint evidence**

```python
@dataclass(frozen=True)
class PlanCheckpoint:
    plan_id: str
    commit: str
    tree: str
    plan_sha256: str
    spec_sha256: str
    upstream_checkpoint: str | None
    upstream_graph_sha256: str
    evidence_refs: tuple[dict[str, str], ...]
```

- [ ] **Step 4: Run GREEN**

Run: `python3 skills/kws-codex-plan-executor/evals/check_multiplan_contract_vnext.py`

Expected: PASS for packet digest parity, cross-plan dependency binding, checkpoint promotion, and stale-upstream rejection.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/{task_contracts,manifest,packets,checkpoints}.py skills/kws-codex-plan-executor/evals/check_multiplan_contract_vnext.py
git commit -m "feat(cpe): bind vnext tasks and plan checkpoints"
```

### Task 4: Replace Scheduler Branches With TransitionKernel And PhaseExecutor

```yaml
task_type: tdd_implementation
dependencies: ["T3"]
spec_refs: ["S1.9.1", "S1.9.2", "S1.9.3", "S1.9.7", "S1.12"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/transition_kernel.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/phase_executor.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence_store.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py
  - skills/kws-codex-plan-executor/evals/check_transition_kernel_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_transition_kernel_vnext.py
operator_reviewed: true
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces `KernelCommand`, `TypedOutcome`, `EvidenceStore`, `decide(state, outcome) -> KernelCommand`, and `PhaseExecutor.execute(command) -> TypedOutcome`. `EvidenceStore` is the only content-addressed evidence writer and the kernel remains the only event writer.

- [ ] **Step 1: Write the transition-table RED**

```python
assert decide(state("ready"), event("start")) == KernelCommand("implementation", task_id)
assert decide(state("reviewed"), event("pass")) == KernelCommand("verify", task_id)
with pytest.raises(IllegalTransition):
    decide(state("ready"), event("complete_program"))
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_transition_kernel_vnext.py`

Expected: FAIL because `transition_kernel.py` is missing.

- [ ] **Step 3: Implement pure decisions and one-command execution**

```python
def decide(state: RunState, outcome: TypedOutcome) -> KernelCommand:
    try:
        return TRANSITIONS[(state.phase, outcome.kind)](state, outcome)
    except KeyError as exc:
        raise IllegalTransition(state.phase, outcome.kind) from exc

class PhaseExecutor:
    def execute(self, command: KernelCommand) -> TypedOutcome:
        return self.handlers[command.kind](command)
```

- [ ] **Step 4: Run transition and crash GREEN**

Run: `python3 skills/kws-codex-plan-executor/evals/check_transition_kernel_vnext.py`

Expected: PASS for every legal transition, illegal transitions, wait/resume,
structural redesign routing, evidence byte verification, and generated crash
points before/after evidence persistence, event append, projection replacement,
plan-checkpoint publication, external-call registration, and global completion.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/{transition_kernel,phase_executor,evidence_store,kernel,projector,scheduler}.py skills/kws-codex-plan-executor/evals/check_transition_kernel_vnext.py
git commit -m "feat(cpe): cut over to one vnext transition kernel"
```

### Task 5: Canonicalize Validation And Remove Old Runtime Paths

```yaml
task_type: tdd_implementation
dependencies: ["T4"]
spec_refs: ["S1.9.1", "S1.9.4", "S1.9.5", "S1.9.6", "S1.13.2"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence_resolver.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/dogfood_vnext.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/quality_vnext.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/dogfood_v4.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/quality_v4.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/release_policy_v4.py
  - skills/kws-codex-plan-executor/scripts/cpe.py
  - skills/kws-codex-plan-executor/evals/check_vnext_cutover.py
  - skills/kws-codex-plan-executor/evals/check_quality_matrix_v4.py
  - skills/kws-codex-plan-executor/evals/check_cpe_v4_e2e.py
  - skills/kws-codex-plan-executor/evals/check_validation_profiles_vnext.py
  - skills/kws-codex-plan-executor/evals/check_manifest_prompt_vnext.py
  - skills/kws-codex-plan-executor/evals/check_sentinel_resume_vnext.py
  - skills/kws-codex-plan-executor/evals/check_ledger_crash_vnext.py
  - skills/kws-codex-plan-executor/evals/check_release_lineage_vnext.py
  - skills/kws-codex-plan-executor/evals/check_privacy_oracle_vnext.py
  - skills/kws-codex-plan-executor/evals/check_authentic_e2e_vnext.py
  - skills/kws-codex-plan-executor/evals/check_fixed_route_vnext.py
  - skills/kws-codex-plan-executor/evals/fixtures/v4-control-snapshot.json
  - skills/kws-codex-plan-executor/evals/maintained-checks.json
  - skills/kws-codex-plan-executor/docs/verification-log.md
  - graphify-out/GRAPH_REPORT.md
  - graphify-out/graph.json
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_vnext_cutover.py
operator_reviewed: true
operator_decision: Approved clean-cut removal of v3 and v4 execution compatibility; historical artifacts must remain untouched and return unsupported_version.
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces `EvidenceResolver`, keeps `validate_integrity()` and `validate_completion()`, and returns `unsupported_version` without opening historical artifact graphs. Validation has exactly three profiles: event/projection/artifact integrity; task/plan-checkpoint/current-revision completion; and release trust/proof binding.

- [ ] **Step 1: Write cutover and evidence-resolution RED cases**

```python
assert inspect_old_run(v4_run).classification == "unsupported_version"
assert snapshot_tree(v4_run) == before
assert EvidenceResolver(run_dir).resolve(ref).task_id == "plan-a::T1"
assert validate_completion(vnext_run).passed is True
assert load_control_snapshot().sha256 == tracked_control_digest
assert every_required_quality_invariant_has_exactly_one_owner()
assert all_decomposed_quality_suites_are_maintained_checks()
assert check_quality_matrix_v4_is_rejection_only()
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_vnext_cutover.py`

Expected: FAIL because old resume paths and multiple artifact readers remain.

- [ ] **Step 3: Route all validators through EvidenceResolver and delete old dispatch**

```python
def inspect_version_header(run_dir: Path) -> str:
    marker = json.loads((run_dir / "run_manifest.json").read_text())["schema_version"]
    if marker != RUN_SCHEMA_VERSION:
        raise UnsupportedVersion(marker)
    return marker
```

Before deleting any successful v4 implementation or fixture, write the
immutable cost-free representative control to
`evals/fixtures/v4-control-snapshot.json`, bind its canonical digest in the
comparison check, and prove that it contains no executable route, provider
input, credential, or mutable path. Move retained dogfood and quality behavior into `dogfood_vnext.py` and
`quality_vnext.py`. Remove `run_task_cycle`, `run_task_cycle_v4`, old resume
selectors, compatibility projections, `dogfood_v4.py`, `quality_v4.py`,
`release_policy_v4.py`, and their successful old-run fixtures after vNext
tests pass. Convert `check_cpe_v4_e2e.py` into the old-artifact rejection
oracle: it must prove old artifacts stay untouched and must not execute or
accept a successful v4 run.

- [ ] **Step 3a: Decompose the quality suite inside Task 5**

This step is part of Task 5; it is not a new implementation task. Move each
vNext invariant out of the monolithic v4 quality matrix into exactly one of
these maintained focused suites:

- `check_manifest_prompt_vnext.py`: canonical manifest, task-packet, prompt,
  schema, and no-worker-authority binding.
- `check_sentinel_resume_vnext.py`: sentinel-first qualification, bounded
  attempts, resume/idempotency, and deterministic no-call outcomes.
- `check_ledger_crash_vnext.py`: evidence/event/projection/checkpoint ordering,
  generated crash points, replay, and recovery.
- `check_release_lineage_vnext.py`: trusted-base and control-snapshot binding,
  upstream plan checkpoints, release lineage, and terminal generation.
- `check_privacy_oracle_vnext.py`: hidden-oracle separation, privacy scanning,
  digest binding, and leak/tamper rejection.
- `check_authentic_e2e_vnext.py`: provider-free public-CLI multi-plan execution,
  dogfood, completion, and unsupported historical artifact behavior.
- `check_fixed_route_vnext.py`: exact Sol/high core and Terra/high bounded
  read-only route preservation, with override/fallback rejection.

`check_quality_matrix_v4.py` may retain only historical v4 rejection/control
coverage needed for the immutable snapshot; it must not remain a second owner
of vNext scenarios. Update `maintained-checks.json` so every focused suite is
listed exactly once with a production entrypoint and mutation assertion. Add
acceptance assertions proving every required quality invariant has exactly one owning suite,
every declared suite is registered and executed, and no vNext
scenario implementation remains in the v4 matrix or historical E2E oracle.

- [ ] **Step 4: Run focused and authentic multi-plan E2E**

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_vnext_cutover.py
python3 evals/check_validation_profiles_vnext.py
python3 evals/check_manifest_prompt_vnext.py
python3 evals/check_sentinel_resume_vnext.py
python3 evals/check_ledger_crash_vnext.py
python3 evals/check_release_lineage_vnext.py
python3 evals/check_privacy_oracle_vnext.py
python3 evals/check_authentic_e2e_vnext.py
python3 evals/check_fixed_route_vnext.py
python3 evals/check_cpe_v4_e2e.py
```

Expected: the three validation profiles and authentic vNext E2E pass; the
fixed route remains exactly Sol/high for core work and Terra/high for bounded
read-only scouting; the historical check is retained only as a rejection
oracle and cannot execute an old run. The decomposition assertions prove every
required quality invariant has exactly one owning suite, all seven suites are
registered and executed, and the v4 matrix contains no duplicate vNext
scenario implementation.

- [ ] **Step 5: Run the verified-checkpoint gate and commit Plan 2**

Run the focused cutover checks above, then:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
cd ../..
bun run check
git diff --check
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran
```

Expected: every command exits 0, Graphify reports `fresh=true`, and the
checkpoint record contains commit, tree, Plan 2 hash, spec hash, and the Plan 1
upstream checkpoint.

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence_resolver.py skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py skills/kws-codex-plan-executor/scripts/cpe_runtime/dogfood_vnext.py skills/kws-codex-plan-executor/scripts/cpe_runtime/quality_vnext.py skills/kws-codex-plan-executor/scripts/cpe_runtime/dogfood_v4.py skills/kws-codex-plan-executor/scripts/cpe_runtime/quality_v4.py skills/kws-codex-plan-executor/scripts/cpe_runtime/release_policy_v4.py skills/kws-codex-plan-executor/scripts/cpe.py skills/kws-codex-plan-executor/evals/check_vnext_cutover.py skills/kws-codex-plan-executor/evals/check_quality_matrix_v4.py skills/kws-codex-plan-executor/evals/check_cpe_v4_e2e.py skills/kws-codex-plan-executor/evals/check_validation_profiles_vnext.py skills/kws-codex-plan-executor/evals/check_manifest_prompt_vnext.py skills/kws-codex-plan-executor/evals/check_sentinel_resume_vnext.py skills/kws-codex-plan-executor/evals/check_ledger_crash_vnext.py skills/kws-codex-plan-executor/evals/check_release_lineage_vnext.py skills/kws-codex-plan-executor/evals/check_privacy_oracle_vnext.py skills/kws-codex-plan-executor/evals/check_authentic_e2e_vnext.py skills/kws-codex-plan-executor/evals/check_fixed_route_vnext.py skills/kws-codex-plan-executor/evals/fixtures/v4-control-snapshot.json skills/kws-codex-plan-executor/evals/maintained-checks.json skills/kws-codex-plan-executor/docs/verification-log.md graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "feat(cpe): complete vnext runtime and multi-plan cutover"
```
