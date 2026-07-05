# CPE Operational Quality Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split CPE operational-quality signals into actionable and informational followups, while preserving finished-run safety and adding would-have dispatch evidence.

**Architecture:** Extend the existing v2.26.0 quality surfaces instead of replacing them: `run_quality_debt.py` owns taxonomy, `analyze_recent_runs.py` owns aggregate report classes, `preflight_dispatch.py` owns final and advisory dispatch decisions, and task-packet/readiness scripts own full-spec fallback next actions. State-level grades remain `green|yellow|red`; report-level output may add `green-with-info`.

**Tech Stack:** Python 3 standard library, existing CPE scripts/evals, Bash eval harness, Markdown contract docs, Graphify command evidence.

## Global Constraints

- Do not change `completion_audit.passed` semantics.
- Do not hide `run_quality.yellow`; only split actionable and informational followups.
- Do not change the state-level `run_quality.grade` enum away from `green|yellow|red`.
- Do not change the `subagents=on` default.
- Do not bypass `spawn_agent` policy or infer explicit delegation where the user did not request it.
- Do not make AgentLens unavailable a blocking failure.
- Do not forbid all full-spec fallback; unreviewed fallback remains actionable, reviewed fallback is allowed when context budget is not red.
- Do not mutate archived run states.
- Keep task packet JSON and `state.json` as the source of truth.
- Use only Python standard library for CPE scripts and evals.
- Update docs and evals in the same implementation branch as behavior changes.

---

## File Structure

- Modify `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
  - Owns stable followup taxonomy, actionable/informational classification, and report display class helpers.
- Modify `skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py`
  - Aggregates taxonomy into `green_with_info_count`, actionable/informational totals, and non-hardcoded rubric dimensions.
- Modify `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
  - Exposes `followup_taxonomy` and report display class fields for replay-friendly summaries.
- Modify `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
  - Covers taxonomy helper behavior and state-grade compatibility.
- Modify `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`
  - Covers recent-run aggregate counts and `green-with-info`.
- Modify `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
  - Preserves final local fallback under explicit-request spawn policy while recording advisory would-have dispatch evidence.
- Modify `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`
  - Covers would-have evidence for explicit-request policy and confirms safety blockers still block.
- Modify `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
  - Adds deterministic full-spec fallback `next_action` to packet mapping evidence.
- Modify `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
  - Surfaces fallback `next_action` in readiness issues.
- Modify `skills/kws-codex-plan-executor/evals/check_task_packet.py`
  - Covers fallback `next_action` in generated task packets.
- Modify `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
  - Covers fallback `next_action` in readiness output.
- Modify `skills/kws-codex-plan-executor/evals/run.sh`
  - Ensures touched evals are included in the main harness if any are not already listed.
- Modify `skills/kws-codex-plan-executor/SKILL.md`
  - Documents informational followups, report-level `green-with-info`, and would-have evidence.
- Modify `skills/kws-codex-plan-executor/references/state-schema.md`
  - Documents `followup_taxonomy`, state grade compatibility, delegation capability, and advisory dispatch fields.
- Modify `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
  - Documents final decision versus would-have decision.
