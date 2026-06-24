# CPE Run Quality Debt Surfacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CPE finished run quality expose non-blocking operational debt without turning verified product work into failed completion audits.

**Architecture:** Add one small shared Python helper for stable run-quality follow-up classification, then consume it from `validate_state.py` and `inspect_runs.py`. Keep product verification in `completion_audit`; use `run_quality.grade`, `operational_debt`, and `open_followups` for executor evidence and efficiency debt.

**Tech Stack:** Python 3 standard library, existing CPE scripts, deterministic eval scripts, markdown contract docs.

## Global Constraints

- Do not weaken subagent safety gates, dirty overlap checks, risky scope blocking, or AgentLens best-effort semantics.
- `completion_audit.passed=true` and `run_quality.grade=yellow` must be valid together.
- `inspect_runs.py --jsonl --quality-report` must keep stdout machine-readable JSONL only.
- Follow-up strings must be stable: `agentlens_missing`, `missing_execution_worktree`, `readiness_fixable_issues`, `full_spec_fallback_present`, `delegation_policy_prevented_all_delegation`.
- Worktree deletion must not be a finished-state hard validation error because it can happen after completion.
- Update `SKILL.md` metadata, checked reference docs, `ARCHITECTURE.md`, evals, and `HISTORY.md` with the behavior contract.

---

## File Structure

- Create `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`: pure helper functions for stable operational debt follow-ups and grade suggestions.
- Modify `skills/kws-codex-plan-executor/scripts/validate_state.py`: require embedded finished `run_quality` to include deterministic follow-ups for state-intrinsic debt.
- Modify `skills/kws-codex-plan-executor/scripts/inspect_runs.py`: merge current filesystem observations with embedded quality and expose current quality provenance.
- Modify `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`: cover validator rules and yellow quality semantics.
- Modify `skills/kws-codex-plan-executor/evals/check_inspect_runs.py`: cover current missing-worktree observation and JSONL quality output.
- Modify `skills/kws-codex-plan-executor/SKILL.md`: document the new run-quality debt contract.
- Modify `skills/kws-codex-plan-executor/references/state-schema.md`: document `operational_debt` and required follow-up semantics.
- Modify `skills/kws-codex-plan-executor/references/execution-cycle.md`: document finalization and inspection behavior.
- Modify `skills/kws-codex-plan-executor/ARCHITECTURE.md`: document where run-quality debt classification lives.
- Modify `skills/kws-codex-plan-executor/HISTORY.md`: add the behavior change entry.

---

### Task 1: Shared Run Quality Debt Classifier

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

**Interfaces:**
- Consumes: CPE state dictionaries and optional current observation flags.
- Produces: `stable_followups(state: dict, *, missing_execution_worktree: bool | None = None) -> list[str]`
- Produces: `operational_debt_summary(state: dict, *, missing_execution_worktree: bool | None = None) -> dict[str, object]`
- Produces: `grade_for(state: dict, followups: list[str], validation_status: str | None = None) -> str`

- [ ] **Step 1: Write failing helper checks**

Append these imports and checks to `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`.

```python
def load_run_quality_debt():
    script_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import run_quality_debt

    return run_quality_debt
```

Inside `main()`, after the existing `bad_quality` check and before `run_static_fixture()`:

```python
    debt = load_run_quality_debt()

    yellow_state = v222_state()
    yellow_state["agentlens_orchestration_run"] = None
    yellow_state["run_quality"]["readiness"]["fixable_issue_count"] = 2
    yellow_state["run_quality"]["context_quality"]["full_spec_fallback_count"] = 1
    yellow_state["dispatch_decisions"] = [
        {
            "task_id": "task_0",
            "decision": "local_fallback",
            "reason": "spawn_agent tool policy requires explicit user delegation intent",
            "failed_prerequisites": ["spawn_policy_requires_explicit_user_request"],
        }
    ]
    checks["debt_helper_reports_stable_followups"] = debt.stable_followups(yellow_state) == [
        "agentlens_missing",
        "readiness_fixable_issues",
        "full_spec_fallback_present",
        "delegation_policy_prevented_all_delegation",
    ]
    if not checks["debt_helper_reports_stable_followups"]:
        failures.append("run_quality_debt.stable_followups should report state-intrinsic debt in stable order")

    checks["debt_helper_reports_yellow_grade"] = debt.grade_for(
        yellow_state,
        debt.stable_followups(yellow_state),
        "passed",
    ) == "yellow"
    if not checks["debt_helper_reports_yellow_grade"]:
        failures.append("run_quality_debt.grade_for should return yellow for passed completion with followups")

    checks["debt_helper_reports_current_missing_worktree"] = (
        "missing_execution_worktree" in debt.stable_followups(yellow_state, missing_execution_worktree=True)
    )
    if not checks["debt_helper_reports_current_missing_worktree"]:
        failures.append("run_quality_debt.stable_followups should include current missing worktree observations")
```

