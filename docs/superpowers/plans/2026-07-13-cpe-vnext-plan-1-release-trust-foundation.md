# CPE vNext Plan 1 Release Trust Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close R1 and build immutable release-closure and four-lane review contracts without making credentialed provider calls.

**Architecture:** A fixed-path `GitObjectSource` reads policy and dogfood contract bytes from an exact commit and emits one digest-bound `TrustRoot`. Release compilation, ledgers, dogfood, finalization, validation, and future review artifacts consume that same root; a deterministic closure transaction prepares the final program gate.

**Tech Stack:** Python 3 standard library, Git CLI object reads, dataclasses, JSON/JSONL, existing CPE release evals.

## Global Constraints

- Source spec: `docs/superpowers/specs/2026-07-13-cpe-vnext-quality-first-workflow-optimization-design.md`, especially S1.8 and S1.13.4.
- This plan makes zero credentialed, provider, network-model, billing, push, or protected-branch operations.
- Production policy and contract paths are constants; alternate paths exist only inside isolated test helpers.
- Worktree or index bytes never authorize a release decision.
- Plan 1 defines R3 contracts but does not issue the final R3 verdict or R2 live proof.
- Every task uses focused RED/GREEN checks and one independently reviewable commit.

## File Structure

- `scripts/cpe_runtime/git_objects.py`: exact commit/blob reads and immutable `TrustRoot`.
- `scripts/cpe_runtime/release_policy_vnext.py`: fixed release policy validation over Git-object bytes.
- `scripts/cpe_runtime/release_closure.py`: deterministic closure phase and review-artifact contracts.
- `evals/check_release_trust_vnext.py`: mutation and pre-provider fail-closed cases.
- `evals/check_release_closure_vnext.py`: closure transition and review-reducer cases.

---

### Task 1: Read Fixed Trust Anchors From Exact Git Objects

```yaml
task_type: tdd_implementation
dependencies: []
spec_refs: ["S1.8.2", "S1.13.4"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/git_objects.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/release_policy_vnext.py
  - skills/kws-codex-plan-executor/evals/live-migration/release-policy-vnext.json
  - skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py
operator_reviewed: true
operator_decision: Approved local trust-boundary implementation; provider calls, billing changes, remote writes, and live proof remain forbidden in Plan 1.
```

**Files:** Create the three files listed above.

**Interfaces:** Produces `GitObjectSource.read_blob(commit: str, path: str) -> GitBlob`, `TrustRoot`, `load_trust_root(repository: Path, reviewed_commit: str) -> TrustRoot`, and `TrustRoot.body() -> dict[str, str]`.

- [ ] **Step 1: Write the failing trust-source check**

```python
root = load_trust_root(repo, reviewed_commit)
assert root.policy.path == "skills/kws-codex-plan-executor/evals/live-migration/release-policy-vnext.json"
assert root.policy.blob_oid == git(repo, "rev-parse", f"{reviewed_commit}:{root.policy.path}")
assert root.policy.sha256 == hashlib.sha256(git_bytes(repo, "show", f"{reviewed_commit}:{root.policy.path}")).hexdigest()
assert root.trust_root_sha256 == sha256_bytes(canonical_json(root.body()))
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'cpe_runtime.git_objects'`.

- [ ] **Step 3: Implement the immutable types and fixed loader**

```python
@dataclass(frozen=True)
class GitBlob:
    path: str
    blob_oid: str
    sha256: str
    content: bytes

@dataclass(frozen=True)
class TrustRoot:
    reviewed_commit: str
    reviewed_tree: str
    policy: GitBlob
    dogfood_contract: GitBlob
    trust_root_sha256: str

def load_trust_root(repository: Path, reviewed_commit: str) -> TrustRoot:
    source = GitObjectSource(repository)
    policy = source.read_blob(reviewed_commit, POLICY_PATH)
    payload = validate_policy_bytes(policy.content)
    contract = source.read_blob(reviewed_commit, str(payload["dogfood_task_contract_path"]))
    return TrustRoot.build(reviewed_commit, source.tree(reviewed_commit), policy, contract)
```

