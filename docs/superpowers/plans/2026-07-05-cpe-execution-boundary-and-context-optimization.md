# CPE Execution Boundary And Context Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent accepted CPE subagent results from escaping the execution
worktree, reduce repeated full-spec packet cost, and split durable run quality
from inspection-only observations.

**Architecture:** Add schema-aware boundary attestation and attempt lineage to
`subagent_runs` while preserving compatibility for older finished states. Then
improve task packet spec mapping and run-quality inspection output using
existing Python scripts and deterministic evals. State JSON remains
authoritative; task packet markdown and recent-run reports remain derived
evidence.

**Tech Stack:** Python 3 standard library, existing `skills/kws-codex-plan-executor` scripts/evals, Bash eval harness, Markdown contract docs, Graphify command evidence.

## Global Constraints

- Do not change `completion_audit.passed` semantics.
- Do not change `subagents=on` default or bypass active Codex spawn policy.
- Do not automatically rewrite old finished `state.json` files.
- Do not make AgentLens unavailable a release blocker.
- Do not forbid full-spec fallback globally.
- Do not revive `components/agentlens/`.
- Keep repository mutations in `~/.codex/worktrees/<run_id>` and orchestration state in `~/.codex/orchestrator/<run_id>`.
- Keep task packet JSON and `state.json` as the source of truth.
- Use only Python standard library in CPE scripts and evals.
- Add deterministic eval coverage before implementation code for each behavior change.
- Preserve existing `validate_state.py` CLI behavior for older valid states.

---

## File Structure

- Modify `skills/kws-codex-plan-executor/scripts/validate_state.py`
  - Owns state-contract validation for boundary attestation, source workspace drift, and subagent attempt lineage.
- Modify `skills/kws-codex-plan-executor/evals/check_state_schema.py`
  - Covers accepted delegated runs with and without boundary evidence, boundary mismatch, source workspace drift, and duplicate final attempts.
- Modify `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
  - Owns new stable followup for duplicate final subagent attempts and report taxonomy classification.
- Modify `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
  - Exposes duplicate-final-attempt count and inspection observation summary in replay output.
- Modify `skills/kws-codex-plan-executor/scripts/inspect_runs.py`
  - Computes inspection-only observations separately from durable `run_quality.open_followups`.
- Modify `skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py`
  - Aggregates durable followups and current inspection observations separately.
- Modify `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
  - Covers duplicate-attempt operational debt and finished missing-worktree informational behavior.
- Modify `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`
  - Covers recent-run aggregation of durable followups versus inspection observations.
- Modify `skills/kws-codex-plan-executor/evals/check_inspect_runs.py`
  - Covers `inspection_observations` shape from read-only inspection.
- Modify `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
  - Improves weak heuristic candidate scoring, emits `suggested_plan_patch`, and adds bounded spec preview metadata for fallback packets.
- Modify `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
  - Surfaces `suggested_plan_patch` and bounded fallback metadata in readiness issues.
- Modify `skills/kws-codex-plan-executor/scripts/render_task_packet_view.py`
  - Shows fallback reason, candidate refs, plan patch, and preview metadata without dumping the full fallback body.
- Modify `skills/kws-codex-plan-executor/evals/check_task_packet.py`
  - Covers stronger candidate refs and bounded fallback metadata.
- Modify `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
  - Covers readiness issue fields for suggested plan patches.
- Modify `skills/kws-codex-plan-executor/evals/check_task_packet_view.py`
  - Covers human-readable fallback warning without full-spec body expansion.
- Modify `skills/kws-codex-plan-executor/SKILL.md`
  - Documents boundary attestation, attempt lineage, and observation split.
- Modify `skills/kws-codex-plan-executor/references/subagent-run-store.md`
  - Documents boundary attestation and final attempt rules.
- Modify `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
  - Documents parent accept boundary checks after dispatch.
- Modify `skills/kws-codex-plan-executor/references/state-schema.md`
  - Documents new state fields, compatibility marker, and validation rules.
- Modify `skills/kws-codex-plan-executor/docs/state-and-logging.md`
  - Documents durable run quality versus inspection observations.
- Modify `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
  - Documents new deterministic eval coverage.
- Modify `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
  - Records remaining environment/tool-policy limitations.
- Modify `skills/kws-codex-plan-executor/ARCHITECTURE.md`
  - Updates ownership diagram and state surfaces.
- Modify `skills/kws-codex-plan-executor/HISTORY.md`
  - Records the behavior change.

---

### Task 1: Subagent Boundary Attestation

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/references/subagent-run-store.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`

**Interfaces:**
- Consumes: top-level state fields `subagent_boundary_schema_version`, `execution_worktree`, `source_workspace`.
- Consumes: `subagent_runs[].boundary_attestation`.
- Produces: validation errors for accepted delegated runs whose worker cwd/git root does not match `execution_worktree`.
- Produces: compatibility rule where older states without `subagent_boundary_schema_version` stay readable.