- [ ] **Step 2: Run the failing helper eval**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'run_quality_debt'`.

- [ ] **Step 3: Add the shared helper**

Create `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


AGENTLENS_MISSING = "agentlens_missing"
MISSING_EXECUTION_WORKTREE = "missing_execution_worktree"
READINESS_FIXABLE_ISSUES = "readiness_fixable_issues"
FULL_SPEC_FALLBACK_PRESENT = "full_spec_fallback_present"
DELEGATION_POLICY_PREVENTED_ALL_DELEGATION = "delegation_policy_prevented_all_delegation"

STABLE_FOLLOWUP_ORDER = [
    AGENTLENS_MISSING,
    MISSING_EXECUTION_WORKTREE,
    READINESS_FIXABLE_ISSUES,
    FULL_SPEC_FALLBACK_PRESENT,
    DELEGATION_POLICY_PREVENTED_ALL_DELEGATION,
]

EXECUTION_MODES = {"interactive", "headless"}
SPAWN_POLICY_REASONS = {
    "spawn_agent tool policy requires explicit user delegation intent",
    "spawn_policy_requires_explicit_user_request",
}


def _run_quality(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("run_quality")
    return value if isinstance(value, dict) else {}


def _count_from_quality(state: dict[str, Any], section: str, key: str) -> int:
    quality = _run_quality(state)
    payload = quality.get(section)
    if not isinstance(payload, dict):
        return 0
    value = payload.get(key)
    return value if isinstance(value, int) and value > 0 else 0


def _has_execution_agentlens_gap(state: dict[str, Any]) -> bool:
    return (
        state.get("lifecycle_outcome") == "finished"
        and state.get("mode") in EXECUTION_MODES
        and not state.get("agentlens_orchestration_run")
    )


def _dispatch_reason_is_spawn_policy(decision: dict[str, Any]) -> bool:
    reason = decision.get("reason")
    failed = decision.get("failed_prerequisites")
    if isinstance(reason, str) and reason in SPAWN_POLICY_REASONS:
        return True
    return isinstance(failed, list) and "spawn_policy_requires_explicit_user_request" in failed


def _all_dispatches_local_due_to_spawn_policy(state: dict[str, Any]) -> bool:
    if state.get("subagents_requested") is not True:
        return False
    decisions = state.get("dispatch_decisions")
    if not isinstance(decisions, list) or not decisions:
        return False
    saw_local = False
    for decision in decisions:
        if not isinstance(decision, dict):
            return False
        if decision.get("decision") == "delegate":
            return False
        if decision.get("decision") != "local_fallback":
            return False
        if not _dispatch_reason_is_spawn_policy(decision):
            return False
        saw_local = True
    return saw_local


def stable_followups(
    state: dict[str, Any],
    *,
    missing_execution_worktree: bool | None = None,
) -> list[str]:
    found: set[str] = set()
    if _has_execution_agentlens_gap(state):
        found.add(AGENTLENS_MISSING)
    if missing_execution_worktree is True:
        found.add(MISSING_EXECUTION_WORKTREE)
    if _count_from_quality(state, "readiness", "fixable_issue_count") > 0:
        found.add(READINESS_FIXABLE_ISSUES)
    if _count_from_quality(state, "context_quality", "full_spec_fallback_count") > 0:
        found.add(FULL_SPEC_FALLBACK_PRESENT)
    if _all_dispatches_local_due_to_spawn_policy(state):
        found.add(DELEGATION_POLICY_PREVENTED_ALL_DELEGATION)
    return [item for item in STABLE_FOLLOWUP_ORDER if item in found]


def operational_debt_summary(
    state: dict[str, Any],
    *,
    missing_execution_worktree: bool | None = None,
) -> dict[str, object]:
    followups = stable_followups(state, missing_execution_worktree=missing_execution_worktree)
    return {
        "schema_version": "1",
        "followups": followups,
        "count": len(followups),
        "blocking": False,
    }


def grade_for(
    state: dict[str, Any],
    followups: list[str],
    validation_status: str | None = None,
) -> str:
    completion = state.get("completion_audit")
    completion_passed = isinstance(completion, dict) and completion.get("passed") is True
    if validation_status == "failed" or not completion_passed:
        return "red"
    return "yellow" if followups else "green"
```

- [ ] **Step 4: Run the helper eval**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
```

Expected: PASS with JSON containing `"debt_helper_reports_stable_followups": true`.

- [ ] **Step 5: Commit Task 1**

```bash
git add skills/kws-codex-plan-executor/scripts/run_quality_debt.py skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git commit -m "feat(cpe): add run quality debt classifier"
```

---

### Task 2: Validator Contract for Embedded Run Quality

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`

**Interfaces:**
- Consumes: `run_quality_debt.stable_followups(...)`
- Produces: validator errors when state-intrinsic follow-ups are missing from finished operational-quality state.

- [ ] **Step 1: Write failing validator checks**

Append these checks to `main()` in `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py` after the helper checks from Task 1:

```python
    yellow_quality = v222_state()
    yellow_quality["agentlens_orchestration_run"] = None
    yellow_quality["run_quality"]["grade"] = "yellow"
    yellow_quality["run_quality"]["readiness"]["fixable_issue_count"] = 1
    yellow_quality["run_quality"]["context_quality"]["full_spec_fallback_count"] = 1
    yellow_quality["run_quality"]["open_followups"] = [
        "agentlens_missing",
        "readiness_fixable_issues",
        "full_spec_fallback_present",
    ]
    yellow_quality["run_quality"]["operational_debt"] = {
        "schema_version": "1",
        "followups": list(yellow_quality["run_quality"]["open_followups"]),
        "count": 3,
        "blocking": False,
    }
    valid_yellow = run_validator(yellow_quality)
    checks["completion_passed_yellow_quality_passes"] = valid_yellow.returncode == 0
    if not checks["completion_passed_yellow_quality_passes"]:
        failures.append("completion_audit.passed=true with run_quality.grade=yellow should pass: " + valid_yellow.stderr)

    missing_followup = v222_state()
    missing_followup["agentlens_orchestration_run"] = None
    missing_followup["run_quality"]["context_quality"]["full_spec_fallback_count"] = 1
    missing_followup["run_quality"]["open_followups"] = []
    invalid_missing_followup = run_validator(missing_followup)
    checks["invalid_missing_required_followup_fails"] = (
        invalid_missing_followup.returncode != 0
        and "run_quality.open_followups missing required followup: agentlens_missing" in invalid_missing_followup.stderr
        and "run_quality.open_followups missing required followup: full_spec_fallback_present" in invalid_missing_followup.stderr
    )
    if not checks["invalid_missing_required_followup_fails"]:
        failures.append("validator should reject finished quality missing required open_followups")

    green_with_followup = v222_state()
    green_with_followup["agentlens_orchestration_run"] = None
    green_with_followup["run_quality"]["open_followups"] = ["agentlens_missing"]
    invalid_green = run_validator(green_with_followup)
    checks["green_with_open_followups_fails"] = (
        invalid_green.returncode != 0 and "run_quality.grade must be yellow or red when open_followups is non-empty" in invalid_green.stderr
    )
    if not checks["green_with_open_followups_fails"]:
        failures.append("validator should reject green run_quality with open followups")
```

- [ ] **Step 2: Run the failing validator eval**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
```

Expected: FAIL because `validate_state.py` does not yet require debt follow-ups and still accepts green quality with follow-ups.

- [ ] **Step 3: Import the helper in the validator**

Near the imports at the top of `skills/kws-codex-plan-executor/scripts/validate_state.py`, add:

```python
try:
    import run_quality_debt
except Exception:
    run_quality_debt = None
```

- [ ] **Step 4: Enforce the embedded quality contract**

Inside `_validate_operational_run_quality`, after the existing `recommendations` list validation, add:

```python
            followups = quality.get("open_followups")
            if isinstance(followups, list):
                if quality.get("grade") == "green" and followups:
                    errors.append("run_quality.grade must be yellow or red when open_followups is non-empty")
                if quality.get("grade") == "yellow" and not followups:
                    errors.append("run_quality.grade yellow requires at least one open_followup")

                if run_quality_debt is not None and data.get("lifecycle_outcome") == "finished" and v222_operational:
                    required_followups = run_quality_debt.stable_followups(data, missing_execution_worktree=False)
                    for item in required_followups:
                        if item not in followups:
                            errors.append(f"run_quality.open_followups missing required followup: {item}")

            if "operational_debt" in quality:
                debt = quality.get("operational_debt")
                if not isinstance(debt, dict):
                    errors.append("run_quality.operational_debt must be an object")
                else:
                    if debt.get("schema_version") != "1":
                        errors.append("run_quality.operational_debt.schema_version must be 1")
                    debt_followups = debt.get("followups")
                    if not isinstance(debt_followups, list):
                        errors.append("run_quality.operational_debt.followups must be a list")
                    count = debt.get("count")
                    if not isinstance(count, int) or count < 0:
                        errors.append("run_quality.operational_debt.count must be a non-negative integer")
                    if not isinstance(debt.get("blocking"), bool):
                        errors.append("run_quality.operational_debt.blocking must be a boolean")
```

- [ ] **Step 5: Run the validator eval**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
```

Expected: PASS with JSON containing `"completion_passed_yellow_quality_passes": true` and `"invalid_missing_required_followup_fails": true`.

- [ ] **Step 6: Commit Task 2**

```bash
git add skills/kws-codex-plan-executor/scripts/validate_state.py skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
git commit -m "fix(cpe): validate run quality debt followups"
```

---

### Task 3: Inspection Current Quality Output

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/inspect_runs.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_inspect_runs.py`

**Interfaces:**
- Consumes: `run_quality_debt.stable_followups(...)`, `run_quality_debt.operational_debt_summary(...)`, `run_quality_debt.grade_for(...)`
- Produces: read-only `run_quality` with current follow-ups, `operational_debt`, and `observed_after_completion` provenance.

- [ ] **Step 1: Write failing inspection checks**

In `skills/kws-codex-plan-executor/evals/check_inspect_runs.py`, change `write_state` to accept a `finished_quality` flag:

```python
def write_state(
    codex_home: Path,
    run_id: str,
    plan: str,
    outcome: str | None = None,
    create_worktree: bool = True,
    finished_quality: bool = False,
) -> None:
```

Before writing `state.json`, add:

```python
    if finished_quality:
        state.update(
            {
                "mode": "interactive",
                "execution_worktree": str(worktree),
                "completion_audit": {
                    "passed": True,
                    "prompt_to_artifact_checklist": ["Task mapped to docs/plan.md"],
                    "verification_evidence": ["git diff --check: passed"],
                    "residual_risk": [],
                },
                "subagents_requested": True,
                "dispatch_decisions": [
                    {
                        "task_id": "task_1",
                        "decision": "local_fallback",
                        "reason": "spawn_agent tool policy requires explicit user delegation intent",
                        "failed_prerequisites": ["spawn_policy_requires_explicit_user_request"],
                    }
                ],
                "run_quality": {
                    "schema_version": "1",
                    "validation_status": "passed",
                    "terminal_state": "finished",
                    "stale": False,
                    "workspace_matches_execution_worktree": True,
                    "score": 96,
                    "grade": "green",
                    "schema_drift": [],
                    "open_followups": [],
                    "readiness": {"task_count": 1, "fixable_issue_count": 0, "blocking_issue_count": 0},
                    "dispatch_consistency": {"mismatch_count": 0, "override_count": 0},
                    "context_quality": {"full_spec_fallback_count": 0},
                    "verification_quality": {"completion_audit_passed": True},
                    "recommendations": [],
                    "summary": "Run finished with validated state.",
                },
            }
        )
```

Append this new tempdir scenario near the end of `main()` before the final payload:

```python
    with tempfile.TemporaryDirectory(prefix="codex-inspect-runs-") as temp:
        home = Path(temp) / ".codex"
        write_state(home, "finished-missing-worktree", "docs/plan.md", outcome="finished", create_worktree=False, finished_quality=True)
        result, data = inspect_all(home, "--include-finished", "--quality-report", "--stale-hours", "24")
        run = (data.get("runs") or [{}])[0]
        quality = run.get("run_quality", {})
        debt = quality.get("operational_debt", {})
        followups = quality.get("open_followups", [])
        checks["finished_missing_worktree_current_quality_reported"] = (
            result.returncode == 0
            and quality.get("grade") == "yellow"
            and quality.get("observed_after_completion") is True
            and "missing_execution_worktree" in followups
            and "agentlens_missing" in followups
            and debt.get("count") == len(debt.get("followups", []))
        )
        if not checks["finished_missing_worktree_current_quality_reported"]:
            failures.append("inspect current quality should report missing worktree and AgentLens followups for finished runs")

        jsonl_result, _ = inspect_all(home, "--include-finished", "--quality-report", "--jsonl")
        jsonl_lines = [line for line in jsonl_result.stdout.splitlines() if line.strip()]
        checks["quality_jsonl_stdout_parseable"] = all(json.loads(line).get("run_id") for line in jsonl_lines)
        if not checks["quality_jsonl_stdout_parseable"]:
            failures.append("inspect --jsonl --quality-report should keep stdout parseable as JSONL")
```

- [ ] **Step 2: Run the failing inspection eval**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_inspect_runs.py
```

Expected: FAIL because `inspect_runs.py` does not yet merge debt helper output.

- [ ] **Step 3: Import the helper in inspection**

Near the imports in `skills/kws-codex-plan-executor/scripts/inspect_runs.py`, add:

```python
try:
    import run_quality_debt
except Exception:
    run_quality_debt = None
```

- [ ] **Step 4: Add current quality enrichment**

Replace the returned object in `run_quality(...)` with this structure:

```python
    existing_quality = state.get("run_quality") if isinstance(state, dict) and isinstance(state.get("run_quality"), dict) else {}
    base_followups = list(existing_quality.get("open_followups", [])) if isinstance(existing_quality.get("open_followups"), list) else []
    current_followups = list(base_followups)
    if stale and "stale_non_terminal_run" not in current_followups:
        current_followups.append("stale_non_terminal_run")
    if missing_worktree and "missing_execution_worktree" not in current_followups:
        current_followups.append("missing_execution_worktree")
    if workspace and execution_worktree and not workspace_matches and "workspace_execution_worktree_mismatch" not in current_followups:
        current_followups.append("workspace_execution_worktree_mismatch")
    if validation_status == "failed" and "state_schema_drift" not in current_followups:
        current_followups.append("state_schema_drift")

    if run_quality_debt is not None and state:
        for item in run_quality_debt.stable_followups(state, missing_execution_worktree=missing_worktree):
            if item not in current_followups:
                current_followups.append(item)
        operational_debt = run_quality_debt.operational_debt_summary(
            state,
            missing_execution_worktree=missing_worktree,
        )
        grade = run_quality_debt.grade_for(state, current_followups, validation_status)
    else:
        operational_debt = {"schema_version": "1", "followups": current_followups, "count": len(current_followups), "blocking": False}
        grade = "red" if validation_status == "failed" else ("yellow" if current_followups else "green")

    observed_after_completion = terminal and current_followups != base_followups
    result = {
        "schema_version": "1",
        "validation_status": validation_status,
        "terminal_state": outcome or "none",
        "stale": stale,
        "workspace_matches_execution_worktree": workspace_matches,
        "schema_drift": errors,
        "open_followups": current_followups,
        "operational_debt": operational_debt,
        "grade": grade,
        "observed_after_completion": observed_after_completion,
        "summary": "; ".join(summary_parts),
    }
    for key in ("score", "readiness", "dispatch_consistency", "context_quality", "verification_quality", "recommendations"):
        if key in existing_quality and key not in result:
            result[key] = existing_quality[key]
    return result
```

Remove the earlier direct `return { ... }` from `run_quality(...)`. Keep the existing `summary_parts` construction before this block.

- [ ] **Step 5: Run the inspection eval**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_inspect_runs.py
```

Expected: PASS with JSON containing `"finished_missing_worktree_current_quality_reported": true`.

- [ ] **Step 6: Commit Task 3**

```bash
git add skills/kws-codex-plan-executor/scripts/inspect_runs.py skills/kws-codex-plan-executor/evals/check_inspect_runs.py
git commit -m "feat(cpe): surface current run quality debt"
```

---

### Task 4: Contract Docs and Full Verification

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`

**Interfaces:**
- Consumes: Task 1-3 behavior and follow-up strings.
- Produces: repo-visible contract docs and final verification evidence.

- [ ] **Step 1: Update `SKILL.md` contract text**

Change the metadata header values:

```yaml
metadata:
  version: "2.24.0"
  updated_at: "2026-06-25"
```

In the Core Invariants area near existing `run_quality` bullets, add:

```markdown
- Finished operational-quality `run_quality.open_followups` records stable
  non-blocking executor debt signals: `agentlens_missing`,
  `missing_execution_worktree`, `readiness_fixable_issues`,
  `full_spec_fallback_present`, and
  `delegation_policy_prevented_all_delegation`. `completion_audit.passed=true`
  and `run_quality.grade=yellow` may coexist when product verification passed
  but executor evidence or efficiency follow-up remains.
```

- [ ] **Step 2: Update `references/state-schema.md`**

In the `run_quality` JSON example, include:

```json
"open_followups": ["agentlens_missing"],
"operational_debt": {
  "schema_version": "1",
  "followups": ["agentlens_missing"],
  "count": 1,
  "blocking": false
}
```

Below the example, add:

```markdown
`run_quality.grade` is an operational quality grade, not a replacement for
`completion_audit.passed`. A finished run may have `completion_audit.passed=true`
and `run_quality.grade=yellow` when implementation verification passed but
non-blocking executor follow-up remains.
```

- [ ] **Step 3: Update `references/execution-cycle.md`**

After the final validation step, add:

```markdown
When finalizing `run_quality`, include state-intrinsic operational debt
follow-ups before running `validate_state.py`. Read-only inspection may add
current observations such as `missing_execution_worktree` after completion
without mutating state; those observations use `observed_after_completion=true`.
```

- [ ] **Step 4: Update `HISTORY.md`**

Add a new top entry:

```markdown
## 2.24.0 - 2026-06-25

- Added stable CPE run-quality debt follow-ups for AgentLens gaps, missing
  execution worktrees, readiness fixable issues, full-spec fallback, and
  delegation policy local fallback.
- Clarified that `completion_audit.passed=true` can coexist with
  `run_quality.grade=yellow` when product verification passed but executor
  operational follow-up remains.
```

- [ ] **Step 5: Update `ARCHITECTURE.md`**

Add this sentence to the state/inspection architecture section:

```markdown
Run-quality operational debt is classified in
`scripts/run_quality_debt.py` so state validation and read-only inspection use
the same stable follow-up strings while keeping filesystem observations such as
missing execution worktrees out of finished-state hard validation.
```

- [ ] **Step 6: Run focused evals**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
python3 skills/kws-codex-plan-executor/evals/check_inspect_runs.py
python3 skills/kws-codex-plan-executor/evals/check_state_schema.py
python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py --skill skills/kws-codex-plan-executor/SKILL.md
```

Expected: all commands exit 0 and print passing JSON or no output for `check_skill_contract.py`.

- [ ] **Step 7: Run full CPE evals and syntax checks**

Run:

```bash
python3 skills/kws-codex-plan-executor/evals/run.sh
python3 -m py_compile skills/kws-codex-plan-executor/scripts/*.py skills/kws-codex-plan-executor/evals/*.py
bash -n skills/kws-codex-plan-executor/evals/run.sh
git diff --check
```

Expected: all commands exit 0. If `evals/run.sh` mutates only a baseline timestamp, restore that timestamp-only diff before committing.

- [ ] **Step 8: Commit Task 4**

```bash
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/HISTORY.md
git commit -m "docs(cpe): document run quality debt contract"
```

- [ ] **Step 9: Final review**

Run:

```bash
git status --short
git log --oneline -4
```

Expected: working tree is clean except unrelated user changes that existed before this plan execution. The latest four commits are the three implementation commits and the docs contract commit from this plan.
