# CPE vNext Plan 3 Quality Deduplication And Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicate semantic judgment and unchanged verification, measure the result without weakening quality, and execute the only final R3/R2 proof sequence.

**Architecture:** An invariant registry consolidates specialist findings into one task verdict; `VerificationPlanner` reuses evidence only under an exact immutable key. Runtime metrics compare representative v4 controls with vNext, while the Program Final Gate freezes and proves one final checkpoint.

**Tech Stack:** Python 3 standard library, JSON evidence, existing worker/prompt pipeline, fake Codex fixtures, guarded live runner.

## Global Constraints

- Source spec sections: S1.10 through S1.15.
- Complete all approved tasks; same-root repetition changes strategy rather than abandoning scope.
- The 50 percent reduction is a reported target, never permission to skip evidence.
- No credentialed call occurs before the Program Final Gate and fresh explicit user authority.
- Deterministic parsing, hashing, graphing, filtering, deduplication, and result classification do not use model turns.
- Final proof binds the post-Plan-3 checkpoint, not a Plan 1 or Plan 2 checkpoint.
- `operator_reviewed` is implementation-review metadata only; it does not authorize any live call.

---

### Task 1: Consolidate Reviews By Invariant

```yaml
task_type: tdd_implementation
dependencies: []
spec_refs: ["S1.10.1", "S1.12"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/invariant_registry.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/review_pipeline.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/failure_policy.py
  - skills/kws-codex-plan-executor/scripts/cpe.py
  - skills/kws-codex-plan-executor/scripts/inspect_runs.py
  - skills/kws-codex-plan-executor/evals/check_review_dedup_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_review_dedup_vnext.py
operator_reviewed: true
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces `InvariantFinding`, `TaskQualityVerdict`, `consolidate_findings()`, `affected_invariants()`, `cpe.py review-program --run-id`, and `inspect_runs.py --latest-vnext-id`.

- [ ] **Step 1: Write failing duplicate-finding and repair-scope checks**

```python
verdict = consolidate_findings(reports, revision=3)
assert [item.invariant_id for item in verdict.findings] == ["state.replay_parity"]
assert affected_invariants(verdict, repair_delta) == ("state.replay_parity",)
assert classify_same_root(2, release_impact=True).action == "redesign_invariant"
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_review_dedup_vnext.py`

Expected: FAIL because the invariant registry does not exist.

- [ ] **Step 3: Implement canonical invariant reduction**

```python
def consolidate_findings(reports, *, revision: int) -> TaskQualityVerdict:
    grouped = group_by_invariant(reports)
    findings = tuple(merge_group(grouped[key]) for key in sorted(grouped))
    return TaskQualityVerdict(revision=revision, findings=findings)
```

Change the third same-root release-impact action from local patch blocking to `redesign_invariant`; the task remains incomplete.
Add `review-program --run-id` as a workspace- and provider-read-only four-lane
dispatcher. Its only allowed write is submission of review results through the
kernel-owned evidence writer; it cannot edit product files, mutate provider
state, or append events directly. Add `--latest-vnext-id` as a read-only
inspection selector that prints exactly one run ID.

- [ ] **Step 4: Run GREEN**

Run: `python3 skills/kws-codex-plan-executor/evals/check_review_dedup_vnext.py`

Expected: PASS for duplicate prose, conflicting severity, repair-delta scope, high-risk reopen, and structural redesign routing.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/{invariant_registry,review_pipeline,failure_policy}.py skills/kws-codex-plan-executor/scripts/cpe.py skills/kws-codex-plan-executor/scripts/inspect_runs.py skills/kws-codex-plan-executor/evals/check_review_dedup_vnext.py
git commit -m "feat(cpe): consolidate vnext reviews by invariant"
```

### Task 2: Reuse Verification Only Under Exact Evidence Keys

```yaml
task_type: tdd_implementation
dependencies: ["T1"]
spec_refs: ["S1.10.2", "S1.10.3", "S1.13.3"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/verification_planner.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/verification_workspace.py
  - skills/kws-codex-plan-executor/evals/check_verification_planner_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_verification_planner_vnext.py
operator_reviewed: true
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces `VerificationKey`, `VerificationPlan`, and `plan_verification(change, graph, evidence) -> VerificationPlan`.

- [ ] **Step 1: Write key and widening RED cases**

```python
key = VerificationKey(tree, patch, command, environment, lock_digest, invariants)
assert plan_verification(unchanged, graph, [passed(key)]).reused == (key,)
assert plan_verification(lock_changed, graph, [passed(key)]).commands == (command,)
assert plan_verification(ambiguous_change, graph, []).scope == "full"
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_verification_planner_vnext.py`

Expected: FAIL because `verification_planner.py` is missing.

- [ ] **Step 3: Implement exact-key planning**

```python
@dataclass(frozen=True)
class VerificationKey:
    tree: str
    patch_sha256: str
    command_sha256: str
    environment_sha256: str
    lock_sha256: str
    invariant_sha256: str