- [ ] **Step 1: Write RED tests for strict boundary validation**

Append these helper functions to `skills/kws-codex-plan-executor/evals/check_state_schema.py` after `completed_task_subagent_run()`:

```python
def boundary_attestation(*, match: bool = True, source_unchanged: bool = True) -> dict:
    root = worktree() if match else "/tmp/codex-home/source/Archive"
    return {
        "schema_version": "1",
        "execution_worktree": worktree(),
        "worker_cwd": root,
        "worker_git_root": root,
        "worker_head_before": "a" * 40,
        "worker_head_after": "b" * 40,
        "source_workspace": "/tmp/codex-home/source/Archive",
        "source_workspace_head_before": "c" * 40,
        "source_workspace_head_after": "c" * 40 if source_unchanged else "d" * 40,
        "execution_worktree_match": match,
        "source_workspace_unchanged": source_unchanged,
        "dirty_scope_after": [],
    }


def boundary_state() -> dict:
    state = v220_state()
    state["subagent_boundary_schema_version"] = "1"
    state["source_workspace"] = "/tmp/codex-home/source/Archive"
    state["execution_worktree"] = state["worktree"]
    run = completed_task_subagent_run()
    run["id"] = "agent_boundary"
    run["boundary_attestation"] = boundary_attestation()
    run["accepted_as_final"] = True
    state["subagent_runs"] = [run]
    state["tasks"]["task_0"]["subagent_strategy"] = {
        "mode": "delegated",
        "reason": "all pre-dispatch prerequisites passed",
        "run_ids": ["agent_boundary"],
    }
    return state
```

Append these checks inside `main()` after the existing subagent validation checks:

```python
        boundary_valid = run_validator(boundary_state())
        checks["boundary_attestation_valid_passes"] = boundary_valid.returncode == 0
        if not checks["boundary_attestation_valid_passes"]:
            failures.append("valid boundary attestation should pass")

        missing_boundary = boundary_state()
        del missing_boundary["subagent_runs"][0]["boundary_attestation"]
        missing_boundary_result = run_validator(missing_boundary)
        checks["accepted_subagent_requires_boundary_attestation"] = (
            missing_boundary_result.returncode != 0
            and "boundary_attestation required" in (missing_boundary_result.stderr + missing_boundary_result.stdout)
        )
        if not checks["accepted_subagent_requires_boundary_attestation"]:
            failures.append("accepted subagent should require boundary attestation in boundary schema states")

        mismatch_boundary = boundary_state()
        mismatch_boundary["subagent_runs"][0]["boundary_attestation"] = boundary_attestation(match=False)
        mismatch_result = run_validator(mismatch_boundary)
        checks["boundary_mismatch_fails"] = (
            mismatch_result.returncode != 0
            and "worker_git_root must match execution_worktree" in (mismatch_result.stderr + mismatch_result.stdout)
        )
        if not checks["boundary_mismatch_fails"]:
            failures.append("worker git root outside execution worktree should fail")

        source_drift = boundary_state()
        source_drift["subagent_runs"][0]["boundary_attestation"] = boundary_attestation(source_unchanged=False)
        source_drift_result = run_validator(source_drift)
        checks["source_workspace_drift_requires_override"] = (
            source_drift_result.returncode != 0
            and "source_workspace_unchanged" in (source_drift_result.stderr + source_drift_result.stdout)
        )
        if not checks["source_workspace_drift_requires_override"]:
            failures.append("source workspace drift should fail without operator override")
```

- [ ] **Step 2: Run RED for state schema**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
```

Expected: FAIL because `validate_state.py` does not yet require `boundary_attestation` for new boundary schema states.

- [ ] **Step 3: Implement boundary validation helpers**

Add these constants near the existing subagent constants in `skills/kws-codex-plan-executor/scripts/validate_state.py`:

```python
REQUIRED_BOUNDARY_ATTESTATION_FIELDS = {
    "schema_version",
    "execution_worktree",
    "worker_cwd",
    "worker_git_root",
    "worker_head_before",
    "worker_head_after",
    "source_workspace",
    "source_workspace_head_before",
    "source_workspace_head_after",
    "execution_worktree_match",
    "source_workspace_unchanged",
    "dirty_scope_after",
}
HEX_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
```

Add this helper after `_validate_strategy_override`:

```python
def _normalize_path_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.rstrip("/")