- Modify `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
  - Updates eval coverage for taxonomy and dispatch evidence.
- Modify `skills/kws-codex-plan-executor/ARCHITECTURE.md`
  - Describes ownership boundaries for quality signals.
- Modify `skills/kws-codex-plan-executor/HISTORY.md`
  - Records the behavior change.

---

### Task 1: Followup Taxonomy and Recent-Run Report Classes

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
- Modify: `skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py`
- Modify: `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`

**Interfaces:**
- Consumes: `stable_followups(state: dict, *, missing_execution_worktree: bool | None = None) -> list[str]`
- Produces: `followup_taxonomy(state: dict, followups: list[str], *, missing_execution_worktree: bool | None = None) -> dict[str, object]`
- Produces: `report_class_for(state: dict, followups: list[str], taxonomy: dict[str, object], validation_status: str | None = None) -> str`
- Produces report-only display classes: `green`, `green-with-info`, `yellow`, `red`

- [ ] **Step 1: Add failing taxonomy checks**

Append these checks inside `main()` in `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`, after the existing `debt = load_run_quality_debt()` line:

```python
    info_state = v222_state()
    info_state["agentlens_orchestration_run"] = None
    info_state["agentlens_status"] = {
        "schema_version": "1",
        "status": "agentlens_unavailable",
        "blocking": False,
    }
    info_state["delegation_capability"] = {
        "schema_version": "1",
        "spawn_policy": "explicit-request-required",
        "explicit_user_delegation_request": False,
        "run_level_effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
    }
    info_state["dispatch_decisions"] = []
    info_followups = debt.stable_followups(info_state)
    info_taxonomy = debt.followup_taxonomy(info_state, info_followups)
    checks["taxonomy_splits_informational_followups"] = (
        info_taxonomy.get("actionable_followups") == []
        and info_taxonomy.get("informational_followups") == [
            "agentlens_missing",
            "delegation_policy_expected_local_fallback",
        ]
        and debt.report_class_for(info_state, info_followups, info_taxonomy, "passed") == "green-with-info"
        and debt.grade_for(info_state, info_followups, "passed") == "yellow"
    )
    if not checks["taxonomy_splits_informational_followups"]:
        failures.append("taxonomy should keep state grade yellow but report info-only debt as green-with-info")

    actionable_state = v222_state()
    actionable_state["run_quality"]["context_quality"]["full_spec_fallback_count"] = 1
    actionable_followups = debt.stable_followups(actionable_state)
    actionable_taxonomy = debt.followup_taxonomy(actionable_state, actionable_followups)
    checks["taxonomy_keeps_full_spec_actionable"] = (
        "full_spec_fallback_present" in actionable_taxonomy.get("actionable_followups", [])
        and debt.report_class_for(actionable_state, actionable_followups, actionable_taxonomy, "passed") == "yellow"
    )
    if not checks["taxonomy_keeps_full_spec_actionable"]:
        failures.append("full-spec fallback should remain actionable and report yellow")

    emit_failed_state = v222_state()
    emit_failed_state["agentlens_orchestration_run"] = None
    emit_failed_state["agentlens_status"] = {
        "schema_version": "1",
        "status": "agentlens_emit_failed",
        "blocking": False,
    }
    emit_followups = debt.stable_followups(emit_failed_state)
    emit_taxonomy = debt.followup_taxonomy(emit_failed_state, emit_followups)
    checks["taxonomy_treats_agentlens_emit_failed_actionable"] = (
        "agentlens_missing" in emit_taxonomy.get("actionable_followups", [])
    )
    if not checks["taxonomy_treats_agentlens_emit_failed_actionable"]:
        failures.append("agentlens emit failure should be actionable even when non-blocking")
```

- [ ] **Step 2: Add failing recent-run rubric checks**

Update the fixture section in `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py` so it creates four runs:

```python
        write_state(orch / "green-run", "green-run", grade="green", followups=[])
        write_state(
            orch / "info-run",
            "info-run",
            grade="yellow",
            followups=["agentlens_missing", "delegation_policy_expected_local_fallback"],
        )
        write_state(
            orch / "yellow-run",
            "yellow-run",
            grade="yellow",
            followups=["full_spec_fallback_present", "delegation_policy_expected_local_fallback"],
        )
        write_state(orch / "red-run", "red-run", grade="red", followups=["schema_drift"], completion=False)
```

Replace the count assertions with:

```python
        checks["counts_runs"] = summary.get("finished_passed_count") == 3 and summary.get("run_count") == 4
        checks["counts_grades"] = (
            summary.get("green_count") == 1
            and summary.get("green_with_info_count") == 1
            and summary.get("yellow_count") == 1
            and summary.get("red_count") == 1
        )
        checks["counts_taxonomy"] = (
            summary.get("actionable_followup_count") == 1
            and summary.get("informational_followup_count") == 4
        )
        checks["rubric_uses_info_class"] = (
            rubric.get("delegation_efficiency") == "green-with-info"
            and rubric.get("validator_maintainability") in {"green", "green-with-info"}
        )