`POLICY_PATH` is the fixed repository-relative vNext policy path above. The
tracked JSON keeps the reviewed dogfood contract path, `2/4/6` ceilings, and
exact release labels.

- [ ] **Step 4: Run GREEN and mutation cases**

Run: `python3 skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py`

Expected: PASS for clean objects and pre-call rejection of dirty, staged, alternate-path, wrong-commit, missing-object, and post-load worktree mutation cases.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/git_objects.py skills/kws-codex-plan-executor/scripts/cpe_runtime/release_policy_vnext.py skills/kws-codex-plan-executor/evals/live-migration/release-policy-vnext.json skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py
git commit -m "feat(cpe): bind vnext release trust to git objects"
```

### Task 2: Bind TrustRoot Through Release Evidence

```yaml
task_type: tdd_implementation
dependencies: ["T1"]
spec_refs: ["S1.8.2", "S1.8.3"]
file_claims:
  - skills/kws-codex-plan-executor/evals/live_migration/compiler.py
  - skills/kws-codex-plan-executor/evals/live_migration/ledger.py
  - skills/kws-codex-plan-executor/evals/live_migration/runner.py
  - skills/kws-codex-plan-executor/evals/live_migration/release_transaction.py
  - skills/kws-codex-plan-executor/evals/live_model_runner.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/dogfood_v4.py
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/public_result.py
  - skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py
operator_reviewed: true
operator_decision: Approved local release-evidence binding changes; the guarded live runner may be edited and tested with fakes but may not make a credentialed call.
```

**Files:** Modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Consumes `TrustRoot.body()` and produces `trust_root_sha256` on manifest, slot registration, ledger events, dogfood evidence, terminal generation, and `validate_release_evidence_root()`. The guarded live CLI accepts only `--matrix vnext` for the new proof path.

- [ ] **Step 1: Add failing cross-binding assertions**

```python
assert manifest["trust_root"] == trust_root.body()
assert ledger_state["trust_root_sha256"] == trust_root.trust_root_sha256
assert generation["trust_root_sha256"] == trust_root.trust_root_sha256
assert validate_release_evidence_root(root)["passed"] is True
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py`

Expected: FAIL because release artifacts do not contain `trust_root_sha256`.

- [ ] **Step 3: Thread one binding through production functions**

```python
def bind_trust_root(payload: dict[str, object], trust_root: TrustRoot) -> dict[str, object]:
    return {**payload, "trust_root": trust_root.body(), "trust_root_sha256": trust_root.trust_root_sha256}

def require_trust_root(payload: Mapping[str, object], expected: TrustRoot) -> None:
    if payload.get("trust_root_sha256") != expected.trust_root_sha256:
        raise ValueError("release_trust_root_mismatch")
```

- [ ] **Step 4: Run focused release checks**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_release_trust_vnext.py && python3 evals/check_release_transaction_v4.py && python3 evals/check_quality_matrix_v4.py`

Expected: all pass; fake-provider invocation count remains zero for every trust mutation.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/evals/live_migration skills/kws-codex-plan-executor/evals/live_model_runner.py skills/kws-codex-plan-executor/scripts/cpe_runtime/dogfood_v4.py skills/kws-codex-plan-executor/scripts/cpe_runtime/public_result.py skills/kws-codex-plan-executor/evals/check_release_trust_vnext.py
git commit -m "feat(cpe): propagate vnext trust root through release evidence"
```

### Task 3: Define Closure Phases And Four-Lane Review Contracts

```yaml
task_type: tdd_implementation
dependencies: ["T2"]
spec_refs: ["S1.8.3", "S1.8.4", "S1.12"]
file_claims:
  - skills/kws-codex-plan-executor/scripts/cpe_runtime/release_closure.py
  - skills/kws-codex-plan-executor/templates/integration-review-vnext.schema.json
  - skills/kws-codex-plan-executor/evals/check_release_closure_vnext.py
acceptance:
  - python3 skills/kws-codex-plan-executor/evals/check_release_closure_vnext.py