```

Ambiguous impact returns the broader task, affected, or full scope; it never reuses partial evidence.

- [ ] **Step 4: Run GREEN**

Run: `python3 skills/kws-codex-plan-executor/evals/check_verification_planner_vnext.py`

Expected: PASS for exact reuse, every invalidation dimension, repair deltas, program downstream impact, and metadata-only closeout.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/{verification_planner,verification_workspace}.py skills/kws-codex-plan-executor/evals/check_verification_planner_vnext.py
git commit -m "feat(cpe): plan vnext verification from immutable evidence"
```

### Task 3: Slim Role Prompts And Record Runtime Metrics

```yaml
task_type: tdd_implementation
dependencies: ["T2"]
spec_refs: ["S1.10.4", "S1.10.6"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_bundles.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/worker.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/run_metrics.py
  - skills/kws-codex-plan-executor/evals/check_quality_metrics_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_quality_metrics_vnext.py
operator_reviewed: true
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces `RunMetrics`, `record_attempt_metric()`, `quality_efficiency_report()`, and role packets with common constraints stored once.

- [ ] **Step 1: Write failing prompt and metrics checks**

```python
assert candidate.prompt.count("approval boundaries") == 1
assert scout.tools == ("read_file", "search")
report = quality_efficiency_report(control, candidate)
assert report["quality_gate_passed"] is True
assert report["model_attempt_reduction"] == Decimal("0.50")
assert report["target_is_release_gate"] is False
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_quality_metrics_vnext.py`

Expected: FAIL because common prompt text is repeated and `run_metrics.py` is missing.

- [ ] **Step 3: Extract common packet content and implement passive metrics**

```python
@dataclass(frozen=True)
class RunMetrics:
    attempts: Mapping[str, int]
    semantic_reviews: int
    suite_runs: Mapping[str, int]
    tokens: Mapping[str, int]
    wall_clock_ms: int
```

Metrics consume existing events and evidence; they never dispatch a model or rerun a command.

- [ ] **Step 4: Run GREEN**

Run: `python3 skills/kws-codex-plan-executor/evals/check_quality_metrics_vnext.py`

Expected: PASS for one-copy constraints, role-specific tools, missing usage fields, zero-denominator reports, and advisory 50 percent targets.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/{prompt_bundles,worker,run_metrics}.py skills/kws-codex-plan-executor/evals/check_quality_metrics_vnext.py
git commit -m "feat(cpe): slim prompts and measure vnext workflow efficiency"
```

### Task 4: Run Representative Cost-Free Quality Comparison

```yaml
task_type: verification
dependencies: ["T3"]
spec_refs: ["S1.11", "S1.13.5"]
file_claims:
  - skills/kws-codex-plan-executor/evals/check_vnext_quality_comparison.py
  - skills/kws-codex-plan-executor/evals/maintained-checks.json
  - skills/kws-codex-plan-executor/docs/verification-log.md
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_vnext_quality_comparison.py
operator_reviewed: true
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces a sanitized comparison for small single-plan, ten-task, Canvas multi-plan, and Waygent dogfood fixtures.

The v4 side is loaded only from the immutable tracked
`evals/fixtures/v4-control-snapshot.json` created before Plan 2 removed the v4
success path. The comparison must not import or execute v4 runtime code.

- [ ] **Step 1: Implement the deterministic comparison driver**

```python
for fixture in ("single", "ten-task", "canvas-program", "waygent-p0"):
    result = compare_frozen_control_with_vnext(fixture)
    assert result.p0_p1_detection == 1
    assert result.false_successes == 0
    assert result.required_evidence_missing == 0