```

Add `"counts_taxonomy"` and `"rubric_uses_info_class"` to the failure loop by leaving the existing loop over `checks.items()` intact.

- [ ] **Step 3: Run RED for taxonomy**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_operational_run_quality.py
python3 evals/check_recent_run_rubric.py
```

Expected:

- `check_operational_run_quality.py` fails because `run_quality_debt.followup_taxonomy` and `report_class_for` do not exist.
- `check_recent_run_rubric.py` fails because the report lacks `green_with_info_count`, actionable/informational totals, and info-aware rubric values.

- [ ] **Step 4: Implement taxonomy helpers**

Add these functions to `skills/kws-codex-plan-executor/scripts/run_quality_debt.py` after `stable_followups`:

```python
def _agentlens_followup_is_actionable(state: dict[str, Any]) -> bool:
    status = state.get("agentlens_status")
    if isinstance(status, dict):
        return status.get("status") == "agentlens_emit_failed"
    return False


def _expected_local_fallback_is_informational(state: dict[str, Any]) -> bool:
    capability = state.get("delegation_capability") if isinstance(state.get("delegation_capability"), dict) else {}
    policy = state.get("delegation_policy") if isinstance(state.get("delegation_policy"), dict) else {}
    evidence = capability or policy
    return (
        evidence.get("spawn_policy") == "explicit-request-required"
        and evidence.get("explicit_user_delegation_request") is False
    )


def followup_taxonomy(
    state: dict[str, Any],
    followups: list[str],
    *,
    missing_execution_worktree: bool | None = None,
) -> dict[str, object]:
    actionable: list[str] = []
    informational: list[str] = []
    release_blocking: list[str] = []
    terminal = state.get("lifecycle_outcome")
    for item in followups:
        if item == AGENTLENS_MISSING:
            if _agentlens_followup_is_actionable(state):
                actionable.append(item)
            else:
                informational.append(item)
        elif item == DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK:
            if _expected_local_fallback_is_informational(state):
                informational.append(item)
            else:
                actionable.append(item)
        elif item == MISSING_EXECUTION_WORKTREE:
            if terminal == "finished" and missing_execution_worktree is True:
                informational.append(item)
            else:
                actionable.append(item)
        elif item in {
            READINESS_FIXABLE_ISSUES,
            PLAN_EXECUTABILITY_FIXABLE_ISSUES,
            FULL_SPEC_FALLBACK_PRESENT,
            DELEGATION_POLICY_PREVENTED_ALL_DELEGATION,
            DELEGATION_POLICY_MISSING_DISPATCH_EVIDENCE,
        }:
            actionable.append(item)
        else:
            actionable.append(item)
    return {
        "schema_version": "1",
        "actionable_followups": actionable,
        "informational_followups": informational,
        "release_blocking_followups": release_blocking,
    }


def report_class_for(
    state: dict[str, Any],
    followups: list[str],
    taxonomy: dict[str, object],
    validation_status: str | None = None,
) -> str:
    state_grade = grade_for(state, followups, validation_status)
    if state_grade == "red":
        return "red"
    actionable = taxonomy.get("actionable_followups")
    informational = taxonomy.get("informational_followups")
    if isinstance(actionable, list) and actionable:
        return "yellow"
    if isinstance(informational, list) and informational:
        return "green-with-info"
    return "green"
```

Do not change `grade_for`; it must keep returning only `green|yellow|red`.

- [ ] **Step 5: Add taxonomy to normalized runs**

In `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`, import the helper safely near the existing script imports:

```python
from run_quality_debt import followup_taxonomy, report_class_for  # noqa: E402
```

Inside `normalize`, before the return object, compute:

```python
    open_followups = list_strings(quality.get("open_followups"))
    taxonomy = followup_taxonomy(state, open_followups)
    report_class = report_class_for(state, open_followups, taxonomy, quality.get("validation_status"))
```