def _validate_boundary_attestation(data: dict, run: dict, prefix: str, errors: list[str]) -> None:
    strict = data.get("subagent_boundary_schema_version") == "1"
    if not strict:
        return
    if run.get("status") != "completed" or run.get("review_status") != "accepted":
        return
    attestation = run.get("boundary_attestation")
    if not isinstance(attestation, dict):
        errors.append(f"{prefix}.boundary_attestation required for accepted delegated run")
        return
    for key in sorted(REQUIRED_BOUNDARY_ATTESTATION_FIELDS):
        if key not in attestation:
            errors.append(f"{prefix}.boundary_attestation missing field {key}")
    if attestation.get("schema_version") != "1":
        errors.append(f"{prefix}.boundary_attestation.schema_version must be 1")
    execution_worktree = _normalize_path_text(data.get("execution_worktree") or data.get("worktree"))
    worker_git_root = _normalize_path_text(attestation.get("worker_git_root"))
    if execution_worktree and worker_git_root != execution_worktree:
        errors.append(f"{prefix}.boundary_attestation.worker_git_root must match execution_worktree")
    worker_cwd = _normalize_path_text(attestation.get("worker_cwd"))
    if execution_worktree and worker_cwd and not worker_cwd.startswith(execution_worktree):
        errors.append(f"{prefix}.boundary_attestation.worker_cwd must be inside execution_worktree")
    if attestation.get("execution_worktree_match") is not True:
        errors.append(f"{prefix}.boundary_attestation.execution_worktree_match must be true")
    if attestation.get("source_workspace_unchanged") is not True and not isinstance(run.get("operator_boundary_override"), dict):
        errors.append(f"{prefix}.boundary_attestation.source_workspace_unchanged requires operator_boundary_override")
    dirty_scope_after = attestation.get("dirty_scope_after")
    if not isinstance(dirty_scope_after, list):
        errors.append(f"{prefix}.boundary_attestation.dirty_scope_after must be a list")
    for sha_key in ("worker_head_before", "worker_head_after", "source_workspace_head_before", "source_workspace_head_after"):
        sha = attestation.get(sha_key)
        if not isinstance(sha, str) or HEX_SHA_RE.match(sha) is None:
            errors.append(f"{prefix}.boundary_attestation.{sha_key} must be a 40-character lowercase hex git sha")
```

Call the helper inside `_validate_subagents`, after completed-run checks:

```python
        _validate_boundary_attestation(data, run, prefix, errors)
```

Add top-level marker validation near the beginning of `_validate_operational_run_quality`:

```python
    boundary_schema = data.get("subagent_boundary_schema_version")
    if boundary_schema is not None and boundary_schema != "1":
        errors.append("subagent_boundary_schema_version must be 1 when present")
```

- [ ] **Step 4: Run GREEN for boundary tests**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
```

Expected: PASS with JSON output containing `"passed": true`.

- [ ] **Step 5: Document boundary attestation**

Update `skills/kws-codex-plan-executor/references/subagent-run-store.md` under "Record Fields" with:

```markdown
Accepted delegated records in states that set `subagent_boundary_schema_version=1`
also require `boundary_attestation`. It records `worker_cwd`, `worker_git_root`,
worker head before/after, source workspace head before/after, and booleans proving
the worker operated inside `execution_worktree` without dirtying the source
workspace. Parent review must reject accepted output when this attestation does
not match the run state.
```

Update `skills/kws-codex-plan-executor/references/state-schema.md` near the
operational-quality section with:

```markdown
`subagent_boundary_schema_version=1` opts a run into strict accepted-subagent
boundary validation. Older finished states without the marker remain readable.
When present, every accepted completed subagent run must carry
`boundary_attestation`, and the attested worker git root must match
`execution_worktree`.
```

- [ ] **Step 6: Commit Task 1**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/references/subagent-run-store.md \
  skills/kws-codex-plan-executor/references/state-schema.md
git diff --cached --check
git commit -m "feat(cpe): validate subagent boundary attestation"
```

Expected: commit succeeds.

---

### Task 2: Attempt Lineage and Duplicate Final Detection

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
- Modify: `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`
- Modify: `skills/kws-codex-plan-executor/references/subagent-run-store.md`

**Interfaces:**
- Consumes: `subagent_runs[].attempt_group`, `attempt_index`, `accepted_as_final`, `supersedes`, `superseded_by`.
- Produces: `duplicate_final_subagent_attempts` stable followup when finished state has more than one final accepted run for the same attempt group.
- Decision: do not add a new `review_status=superseded` enum in this task. Superseded attempts use existing `review_status=rejected` with `superseded_by`.

- [ ] **Step 1: Write RED tests for attempt lineage**

Append this helper to `skills/kws-codex-plan-executor/evals/check_state_schema.py` after `boundary_state()`:

```python
def duplicate_final_attempt_state() -> dict:
    state = boundary_state()
    first = dict(state["subagent_runs"][0])
    first["id"] = "agent_attempt_1"
    first["attempt_group"] = "task_0:docs/example.md"
    first["attempt_index"] = 1
    first["accepted_as_final"] = True
    first["boundary_attestation"] = boundary_attestation()
    second = dict(first)
    second["id"] = "agent_attempt_2"
    second["attempt_index"] = 2
    state["subagent_runs"] = [first, second]
    state["tasks"]["task_0"]["subagent_strategy"]["run_ids"] = ["agent_attempt_1", "agent_attempt_2"]
    return state