operator_reviewed: true
```

**Files:** Create exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces `ClosurePhase`, `ReviewFinding`, `ReviewLaneReport`, `ConsolidatedReview`, `next_closure_phase()`, and `consolidate_review_lanes()`.

- [ ] **Step 1: Write failing transition and deduplication checks**

```python
assert next_closure_phase("trust_ready", "runtime_frozen") == "review_pending"
review = consolidate_review_lanes(reports, checkpoint_sha256=checkpoint)
assert [finding.invariant_id for finding in review.findings] == ["trust.git_object_binding"]
assert review.repair_waves_allowed == 1
```

- [ ] **Step 2: Run RED**

Run: `python3 skills/kws-codex-plan-executor/evals/check_release_closure_vnext.py`

Expected: FAIL because `release_closure.py` does not exist.

- [ ] **Step 3: Implement the closed phase table and reducer**

```python
PHASES = {
    ("trust_ready", "runtime_frozen"): "review_pending",
    ("review_pending", "review_passed"): "cost_free_pending",
    ("cost_free_pending", "cost_free_passed"): "live_proof_pending",
    ("live_proof_pending", "live_proved"): "closeout_pending",
    ("closeout_pending", "metadata_verified"): "closed",
}

def consolidate_review_lanes(reports, *, checkpoint_sha256: str) -> ConsolidatedReview:
    require_exact_lanes(reports, {"state_crash", "trust_privacy", "cli_dataflow", "release_lineage"})
    return ConsolidatedReview.from_invariant_groups(reports, checkpoint_sha256, repair_waves_allowed=1)
```

- [ ] **Step 4: Run GREEN and schema validation**

Run: `python3 skills/kws-codex-plan-executor/evals/check_release_closure_vnext.py`

Expected: PASS for legal phases, duplicate invariant reduction, checkpoint mismatch rejection, missing lane rejection, and second fix-wave rejection.

- [ ] **Step 5: Commit**

```bash
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/release_closure.py skills/kws-codex-plan-executor/templates/integration-review-vnext.schema.json skills/kws-codex-plan-executor/evals/check_release_closure_vnext.py
git commit -m "feat(cpe): define vnext release closure contracts"
```

### Task 4: Register Deterministic Checks And Record Plan 1 Checkpoint

```yaml
task_type: documentation
dependencies: ["T3"]
spec_refs: ["S1.8", "S1.13.4", "S1.14"]
file_claims:
  - skills/kws-codex-plan-executor/evals/maintained-checks.json
  - skills/kws-codex-plan-executor/docs/evals-and-verification.md
  - skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md
  - skills/kws-codex-plan-executor/docs/verification-log.md
  - graphify-out/GRAPH_REPORT.md
  - graphify-out/graph.json
acceptance:
  - cd skills/kws-codex-plan-executor && ./evals/run.sh
operator_reviewed: true
```

**Files:** Modify exactly the paths declared in this task YAML `file_claims`; do not touch undeclared paths.

**Interfaces:** Produces the Plan 1 verified checkpoint consumed by Plan 2. It closes R1 but records R2 and final R3 as Program Final Gate work.

- [ ] **Step 1: Register both focused checks**

Add `check_release_trust_vnext.py` and `check_release_closure_vnext.py` to `evals/maintained-checks.json` with explicit `deterministic` classification.

- [ ] **Step 2: Run the complete cost-free CPE gate**

Run: `cd skills/kws-codex-plan-executor && ./evals/run.sh`

Expected: exit 0 with `paid_execution=skipped_not_approved`.

- [ ] **Step 3: Run repository and hygiene checks**

Run: `bun run check && git diff --check`

Expected: both exit 0.

- [ ] **Step 4: Update active risk and verification docs, then refresh Graphify**

Record R1 as closed at the exact commit; retain R2/R3 as Program Final Gate pending. Run `graphify update .` and `python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran`.

Expected: `fresh=true` with no errors.

- [ ] **Step 5: Commit the Plan 1 checkpoint**

```bash
git add skills/kws-codex-plan-executor/evals/maintained-checks.json skills/kws-codex-plan-executor/docs graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs(cpe): record vnext trust foundation checkpoint"
```