Then replace the existing `"open_followups": ...` line and add two fields:

```python
        "open_followups": open_followups,
        "followup_taxonomy": taxonomy,
        "run_quality_report_class": report_class,
```

- [ ] **Step 6: Update recent-run aggregate report**

In `skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py`, update `grade_counts`:

```python
def grade_counts(normalized: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "green_count": sum(1 for item in normalized if item.get("run_quality_report_class") == "green"),
        "green_with_info_count": sum(1 for item in normalized if item.get("run_quality_report_class") == "green-with-info"),
        "yellow_count": sum(1 for item in normalized if item.get("run_quality_report_class") == "yellow"),
        "red_count": sum(
            1
            for item in normalized
            if item.get("run_quality_report_class") == "red" or item.get("completion_passed") is False
        ),
    }
```

Add this helper:

```python
def taxonomy_count(item: dict[str, Any], key: str) -> int:
    taxonomy = item.get("followup_taxonomy")
    if not isinstance(taxonomy, dict):
        return 0
    value = taxonomy.get(key)
    return len(value) if isinstance(value, list) else 0
```

In `build_report`, add to `summary`:

```python
        "actionable_followup_count": sum(taxonomy_count(item, "actionable_followups") for item in runs),
        "informational_followup_count": sum(taxonomy_count(item, "informational_followups") for item in runs),
```

Replace the rubric with:

```python
    rubric = {
        "safety": "red" if counts["red_count"] else "green",
        "context": "yellow" if summary["full_spec_fallback_count"] else "green",
        "delegation_efficiency": (
            "yellow"
            if any(
                "delegation_policy_prevented_all_delegation"
                in (item.get("followup_taxonomy", {}).get("actionable_followups") or [])
                for item in runs
            )
            else ("green-with-info" if summary["expected_local_fallback_count"] else "green")
        ),
        "evidence": worst_grade(["yellow" if not item.get("verification_evidence_classes") else "green" for item in runs]),
        "validator_maintainability": "green",
    }
```

- [ ] **Step 7: Run GREEN for Task 1**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_operational_run_quality.py
python3 evals/check_recent_run_rubric.py
python3 scripts/analyze_recent_runs.py --codex-home /Users/kws/.codex --recent 3 --include-finished
```

Expected:

- Both evals pass.
- The live recent-run report includes `green_with_info_count`, `actionable_followup_count`, and `informational_followup_count`.
- Runs that only have AgentLens unavailable plus expected local fallback are report-level `green-with-info`.

- [ ] **Step 8: Commit Task 1**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/run_quality_debt.py \
  skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py \
  skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py \
  skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py
git commit -m "feat(cpe): classify operational quality followups"
```

---

### Task 2: Would-Have Dispatch Evidence

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`

**Interfaces:**
- Consumes: `adaptive_value_decision(packet: dict, write_scope: list[str], explicit_requested: bool) -> tuple[str, str, dict]`
- Produces dispatch field: `delegation_policy.would_have_decision: "delegate"|"local_fallback"|"block"`
- Produces dispatch field: `delegation_policy.would_have_reason: str`
- Produces dispatch field: `delegation_policy.would_have_value_gate: "delegate"|"local_fast_path"|"block"`

- [ ] **Step 1: Add failing would-have eval**

In `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`, update the existing `spawn_policy_requires_explicit_request_local_fallback` check block. Replace that check with:

```python
        policy = data.get("delegation_policy", {})
        checks["spawn_policy_requires_explicit_request_local_fallback"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and "spawn_policy_requires_explicit_user_request" in data.get("failed_prerequisites", [])
            and policy.get("effective_mode") == "local_fallback"
            and policy.get("value_gate") == "skipped_by_spawn_policy"
            and policy.get("would_have_decision") == "local_fallback"
            and policy.get("would_have_value_gate") == "local_fast_path"
            and policy.get("would_have_reason") == "adaptive_policy_local_fast_path_docs_only"
            and policy.get("signals", {}).get("declared_file_count") == 1
        )