```

Append checks inside `main()` after boundary checks:

```python
        duplicate_final = duplicate_final_attempt_state()
        duplicate_final_result = run_validator(duplicate_final)
        checks["duplicate_final_attempts_fail"] = (
            duplicate_final_result.returncode != 0
            and "multiple final accepted subagent attempts" in (duplicate_final_result.stderr + duplicate_final_result.stdout)
        )
        if not checks["duplicate_final_attempts_fail"]:
            failures.append("multiple final accepted attempts for one attempt_group should fail")

        superseded_attempt = duplicate_final_attempt_state()
        superseded_attempt["subagent_runs"][0]["review_status"] = "rejected"
        superseded_attempt["subagent_runs"][0]["accepted_as_final"] = False
        superseded_attempt["subagent_runs"][0]["superseded_by"] = "agent_attempt_2"
        superseded_attempt["tasks"]["task_0"]["subagent_strategy"]["run_ids"] = ["agent_attempt_2"]
        superseded_result = run_validator(superseded_attempt)
        checks["superseded_attempt_lineage_passes"] = superseded_result.returncode == 0
        if not checks["superseded_attempt_lineage_passes"]:
            failures.append("rejected superseded attempt plus one final accepted run should pass")
```

- [ ] **Step 2: Run RED for attempt lineage**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
```

Expected: FAIL because duplicate final attempts are not yet rejected.

- [ ] **Step 3: Implement attempt lineage validation**

Add this helper after `_validate_boundary_attestation` in `validate_state.py`:

```python
def _attempt_group_for(run: dict) -> str:
    value = run.get("attempt_group")
    if isinstance(value, str) and value.strip():
        return value
    owner = str(run.get("owner_task") or "")
    scope = ",".join(item for item in run.get("write_scope", []) if isinstance(item, str))
    return f"{owner}:{scope}"


def _validate_attempt_lineage(runs: list[dict], errors: list[str]) -> None:
    final_by_group: dict[str, list[str]] = {}
    ids = {str(run.get("id")) for run in runs if isinstance(run, dict) and _has_substantive_value(run.get("id"))}
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        prefix = f"subagent_runs[{index}]"
        accepted_as_final = run.get("accepted_as_final")
        if accepted_as_final is not None and not isinstance(accepted_as_final, bool):
            errors.append(f"{prefix}.accepted_as_final must be a boolean")
        attempt_index = run.get("attempt_index")
        if attempt_index is not None and (not isinstance(attempt_index, int) or attempt_index < 1):
            errors.append(f"{prefix}.attempt_index must be a positive integer")
        superseded_by = run.get("superseded_by")
        if superseded_by is not None and str(superseded_by) not in ids:
            errors.append(f"{prefix}.superseded_by must reference another subagent run id")
        if run.get("review_status") == "accepted" and accepted_as_final is not False:
            final_by_group.setdefault(_attempt_group_for(run), []).append(str(run.get("id")))
    for group, run_ids in final_by_group.items():
        if len(run_ids) > 1:
            errors.append(f"multiple final accepted subagent attempts for {group}: {', '.join(run_ids)}")
```

Call it once at the end of `_validate_subagents`, after active scope overlap validation:

```python
    _validate_attempt_lineage([run for run in runs if isinstance(run, dict)], errors)
```

- [ ] **Step 4: Add operational debt for legacy duplicate finals**

Add a constant to `run_quality_debt.py`:

```python
DUPLICATE_FINAL_SUBAGENT_ATTEMPTS = "duplicate_final_subagent_attempts"
```

Add it to `STABLE_FOLLOWUP_ORDER` after `DELEGATION_POLICY_MISSING_DISPATCH_EVIDENCE`.

Add helper functions:

```python
def duplicate_final_attempt_count(state: dict[str, Any]) -> int:
    runs = state.get("subagent_runs")
    if not isinstance(runs, list):
        return 0
    groups: dict[str, int] = {}
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("status") != "completed" or run.get("review_status") != "accepted":
            continue
        if run.get("accepted_as_final") is False:
            continue
        owner = str(run.get("owner_task") or "")
        scope = ",".join(item for item in run.get("write_scope", []) if isinstance(item, str))
        group = str(run.get("attempt_group") or f"{owner}:{scope}")
        groups[group] = groups.get(group, 0) + 1
    return sum(count - 1 for count in groups.values() if count > 1)
```

Add to `stable_followups`:

```python
    if duplicate_final_attempt_count(state) > 0:
        found.add(DUPLICATE_FINAL_SUBAGENT_ATTEMPTS)
```

Add to the actionable set inside `followup_taxonomy`:

```python
            DUPLICATE_FINAL_SUBAGENT_ATTEMPTS,
```

- [ ] **Step 5: Expose duplicate count in replay**

Modify `normalize_cpe_run.py` to import or access `run_quality_debt.duplicate_final_attempt_count` through the existing imported module and add:

```python
        "duplicate_final_subagent_attempt_count": run_quality_debt.duplicate_final_attempt_count(state),
```

inside the normalized return object.