```

- [ ] **Step 2: Run the comparison**

Run: `python3 skills/kws-codex-plan-executor/evals/check_vnext_quality_comparison.py`

Expected: exit 0; the tracked control digest is verified, quality gates pass,
and exact efficiency deltas are reported without a credentialed call or a v4
success route.

- [ ] **Step 3: Register maintained checks and run the cost-free suite**

Run: `cd skills/kws-codex-plan-executor && ./evals/run.sh`

Expected: exit 0 with all vNext checks registered and `paid_execution=skipped_not_approved`.

- [ ] **Step 4: Run repository verification**

Run: `bun run check && git diff --check`

Expected: both exit 0.

- [ ] **Step 5: Commit the frozen Plan 3 runtime checkpoint**

```bash
git add skills/kws-codex-plan-executor/evals/check_vnext_quality_comparison.py skills/kws-codex-plan-executor/evals/maintained-checks.json skills/kws-codex-plan-executor/docs/verification-log.md
git commit -m "test(cpe): freeze vnext quality comparison checkpoint"
```

Record the frozen checkpoint's commit, tree, Plan 3 hash, spec hash, and Plan 2
upstream checkpoint before entering the Program Final Gate.

### Task 5: Execute The Program Final Gate

```yaml
task_type: external_effect
dependencies: ["T4"]
spec_refs: ["S1.8.4", "S1.8.5", "S1.8.6", "S1.11", "S1.15"]
file_claims:
  - skills/kws-codex-plan-executor/docs/verification-log.md
  - skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md
  - skills/kws-codex-plan-executor/docs/release-process.md
  - graphify-out/GRAPH_REPORT.md
  - graphify-out/graph.json
acceptance:
  - cd skills/kws-codex-plan-executor && ./evals/run.sh
operator_reviewed: true
operator_decision: Credentialed R2 proof requires fresh explicit subscription-usage authority after the final R3 review and cost-free gate; without it the program remains honestly blocked, not failed or complete.
```

**Files:** Create or modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces the final R3 consolidated verdict, `proof_checkpoint`, terminal R2 generation, `closeout_commit`, and program completion report.

- [ ] **Step 1: Freeze and run the four review lanes**

Run: `python3 skills/kws-codex-plan-executor/scripts/cpe.py review-program --run-id "$(python3 skills/kws-codex-plan-executor/scripts/inspect_runs.py --codex-home ~/.codex --latest-vnext-id)" --lanes state_crash,trust_privacy,cli_dataflow,release_lineage`

Expected: one checkpoint-bound consolidated report. If it contains P0/P1 findings, run the one consolidated repair through the same run, repeat affected checks, create a new frozen checkpoint, and rerun this step before continuing.

- [ ] **Step 2: Run the final cost-free gate once**

Run: `cd skills/kws-codex-plan-executor && ./evals/run.sh && cd ../.. && bun run check && git diff --check`

Expected: all commands exit 0; the proof checkpoint is unchanged throughout.

- [ ] **Step 3: Stop for current credentialed-call authority**

Do not infer approval from this plan. Obtain explicit authority for ChatGPT subscription usage and the `2/4/6` ceiling. Without authority, record `authority_required` and preserve the frozen run.
No `operator_reviewed` field, prior review result, or implementation checkpoint
can substitute for this fresh live-call authority.

- [ ] **Step 4: Execute sentinel, normal regression, dogfood, and finalization**

```bash
cd skills/kws-codex-plan-executor
EVIDENCE_ROOT="$HOME/.codex/cpe-vnext-release-evidence"
python3 evals/live_model_runner.py start --matrix vnext --proof-profile critical_path_live --sentinel-only --confirm-subscription-usage --evidence-root "$EVIDENCE_ROOT"
RUN_DIR="$(find "$EVIDENCE_ROOT" -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
python3 evals/live_model_runner.py resume --run-dir "$RUN_DIR" --confirm-subscription-usage
python3 evals/live_model_runner.py aggregate --run-dir "$RUN_DIR" --output "$RUN_DIR/aggregate.json"
python3 evals/live_model_runner.py finalize-release --evidence-root "$EVIDENCE_ROOT" --run-dir "$RUN_DIR" --dogfood-run-dir "$HOME/.codex/orchestrator/$(python3 scripts/inspect_runs.py --codex-home ~/.codex --latest-vnext-id)"
```

Expected: exactly two critical matrix calls, no duplicate sentinel, at most four dogfood attempts, terminal privacy-clean generation, and `critical-path-live verified`.

- [ ] **Step 5: Perform metadata-only closeout and commit**

Update the verification log and risk register with proof and closeout commits, keep R4-R6 truthful, run docs checks and Graphify freshness, then commit only allowlisted metadata:

```bash
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran
git diff --check
git add skills/kws-codex-plan-executor/docs/verification-log.md skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md skills/kws-codex-plan-executor/docs/release-process.md graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs(cpe): close vnext program release evidence"
```