```

Add a second explicit-request fixture after that block:

```python
    with tempfile.TemporaryDirectory(prefix="cpe-dispatch-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "scripts").mkdir()
        (repo / "evals").mkdir()
        (repo / "scripts/tool.py").write_text("print('base')\n", encoding="utf-8")
        (repo / "evals/check_tool.py").write_text("print('base')\n", encoding="utf-8")
        subprocess.run(["git", "add", "scripts/tool.py", "evals/check_tool.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "add tool"], cwd=repo, check=True)
        state_path = repo / "state.json"
        packet_path = repo / "task_0.json"
        write_packet(
            packet_path,
            ["scripts/tool.py", "evals/check_tool.py"],
            allowed_write_globs=["scripts/*.py", "evals/*.py"],
            estimated_chars=18000,
            dependencies=[],
        )
        write_state(state_path)
        result, data = run_dispatch(
            repo,
            state_path,
            packet_path,
            "--spawn-policy",
            "explicit-request-required",
            "--explicit-delegation-requested",
            "false",
            "--requested-subagents",
            "on",
            "--requested-source",
            "default",
            write_scope=["scripts/*.py", "evals/*.py"],
        )
        policy = data.get("delegation_policy", {})
        checks["spawn_policy_records_would_have_delegate"] = (
            result.returncode == 0
            and data.get("decision") == "local_fallback"
            and policy.get("value_gate") == "skipped_by_spawn_policy"
            and policy.get("would_have_decision") == "delegate"
            and policy.get("would_have_value_gate") == "delegate"
            and policy.get("would_have_reason") == "all pre-dispatch prerequisites passed"
        )
        if not checks["spawn_policy_records_would_have_delegate"]:
            failures.append("explicit-request policy should record whether the task would have delegated")
```

- [ ] **Step 2: Run RED for dispatch evidence**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
```

Expected: FAIL because current spawn-policy path sets `value_gate=skipped` and lacks `would_have_*` fields.

- [ ] **Step 3: Add advisory helper to preflight dispatch**

In `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`, add this helper after `adaptive_value_decision`:

```python
def advisory_value_decision(packet: dict, write_scope: list[str], explicit_requested: bool) -> tuple[str, str, dict]:
    value_gate, value_reason, signals = adaptive_value_decision(packet, write_scope, explicit_requested)
    if value_gate == "local_fast_path":
        return "local_fallback", value_reason, signals
    if value_gate == "block":
        return "block", value_reason, signals
    return "delegate", value_reason, signals
```

- [ ] **Step 4: Compute would-have fields when spawn policy blocks delegation**

In `preflight_dispatch.py`, keep the existing final `decision=local_fallback` for:

```python
elif args.spawn_policy == "explicit-request-required" and not explicit_requested:
```

After packet/state/write-scope validation and before `delegation_policy["safety_gate"] = ...`, replace the current `if not failed and decision == "delegate": ... else ...` value-gate block with this structure:

```python
    spawn_policy_failed_only = failed == ["spawn_policy_requires_explicit_user_request"]
    if spawn_policy_failed_only and decision == "local_fallback":
        would_decision, would_reason, signals = advisory_value_decision(packet, write_scope, explicit_requested)
        delegation_policy["signals"] = signals
        delegation_policy["value_gate"] = "skipped_by_spawn_policy"
        delegation_policy["would_have_decision"] = would_decision
        delegation_policy["would_have_reason"] = would_reason
        delegation_policy["would_have_value_gate"] = (
            "delegate" if would_decision == "delegate" else ("block" if would_decision == "block" else "local_fast_path")
        )
    elif not failed and decision == "delegate":
        value_gate, value_reason, signals = adaptive_value_decision(packet, write_scope, explicit_requested)
        delegation_policy["signals"] = signals
        delegation_policy["value_gate"] = value_gate
        if value_gate == "local_fast_path":
            decision = "local_fallback"
            reason = value_reason
        elif value_gate == "block":
            failed.append(value_reason)
            decision = "block"
            reason = value_reason
        else:
            reason = value_reason
    else:
        delegation_policy["signals"] = {}
        delegation_policy["value_gate"] = "skipped"
```

This preserves final decisions. It only adds advisory fields when the only failed prerequisite is `spawn_policy_requires_explicit_user_request`.

- [ ] **Step 5: Validate state schema allows advisory fields**

Inspect `skills/kws-codex-plan-executor/scripts/validate_state.py` and `skills/kws-codex-plan-executor/evals/check_state_schema.py`. If `delegation_policy` currently rejects unknown optional keys, add these allowed keys:

```python
"would_have_decision"
"would_have_reason"
"would_have_value_gate"
```

Then add a state-schema eval assertion that a valid state with those three fields passes:

```python
    state = v220_state()
    state["delegation_policy"]["would_have_decision"] = "delegate"
    state["delegation_policy"]["would_have_reason"] = "all pre-dispatch prerequisites passed"
    state["delegation_policy"]["would_have_value_gate"] = "delegate"
    checks["delegation_policy_allows_would_have_fields"] = validate_state_payload(state)[0] == []
```

Use the exact helper names already present in `check_state_schema.py`; do not invent a parallel validator entry point.

- [ ] **Step 6: Run GREEN for Task 2**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
python3 scripts/preflight_dispatch.py --help
```

Expected:

- `check_preflight_dispatch.py` passes.
- State schema eval passes.
- `preflight_dispatch.py --help` still works and has no new required CLI arguments.

- [ ] **Step 7: Commit Task 2**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/preflight_dispatch.py \
  skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/scripts/validate_state.py
git commit -m "feat(cpe): record would-have dispatch evidence"
```

---

### Task 3: Full-Spec Fallback Next Action

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`

**Interfaces:**
- Produces: `fallback_next_action(reason: str, suggested_refs: list[str]) -> str`
- Produces packet field: `spec.mapping.next_action: str`
- Produces readiness issue field: `next_action: str`

- [ ] **Step 1: Add failing task-packet eval**

In `skills/kws-codex-plan-executor/evals/check_task_packet.py`, find the existing assertion block that checks:

```python
fallback_mapping.get("fallback_reason") == "weak_heuristic_match"
```

Extend that same check with:

```python
            and fallback_mapping.get("next_action") == "Add explicit spec_refs to the plan task using one of: S1"
```

Use the actual suggested section id from that fixture. If the fixture asserts multiple `suggested_spec_refs`, the expected string is:

```python
"Add explicit spec_refs to the plan task using one of: S1, S2"
```

- [ ] **Step 2: Add failing readiness eval**

In `skills/kws-codex-plan-executor/evals/check_run_readiness.py`, extend `checks["full_spec_fallback_has_reason"]`:

```python
        checks["full_spec_fallback_has_reason"] = (
            fallback_issue.get("fallback_reason") == "missing_spec_refs"
            and fallback_issue.get("suggested_spec_refs") == ["problem", "goals"]
            and fallback_issue.get("next_action") == "Add explicit spec_refs to the plan task using one of: problem, goals"
        )
```

- [ ] **Step 3: Run RED for fallback next action**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
```

Expected: FAIL because fallback mapping/readiness output lacks `next_action`.

- [ ] **Step 4: Implement deterministic next-action text**

Add this helper to `skills/kws-codex-plan-executor/scripts/build_task_packet.py` after `suggested_spec_refs`:

```python
def fallback_next_action(reason: str, refs: list[str]) -> str:
    if refs:
        return "Add explicit spec_refs to the plan task using one of: " + ", ".join(refs)
    if reason == "missing_spec_refs":
        return "Add explicit spec_refs to the plan task."
    if reason == "manifest_gap":
        return "Update spec_manifest task_to_sections or section ids for this task."
    if reason == "weak_heuristic_match":
        return "Add or correct section ids in the spec and plan pair."
    if reason == "intentional_operator_reviewed":
        return "Record operator_decision and keep context budget evidence."
    return "Review spec mapping evidence and add task-specific spec_refs."
```

In `resolve_sections`, replace:

```python
    reason = fallback_reason(task, candidate_scores)
```

with:

```python
    reason = fallback_reason(task, candidate_scores)
    refs = suggested_spec_refs(candidate_scores)
```

Then update the returned mapping:

```python
        "fallback_reason": reason,
        "suggested_spec_refs": refs,
        "next_action": fallback_next_action(reason, refs),
        "operator_reviewed": False,
```

- [ ] **Step 5: Surface next action in readiness issues**

In `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`, inside the `full_spec_fallback` issue payload, add:

```python
                next_action=mapping.get("next_action") or "Add explicit spec_refs to the plan task.",
```

- [ ] **Step 6: Run GREEN for Task 3**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
```

Expected: both evals pass and include next-action evidence.

- [ ] **Step 7: Commit Task 3**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/build_task_packet.py \
  skills/kws-codex-plan-executor/scripts/audit_run_readiness.py \
  skills/kws-codex-plan-executor/evals/check_task_packet.py \
  skills/kws-codex-plan-executor/evals/check_run_readiness.py
git commit -m "feat(cpe): explain full spec fallback fixes"
```

---

### Task 4: Contract Docs, Harness Coverage, and Closeout

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: behavior implemented in Tasks 1-3.
- Produces: updated public skill contract and deterministic harness coverage.

- [ ] **Step 1: Update `SKILL.md` contract**

In `skills/kws-codex-plan-executor/SKILL.md`, add these contract bullets near the existing run-quality and dispatch bullets:

```markdown
- Recent-run analysis separates actionable followups from informational followups. `green-with-info` is report-only display metadata; durable `state.json` run quality grades remain `green`, `yellow`, or `red`.
- Expected local fallback caused by `spawn_policy=explicit-request-required` and no explicit delegation request is informational policy evidence, not proof that task safety gates were skipped.
- When spawn policy prevents actual delegation, pre-dispatch may record advisory `would_have_decision`, `would_have_reason`, and `would_have_value_gate` under `delegation_policy`; these fields never authorize spawning and never replace the final `decision`.
- Full-spec fallback evidence includes a deterministic `next_action` so plan/spec authors know how to reduce context debt in the next run.
```

- [ ] **Step 2: Update state schema reference**

In `skills/kws-codex-plan-executor/references/state-schema.md`, document:

```markdown
### run_quality.followup_taxonomy

Optional object with `schema_version=1`, `actionable_followups`,
`informational_followups`, and `release_blocking_followups`. The taxonomy is derived
from `open_followups`; it does not replace `completion_audit`, validation, or
residual-risk rules.

`green-with-info` is allowed only in read-only reports such as
`analyze_recent_runs.py`. Durable `run_quality.grade` remains `green`, `yellow`, or
`red`.

### delegation_policy advisory would-have fields

When `spawn_policy=explicit-request-required` blocks actual delegation, dispatch
payloads may include `would_have_decision`, `would_have_reason`, and
`would_have_value_gate`. These fields are advisory analysis. Final execution follows
`decision`, `reason`, `failed_prerequisites`, and task `subagent_strategy`.
```

- [ ] **Step 3: Update pre-dispatch reference**

In `skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md`, add:

```markdown
The final dispatch decision and advisory would-have decision are different surfaces.
If spawn policy requires explicit delegation intent and the user did not provide it,
the final decision remains `local_fallback`. CPE may still evaluate safety/value signals
and record what would have happened if spawning were allowed. This evidence is for
operator analysis only and must not trigger a subagent run.
```

- [ ] **Step 4: Update architecture and eval docs**

In `skills/kws-codex-plan-executor/ARCHITECTURE.md`, add a short ownership note:

```markdown
Operational quality signal ownership:

- `run_quality_debt.py` classifies stable followups and report-only display classes.
- `analyze_recent_runs.py` aggregates recent state into operator-facing rubric JSON.
- `preflight_dispatch.py` owns final dispatch decisions and advisory would-have evidence.
- Task packet and readiness scripts own full-spec fallback diagnosis and next actions.
```

In `skills/kws-codex-plan-executor/docs/evals-and-verification.md`, add the touched evals:

```markdown
- `evals/check_operational_run_quality.py`: followup taxonomy and state-grade compatibility.
- `evals/check_recent_run_rubric.py`: report-level `green-with-info` and aggregate followup counts.
- `evals/check_preflight_dispatch.py`: advisory would-have dispatch evidence.
- `evals/check_task_packet.py` and `evals/check_run_readiness.py`: full-spec fallback next actions.
```

- [ ] **Step 5: Confirm `evals/run.sh` includes touched evals**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
rg -n "check_operational_run_quality|check_recent_run_rubric|check_preflight_dispatch|check_task_packet|check_run_readiness" evals/run.sh
```

Expected: every touched eval appears in `evals/run.sh`.

If one is missing, add it to the deterministic Python eval section using the existing pattern. The added line must be exact:

```bash
run_eval "python3 evals/check_operational_run_quality.py"
run_eval "python3 evals/check_recent_run_rubric.py"
run_eval "python3 evals/check_preflight_dispatch.py"
run_eval "python3 evals/check_task_packet.py"
run_eval "python3 evals/check_run_readiness.py"
```

- [ ] **Step 6: Update history**

Add an entry near the top of `skills/kws-codex-plan-executor/HISTORY.md`:

```markdown
## 2.27.0 - 2026-07-05

- Split recent-run operational-quality followups into actionable and informational taxonomy.
- Added report-level `green-with-info` for runs that passed completion and only have informational followups.
- Recorded advisory would-have dispatch evidence when spawn policy prevents actual delegation.
- Added deterministic next-action guidance for full-spec fallback context debt.
```

Do not update package version metadata unless the existing release process in this repo requires it for docs/contract changes.

- [ ] **Step 7: Run focused verification**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_operational_run_quality.py
python3 evals/check_recent_run_rubric.py
python3 evals/check_preflight_dispatch.py
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
```

Expected: every command passes.

- [ ] **Step 8: Run full CPE and repo verification**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
cd /Users/kws/source/private/Archive
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root /Users/kws/source/private/Archive --update-ran
bun run check
git diff --check
```

Expected:

- `./evals/run.sh` passes.
- Graphify freshness check reports `fresh=true`.
- `bun run check` passes.
- `git diff --check` prints no errors.

- [ ] **Step 9: Commit Task 4**

```bash
git add \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/references/pre-dispatch-pipeline.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/evals/run.sh \
  graphify-out
git commit -m "docs(cpe): document quality signal taxonomy"
```

If `graphify-out/` is ignored and has no staged changes, omit it from the final staged set and record in the completion summary that Graphify freshness was command evidence only.

---

## Final Acceptance

- Recent-run analysis on the three inspected 2026-07-05 states separates informational AgentLens absence, informational expected local fallback, and actionable full-spec fallback.
- `completion_audit.passed=true` remains compatible with state-level `run_quality.grade=yellow`.
- Report-level `green-with-info` appears only in analysis output, not durable state grade.
- Explicit-request spawn policy still prevents actual delegation unless the user explicitly requests delegation.
- Would-have dispatch evidence is recorded only as advisory analysis.
- Full-spec fallback mapping includes deterministic `next_action`.
- All focused evals, full CPE evals, `bun run check`, Graphify freshness, and `git diff --check` pass.

## Self-Review

- Spec coverage: Tasks 1-4 cover taxonomy, run-level expected local fallback, AgentLens classification, full-spec fallback next actions, recent-run rubric output, dispatch evidence, docs, and verification.
- Placeholder scan: no unfinished markers remain.
- Type consistency: `followup_taxonomy`, `report_class_for`, `would_have_decision`, `would_have_reason`, `would_have_value_gate`, and `next_action` are named consistently across tasks.
- Scope check: this is one implementation plan for CPE operational-quality signal classification and evidence, not a Waygent runtime rewrite.