Update `evals/check_cpe_replay.py` with a state containing two accepted same-scope runs and assert:

```python
        replay.get("duplicate_final_subagent_attempt_count") == 1
        and "duplicate_final_subagent_attempts" in replay.get("open_followups", [])
```

- [ ] **Step 6: Run GREEN for lineage and replay**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
python3 evals/check_operational_run_quality.py
python3 evals/check_cpe_replay.py
```

Expected: all three commands pass.

- [ ] **Step 7: Document attempt lineage**

Update `references/subagent-run-store.md` with:

```markdown
When multiple attempts target the same task and write scope, records should share
`attempt_group` and increment `attempt_index`. Finished state can keep rejected
or superseded attempts for audit history, but only one completed accepted record
per attempt group may be final. This plan uses the existing `review_status=rejected`
plus `superseded_by` for superseded attempts; it does not introduce a new review
status enum.
```

- [ ] **Step 8: Commit Task 2**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/scripts/run_quality_debt.py \
  skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py \
  skills/kws-codex-plan-executor/evals/check_cpe_replay.py \
  skills/kws-codex-plan-executor/references/subagent-run-store.md
git diff --cached --check
git commit -m "feat(cpe): track subagent attempt lineage"
```

Expected: commit succeeds.

---

### Task 3: Spec Mapping Optimizer and Bounded Fallback Packets

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/scripts/render_task_packet_view.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_task_packet_view.py`

**Interfaces:**
- Consumes: parsed plan task fields `title`, `body`, `files`, `acceptance_command`, `spec_refs`.
- Produces: `spec.mapping.suggested_spec_refs`, `suggested_plan_patch`, `next_action`, `fallback_preview`.
- Produces: bounded readiness/dispatch context metadata while preserving full spec recoverability through `source_path` and `sha256`.

- [ ] **Step 1: Write RED tests for stronger fallback suggestions**

In `evals/check_task_packet.py`, extend the existing fallback fixture by changing the manifest sections to include a partial billing candidate:

```python
            "S3": {
                "id": "S3",
                "title": "Billing Workflow",
                "level": 1,
                "line_start": 7,
                "line_end": 9,
                "chars": 32,
                "sha256": "z",
                "signals": {"title_tokens": ["billing", "workflow"]},
            },
```

Add `S3` to `section_order` and append billing text to `spec_text`:

```python
spec_text = "# Feature\nfeature text\n\n# Auth Session\nauth session text\n\n# Billing Workflow\nbilling workflow text\n"
```

Replace the fallback mapping check with:

```python
        checks["fallback_mapping_reason_and_suggestions"] = (
            fallback_mapping.get("fallback_reason") == "weak_heuristic_match"
            and fallback_mapping.get("suggested_spec_refs") == ["S3"]
            and fallback_mapping.get("suggested_plan_patch") == 'spec_refs: ["S3"]'
            and fallback_mapping.get("next_action") == "Add explicit spec_refs to the plan task using one of: S3"
            and fallback_mapping.get("operator_reviewed") is False
        )
```

Add a bounded preview assertion:

```python
        checks["fallback_preview_is_bounded"] = (
            isinstance(fallback_mapping.get("fallback_preview"), dict)
            and fallback_mapping["fallback_preview"].get("source_ref") == "*"
            and isinstance(fallback_mapping["fallback_preview"].get("chars"), int)
            and fallback_mapping["fallback_preview"].get("chars") <= 1200
        )
        if not checks["fallback_preview_is_bounded"]:
            failures.append("fallback mapping should include bounded preview metadata")
```

- [ ] **Step 2: Write RED tests for readiness and markdown view**

In `evals/check_run_readiness.py`, update the full-spec fallback fixture expectation:

```python
        checks["full_spec_fallback_has_reason"] = (
            fallback_issue.get("fallback_reason") == "missing_spec_refs"
            and fallback_issue.get("suggested_spec_refs") == ["problem", "goals"]
            and fallback_issue.get("suggested_plan_patch") == 'spec_refs: ["problem", "goals"]'
            and fallback_issue.get("next_action") == "Add explicit spec_refs to the plan task using one of: problem, goals"
        )
```

In `evals/check_task_packet_view.py`, assert the markdown contains `Suggested plan patch` and does not contain the repeated full spec marker more than once:

```python
        checks["full_spec_fallback_view_has_patch"] = (
            result.returncode == 0
            and "Suggested plan patch" in text
            and text.count("full spec fallback") == 1
        )
        if not checks["full_spec_fallback_view_has_patch"]:
            failures.append("task packet view should show suggested plan patch without repeating full spec body")
```

- [ ] **Step 3: Run RED for packet behavior**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
python3 evals/check_task_packet_view.py
```

Expected: FAIL because `suggested_plan_patch` and `fallback_preview` are not emitted yet.

- [ ] **Step 4: Implement stronger token scoring and plan patch output**

In `build_task_packet.py`, add this helper after `path_tokens`:

```python
def task_search_tokens(task: dict) -> set[str]:
    tokens = path_tokens([item for item in task.get("files", []) if isinstance(item, str)])
    for key in ("title", "body", "acceptance_command"):
        value = task.get(key)
        if isinstance(value, str):
            tokens.update(tokenize(value))
    return tokens
```

Modify `score_section` so it uses `task_search_tokens(task)` instead of only file tokens:

```python
    file_tokens = path_tokens(files)
    search_tokens = task_search_tokens(task)
```

Replace the title token scoring block with:

```python
    title_tokens = set(signals.get("title_tokens", [])) or tokenize(str(section.get("title", "")))
    overlap = title_tokens.intersection(search_tokens)
    if title_tokens and title_tokens.issubset(search_tokens):
        score += 2
        reasons.append("title_token")
    elif overlap:
        score += 1
        reasons.append("partial_title_token")
```

Add helpers after `suggested_spec_refs`:

```python
def suggested_plan_patch(refs: list[str]) -> str:
    escaped = ", ".join(json.dumps(ref, ensure_ascii=False) for ref in refs)
    return f"spec_refs: [{escaped}]"


def bounded_preview(text: str, *, max_chars: int = 1200) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[truncated]"
```

Update fallback mapping in `resolve_sections`:

```python
    patch = suggested_plan_patch(refs) if refs else ""
    return ["*"], True, {
        "selected_section_ids": ["*"],
        "candidate_scores": candidate_scores,
        "mapping_reason": "No task-specific spec section matched; using full spec fallback.",
        "requires_parent_mapping": True,
        "source": "fallback",
        "fallback_reason": reason,
        "suggested_spec_refs": refs,
        "suggested_plan_patch": patch,
        "next_action": fallback_next_action(reason, refs),
        "operator_reviewed": False,
    }
```

Update `spec_context` to return full text for execution compatibility, but add preview metadata in `build_packet` after `spec_text` is computed:

```python
    if fallback_used:
        mapping["fallback_preview"] = {
            "source_ref": "*",
            "chars": min(len(spec_text), 1200),
            "sha256": sha256_text(spec_text),
            "text": bounded_preview(spec_text),
        }
```

- [ ] **Step 5: Surface patch in readiness**

In `audit_run_readiness.py`, add `suggested_plan_patch` to the full-spec fallback issue payload:

```python
                suggested_plan_patch=mapping.get("suggested_plan_patch") or "",
```

- [ ] **Step 6: Surface patch in task packet markdown**

In `render_task_packet_view.py`, where the full-spec fallback warning is rendered, include:

```python
    suggested_patch = mapping.get("suggested_plan_patch") if isinstance(mapping, dict) else ""
    if isinstance(suggested_patch, str) and suggested_patch.strip():
        lines.append(f"- Suggested plan patch: `{suggested_patch}`")
```

Keep the existing source-of-truth JSON link and do not render `spec.text` for fallback mode.

- [ ] **Step 7: Run GREEN for packet behavior**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
python3 evals/check_task_packet_view.py
```

Expected: all three commands pass.

- [ ] **Step 8: Commit Task 3**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/build_task_packet.py \
  skills/kws-codex-plan-executor/scripts/audit_run_readiness.py \
  skills/kws-codex-plan-executor/scripts/render_task_packet_view.py \
  skills/kws-codex-plan-executor/evals/check_task_packet.py \
  skills/kws-codex-plan-executor/evals/check_run_readiness.py \
  skills/kws-codex-plan-executor/evals/check_task_packet_view.py
git diff --cached --check
git commit -m "feat(cpe): improve spec fallback guidance"
```

Expected: commit succeeds.

---

### Task 4: Run Quality Observation Split

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/inspect_runs.py`
- Modify: `skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py`
- Modify: `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
- Modify: `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_inspect_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

**Interfaces:**
- Consumes: existing durable `run_quality.open_followups`.
- Produces: read-only `inspection_observations` in `inspect_runs.py` output.
- Produces: separate aggregate fields `durable_actionable_followup_count`, `inspection_observation_count`, and `finished_missing_worktree_info_count`.

- [ ] **Step 1: Write RED tests for inspection observations**

In `evals/check_inspect_runs.py`, add an assertion to the finished missing-worktree fixture:

```python
        quality = finished_record.get("run_quality", {})
        observations = quality.get("inspection_observations", {})
        checks["finished_missing_worktree_is_observation"] = (
            observations.get("observed_after_completion") is True
            and observations.get("missing_execution_worktree") is True
            and observations.get("display_class") == "green-with-info"
            and "missing_execution_worktree" not in quality.get("operational_debt", {}).get("followups", [])
        )
        if not checks["finished_missing_worktree_is_observation"]:
            failures.append("finished missing worktree should be an inspection observation, not durable debt")
```

In `evals/check_recent_run_rubric.py`, add:

```python
        checks["separates_inspection_observations"] = (
            summary.get("inspection_observation_count", 0) >= 0
            and "durable_actionable_followup_count" in summary
        )
```

- [ ] **Step 2: Run RED for inspection split**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_inspect_runs.py
python3 evals/check_recent_run_rubric.py
```

Expected: FAIL because `inspection_observations` and the new summary fields do not exist.

- [ ] **Step 3: Implement observation helper in `inspect_runs.py`**

Add this helper after `validation_result`:

```python
def inspection_observations(*, terminal: bool, missing_worktree: bool, observed_after_completion: bool) -> dict[str, Any]:
    display_class = "green"
    if missing_worktree and terminal and observed_after_completion:
        display_class = "green-with-info"
    elif missing_worktree:
        display_class = "yellow"
    return {
        "schema_version": "1",
        "missing_execution_worktree": missing_worktree,
        "observed_after_completion": observed_after_completion,
        "display_class": display_class,
    }
```

In `run_quality`, compute:

```python
    observed_after_completion = terminal and current_followups != base_followups
    observations = inspection_observations(
        terminal=terminal,
        missing_worktree=missing_worktree,
        observed_after_completion=observed_after_completion,
    )
```

Do not add `missing_execution_worktree` to `operational_debt` when `terminal` is `True`. Keep it in `open_followups` for backward display compatibility, but set:

```python
        "inspection_observations": observations,
```

inside the returned `run_quality` object.

- [ ] **Step 4: Update taxonomy for finished missing worktree**

In `run_quality_debt.followup_taxonomy`, keep existing behavior where finished missing worktree is informational:

```python
        elif item == MISSING_EXECUTION_WORKTREE:
            if terminal == "finished" and missing_execution_worktree is True:
                informational.append(item)
            else:
                actionable.append(item)
```

Ensure `operational_debt_summary` receives `missing_execution_worktree=False` for finished inspection-only observations in `inspect_runs.py`.

- [ ] **Step 5: Update recent-run aggregation**

In `analyze_recent_runs.py`, add helpers:

```python
def inspection_observation_count(item: dict[str, Any]) -> int:
    observations = item.get("inspection_observations")
    if not isinstance(observations, dict):
        return 0
    return int(any(value is True for key, value in observations.items() if key != "observed_after_completion"))
```

Add summary fields:

```python
        "durable_actionable_followup_count": summary["actionable_followup_count"],
        "inspection_observation_count": sum(inspection_observation_count(item) for item in runs),
```

Update `normalize_cpe_run.py` to copy `run_quality.inspection_observations` when present:

```python
        "inspection_observations": quality.get("inspection_observations") if isinstance(quality.get("inspection_observations"), dict) else {},
```

- [ ] **Step 6: Run GREEN for inspection split**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_inspect_runs.py
python3 evals/check_recent_run_rubric.py
python3 evals/check_operational_run_quality.py
```

Expected: all commands pass.

- [ ] **Step 7: Commit Task 4**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/inspect_runs.py \
  skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py \
  skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py \
  skills/kws-codex-plan-executor/scripts/run_quality_debt.py \
  skills/kws-codex-plan-executor/evals/check_inspect_runs.py \
  skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git diff --cached --check
git commit -m "feat(cpe): split inspection observations from run debt"
```

Expected: commit succeeds.

---

### Task 5: Contract Docs, Baseline, and Full Verification

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/references/subagent-run-store.md`
- Modify: `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`

**Interfaces:**
- Consumes: implementation artifacts from Tasks 1-4.
- Produces: updated skill contract and verification evidence for release closeout.

- [ ] **Step 1: Update skill contract docs**

In `skills/kws-codex-plan-executor/SKILL.md`, add bullets to Core Invariants:

```markdown
- Finished states that opt into `subagent_boundary_schema_version=1` require
  accepted delegated `subagent_runs` to carry `boundary_attestation` proving the
  worker operated inside `execution_worktree` and did not dirty the source
  workspace unless an explicit operator override is recorded.
- Finished states cannot present multiple final accepted subagent attempts for
  the same task/write scope; superseded attempts remain inspectable as rejected
  records with `superseded_by`.
- Read-only inspection may attach `inspection_observations` such as a finished
  missing execution worktree without rewriting durable run quality state.
```

- [ ] **Step 2: Update reference docs**

Add concise sections to:

`references/pre-dispatch-pipeline.md`:

```markdown
Parent acceptance is separate from pre-dispatch. A `delegate` decision only
authorizes spawning. Before accepting worker output, the parent records boundary
attestation, runs the diff-scope check from the execution worktree, and confirms
the source workspace did not receive unexpected commits or dirty files.
```

`docs/state-and-logging.md`:

```markdown
`inspection_observations` are read-only inspection facts. They explain current
filesystem observations such as a removed execution worktree after a finished
run. They do not replace durable `state.json`, `completion_audit`, or task
acceptance evidence.
```

`docs/risks-limitations-deferrals.md`:

```markdown
Boundary attestation proves parent-accepted worker output was reviewed against
the expected execution worktree. It does not install or manage the external
subagent runtime. AgentLens remains best-effort, and old finished states remain
readable even when they predate boundary attestation.
```

- [ ] **Step 3: Update eval coverage docs**

In `docs/evals-and-verification.md`, add:

```markdown
Boundary and lineage coverage:

- `check_state_schema.py` rejects accepted delegated runs without boundary
  attestation when `subagent_boundary_schema_version=1`.
- `check_state_schema.py` rejects worker git roots outside the execution
  worktree and source workspace drift without operator override.
- `check_operational_run_quality.py` and `check_cpe_replay.py` keep duplicate
  final subagent attempts visible as actionable operational debt.
- `check_inspect_runs.py` keeps finished missing worktrees as inspection
  observations rather than durable product-verification failures.
```

- [ ] **Step 4: Update history**

Add an entry to the top of `HISTORY.md`:

```markdown
## Unreleased

- Added schema-aware subagent boundary attestation for accepted delegated runs.
- Added attempt-lineage validation so finished state has at most one final
  accepted attempt per task/write scope.
- Improved full-spec fallback guidance with candidate spec refs and suggested
  plan patches.
- Split read-only inspection observations from durable run-quality debt.
```

- [ ] **Step 5: Run focused verification bundle**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
python3 evals/check_operational_run_quality.py
python3 evals/check_cpe_replay.py
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
python3 evals/check_task_packet_view.py
python3 evals/check_inspect_runs.py
python3 evals/check_recent_run_rubric.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

Expected: all commands pass.

- [ ] **Step 6: Run release contract and full harness**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_release_contract.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 scripts/audit_superpowers_compatibility.py \
  --superpowers-root /Users/kws/.codex/skills \
  --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
```

Expected:

- `check_release_contract.py` passes.
- `check_skill_contract.py --skill SKILL.md` passes.
- Compatibility audit recommends `thin_stateful_bridge`.
- `./evals/run.sh` reports all CPE evals passing.

- [ ] **Step 7: Run repo-level checks and Graphify**

Run:

```bash
cd /Users/kws/source/private/Archive
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root /Users/kws/source/private/Archive \
  --update-ran \
  --output /tmp/cpe-boundary-graphify-audit.json
bun run check
git diff --check
```

Expected:

- Graphify update succeeds.
- Graphify freshness JSON contains `"fresh": true`.
- `bun run check` passes.
- `git diff --check` passes.

- [ ] **Step 8: Update verification log**

Append this entry to `skills/kws-codex-plan-executor/docs/verification-log.md` with the actual command outcomes:

```markdown
## 2026-07-05 - Execution boundary and context optimization

- `python3 evals/check_state_schema.py` - PASS.
- `python3 evals/check_operational_run_quality.py` - PASS.
- `python3 evals/check_cpe_replay.py` - PASS.
- `python3 evals/check_task_packet.py` - PASS.
- `python3 evals/check_run_readiness.py` - PASS.
- `python3 evals/check_task_packet_view.py` - PASS.
- `python3 evals/check_inspect_runs.py` - PASS.
- `python3 evals/check_recent_run_rubric.py` - PASS.
- `python3 -m py_compile scripts/*.py evals/*.py` - PASS.
- `bash -n evals/run.sh` - PASS.
- `python3 evals/check_release_contract.py` - PASS.
- `python3 evals/check_skill_contract.py --skill SKILL.md` - PASS.
- Compatibility audit - PASS, `thin_stateful_bridge`.
  Command:
  python3 scripts/audit_superpowers_compatibility.py \
    --superpowers-root /Users/kws/.codex/skills \
    --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
- `./evals/run.sh` - PASS.
- `graphify update .` - PASS.
- Graphify freshness - PASS, `fresh=true`.
  Command:
  python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
    --repo-root /Users/kws/source/private/Archive \
    --update-ran \
    --output /tmp/cpe-boundary-graphify-audit.json
- `bun run check` - PASS.
- `git diff --check` - PASS.
```

- [ ] **Step 9: Commit Task 5**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/references/subagent-run-store.md \
  skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/docs/risks-limitations-deferrals.md \
  skills/kws-codex-plan-executor/docs/verification-log.md \
  graphify-out/GRAPH_REPORT.md \
  graphify-out/graph.json
git diff --cached --check
git commit -m "docs(cpe): document execution boundary optimization"
```

Expected: commit succeeds.

---

## Final Verification

After Task 5, run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 scripts/audit_superpowers_compatibility.py \
  --superpowers-root /Users/kws/.codex/skills \
  --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
cd /Users/kws/source/private/Archive
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root /Users/kws/source/private/Archive \
  --update-ran \
  --output /tmp/cpe-boundary-graphify-audit.json
bun run check
git diff --check
git status --short --branch --untracked-files=all
```

Expected final state:

- All commands pass.
- `git status --short --branch --untracked-files=all` shows a clean implementation branch.
- Recent-run inspection can explain boundary, lineage, context fallback, and inspection-only debt without reading raw transcripts.
