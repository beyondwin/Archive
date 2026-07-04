# CPE Operational Quality Umbrella Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recent-run quality rubric, reduce repeated CPE yellow operational debt, and modularize CPE state validation without weakening execution safety.

**Architecture:** Start with deterministic run analysis so improvements are measured before behavior changes. Then add focused context/delegation/AgentLens evidence that distinguishes true risk from expected environment debt. Finally split `validate_state.py` behind the existing public CLI so future state-contract changes stay isolated and parity-tested.

**Tech Stack:** Python 3 standard library, Bash eval harness, Markdown docs, existing `skills/kws-codex-plan-executor` scripts/evals, Graphify command evidence.

## Global Constraints

- Do not change `completion_audit.passed` semantics.
- Do not hide `run_quality.yellow`; only reviewed or not-applicable debt may become green.
- Do not forbid all full-spec fallback; operator-reviewed fallback is allowed.
- Do not change `subagents=on` default.
- Do not bypass `spawn_agent` policy or infer explicit delegation where the user did not request it.
- Do not make AgentLens unavailable a blocking failure.
- Do not introduce breaking state schema changes while modularizing `validate_state.py`.
- Do not import Waygent TypeScript runtime into the CPE Python skill.
- Keep task packet JSON and `state.json` as the source of truth.
- Use only Python standard library for CPE scripts and evals.
- Runtime artifacts belong under `~/.codex/orchestrator/<run_id>/`; repository worktrees must not receive CPE state artifacts.

---

## File Structure

- Create `skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py`
  - Responsibility: aggregate recent CPE `state.json` files into a deterministic operational-quality rubric report.
- Modify `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
  - Responsibility: expose tri-state prompt/AgentLens/Graphify fields that the rubric can reuse.
- Create `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`
  - Responsibility: cover green, yellow, red, missing artifact, full-spec fallback, and expected local fallback scenarios.
- Modify `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
  - Responsibility: add fallback reason and suggested spec refs to packet mapping evidence.
- Modify `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
  - Responsibility: report fallback diagnosis and operator-reviewed fallback state.
- Modify `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`
  - Responsibility: keep plan audit fixable counts aligned with new fallback reasons.
- Modify `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
  - Responsibility: accept run-level delegation capability evidence and avoid task-level policy noise where spawning is globally unavailable.
- Modify `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
  - Responsibility: classify `agentlens_unavailable`, run-level expected local fallback, and reviewed full-spec fallback.
- Create `skills/kws-codex-plan-executor/scripts/cpe_state_validation/`
  - Responsibility: domain-specific validation modules used by the public `validate_state.py` CLI.
- Modify `skills/kws-codex-plan-executor/scripts/validate_state.py`
  - Responsibility: stay as the public CLI and delegate to `cpe_state_validation.validate`.
- Create `skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py`
  - Responsibility: prove modular validator parity against representative valid and invalid states.
- Modify `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`, `check_task_packet.py`, `check_run_readiness.py`, `check_plan_executability_audit.py`, `check_preflight_dispatch.py`, `check_state_schema.py`, `check_operational_run_quality.py`, and `evals/run.sh`
  - Responsibility: lock the new behavior in deterministic evals.
- Modify `skills/kws-codex-plan-executor/SKILL.md`, `README.md`, `ARCHITECTURE.md`, `references/state-schema.md`, `references/execution-cycle.md`, `docs/evals-and-verification.md`, `docs/state-and-logging.md`, `docs/eval-coverage-cpe.md`, `docs/verification-log.md`, and `HISTORY.md`
  - Responsibility: keep skill contract, operator docs, coverage map, verification log, and history aligned.

---

### Task 1: Recent Run Rubric Harness

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py`
- Create: `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`
- Modify: `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Consumes: `normalize_cpe_run.normalize(state: dict, context_text: str = "", final_output_text: str = "") -> dict[str, Any]`.
- Produces: `analyze_recent_runs.build_report(run_dirs: list[Path]) -> dict[str, Any]`.
- Produces CLI: `python3 scripts/analyze_recent_runs.py --codex-home ~/.codex --recent 5 --include-finished --output /tmp/report.json`.

- [ ] **Step 1: Write the failing recent-run rubric eval**

Create `skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_recent_runs.py"


def write_state(run_dir: Path, run_id: str, *, grade: str, followups: list[str], completion: bool = True) -> None:
    run_dir.mkdir(parents=True)
    state = {
        "schema_version": "1",
        "run_id": run_id,
        "mode": "interactive",
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "workspace": str(run_dir.parent.parent / "worktrees" / run_id),
        "worktree": str(run_dir.parent.parent / "worktrees" / run_id),
        "execution_worktree": str(run_dir.parent.parent / "worktrees" / run_id),
        "lifecycle_outcome": "finished",
        "subagents_requested": True,
        "completion_audit": {
            "passed": completion,
            "prompt_to_artifact_checklist": ["implemented requested artifacts"],
            "verification_evidence": [{"class": "verification_bundle", "name": "fixture"}],
            "residual_risk": [],
        },
        "run_quality": {
            "schema_version": "1",
            "grade": grade,
            "validation_status": "passed" if completion else "failed",
            "open_followups": followups,
            "readiness": {"fixable_issue_count": 0, "plan_executability_fixable_issue_count": 0},
            "dispatch_consistency": {},
            "context_quality": {"full_spec_fallback_count": 1 if "full_spec_fallback_present" in followups else 0},
            "verification_quality": {},
        },
        "tasks": {
            "task_1": {
                "status": "completed",
                "unit_manifest": {
                    "tool_policy": "implementation",
                    "allowed_write_globs": ["src/app.py"],
                    "forbidden_write_globs": [".git/**"],
                },
                "subagent_strategy": {
                    "mode": "local_fallback",
                    "reason": "spawn_agent tool policy requires explicit user delegation intent",
                    "run_ids": [],
                },
            }
        },
        "dispatch_decisions": [
            {
                "task_id": "task_1",
                "decision": "local_fallback",
                "reason": "spawn_agent tool policy requires explicit user delegation intent",
                "failed_prerequisites": ["spawn_policy_requires_explicit_user_request"],
            }
        ],
        "delegation_policy": {
            "requested_mode": "on",
            "requested_source": "default",
            "explicit_user_delegation_request": False,
            "spawn_policy": "explicit-request-required",
            "effective_mode": "local_fallback",
            "reason": "spawn_agent tool policy requires explicit user delegation intent",
            "policy_kind": "adaptive",
            "safety_gate": "failed",
            "value_gate": "skipped",
            "signals": {},
        },
    }
    (run_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-recent-rubric-") as temp:
        home = Path(temp)
        orch = home / ".codex" / "orchestrator"
        write_state(orch / "green-run", "green-run", grade="green", followups=[])
        write_state(orch / "yellow-run", "yellow-run", grade="yellow", followups=["full_spec_fallback_present", "delegation_policy_expected_local_fallback"])
        write_state(orch / "red-run", "red-run", grade="red", followups=["schema_drift"], completion=False)
        output = home / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--codex-home",
                str(home / ".codex"),
                "--recent",
                "3",
                "--include-finished",
                "--output",
                str(output),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        report = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
        summary = report.get("summary", {})
        rubric = report.get("rubric", {})
        checks["script_succeeds"] = result.returncode == 0
        checks["counts_runs"] = summary.get("finished_passed_count") == 2 and summary.get("run_count") == 3
        checks["counts_grades"] = summary.get("green_count") == 1 and summary.get("yellow_count") == 1 and summary.get("red_count") == 1
        checks["counts_debt"] = summary.get("full_spec_fallback_count") == 1 and summary.get("expected_local_fallback_count") == 1
        checks["rubric_dimensions"] = set(rubric) == {"safety", "context", "delegation_efficiency", "evidence", "validator_maintainability"}
        for name, passed in checks.items():
            if not passed:
                failures.append(name)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_recent_run_rubric.py
```

Expected: FAIL because `scripts/analyze_recent_runs.py` does not exist.

- [ ] **Step 3: Implement `analyze_recent_runs.py`**

Create `skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from normalize_cpe_run import normalize  # noqa: E402


RUBRIC_KEYS = ("safety", "context", "delegation_efficiency", "evidence", "validator_maintainability")


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"run_id": path.parent.name, "lifecycle_outcome": "invalid", "_load_error": True}
    return payload if isinstance(payload, dict) else {"run_id": path.parent.name, "_load_error": True}


def state_paths(codex_home: Path, include_finished: bool) -> list[Path]:
    paths = sorted((codex_home / "orchestrator").glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if include_finished:
        return paths
    result: list[Path] = []
    for path in paths:
        state = load_json(path)
        if state.get("lifecycle_outcome") not in {"finished", "failed", "blocked"}:
            result.append(path)
    return result


def grade_counts(normalized: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "green_count": sum(1 for item in normalized if item.get("run_quality_grade") == "green"),
        "yellow_count": sum(1 for item in normalized if item.get("run_quality_grade") == "yellow"),
        "red_count": sum(1 for item in normalized if item.get("run_quality_grade") == "red" or item.get("completion_passed") is False),
    }


def expected_local_fallback_count(item: dict[str, Any]) -> int:
    reasons = item.get("dispatch_decision_reasons")
    if not isinstance(reasons, dict):
        return 0
    return int(reasons.get("spawn_agent tool policy requires explicit user delegation intent", 0))


def worst_grade(values: list[str]) -> str:
    if "red" in values:
        return "red"
    if "yellow" in values:
        return "yellow"
    return "green"


def build_report(run_dirs: list[Path]) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        state = load_json(run_dir / "state.json")
        item = normalize(state)
        item["state_path"] = str(run_dir / "state.json")
        runs.append(item)
    counts = grade_counts(runs)
    summary = {
        "run_count": len(runs),
        "finished_passed_count": sum(1 for item in runs if item.get("terminal_state") == "finished" and item.get("completion_passed") is True),
        **counts,
        "full_spec_fallback_count": sum(int(item.get("full_spec_fallback_count") or 0) for item in runs),
        "expected_local_fallback_count": sum(expected_local_fallback_count(item) for item in runs),
    }
    rubric = {
        "safety": "red" if counts["red_count"] else "green",
        "context": "yellow" if summary["full_spec_fallback_count"] else "green",
        "delegation_efficiency": "yellow" if summary["expected_local_fallback_count"] else "green",
        "evidence": worst_grade(["yellow" if not item.get("verification_evidence_classes") else "green" for item in runs]),
        "validator_maintainability": "yellow",
    }
    return {"schema_version": "1", "summary": summary, "rubric": rubric, "runs": runs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze recent CPE runs into an operational-quality rubric.")
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--recent", type=int, default=5)
    parser.add_argument("--include-finished", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    paths = state_paths(Path(args.codex_home).expanduser(), include_finished=args.include_finished)[: args.recent]
    report = build_report([path.parent for path in paths])
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Extend normalized replay tri-state fields**

Modify `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py` in `normalize()` so the returned dict includes:

```python
        "prompt_audit_status": "passed"
        if prompt_audit.get("passed") is True or prompt_audit.get("dynamic_marker_violations") == []
        else ("missing" if not prompt_audit else "failed"),
        "graphify_status": "fresh" if graphify.get("fresh") is True else ("missing" if not graphify else "stale"),
        "agentlens_status": "recorded" if state.get("agentlens_orchestration_run") else (
            "not_applicable" if state.get("mode") in {"prompt", "handoff"} else "unavailable"
        ),
```

Keep existing `prompt_audit_passed` and `graphify_fresh` fields for compatibility.

- [ ] **Step 5: Extend replay eval and run harness**

In `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`, add checks that a fixture with no `agentlens_orchestration_run` and `mode=interactive` returns `agentlens_status="unavailable"`, and a fixture with `mode=prompt` returns `agentlens_status="not_applicable"`.

In `skills/kws-codex-plan-executor/evals/run.sh`, add:

```bash
python3 "$EVAL_DIR/check_recent_run_rubric.py" >/dev/null
```

Place it near `check_cpe_replay.py`.

- [ ] **Step 6: Run GREEN**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_recent_run_rubric.py
python3 evals/check_cpe_replay.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py \
  skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py \
  skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py \
  skills/kws-codex-plan-executor/evals/check_cpe_replay.py \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "feat(cpe): add recent run quality rubric"
```

---

### Task 2: Full-Spec Fallback Diagnosis

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/build_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_task_packet.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_run_readiness.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`

**Interfaces:**
- Produces packet mapping fields: `fallback_reason: str`, `suggested_spec_refs: list[str]`, `operator_reviewed: bool`.
- Consumes existing `spec.mapping.candidate_scores`.
- Produces readiness issue extras: `fallback_reason`, `suggested_spec_refs`.

- [ ] **Step 1: Add failing task packet eval**

In `skills/kws-codex-plan-executor/evals/check_task_packet.py`, extend the existing full-spec fallback case to assert:

```python
        mapping = fallback.get("spec", {}).get("mapping", {})
        checks["fallback_mapping_reason_and_suggestions"] = (
            mapping.get("fallback_reason") == "weak_heuristic_match"
            and isinstance(mapping.get("suggested_spec_refs"), list)
            and mapping.get("operator_reviewed") is False
        )
        if not checks["fallback_mapping_reason_and_suggestions"]:
            failures.append("full-spec fallback should explain reason and suggested spec refs")
```

- [ ] **Step 2: Add failing readiness eval**

In `skills/kws-codex-plan-executor/evals/check_run_readiness.py`, update the fallback packet fixture so `packet["spec"]["mapping"]` includes:

```python
{
    "fallback_reason": "missing_spec_refs",
    "suggested_spec_refs": ["problem", "goals"],
    "operator_reviewed": False,
}
```

Then assert the readiness issue preserves these fields:

```python
        fallback_issue = next(item for item in payload["issues"] if item["kind"] == "full_spec_fallback")
        checks["full_spec_fallback_has_reason"] = (
            fallback_issue.get("fallback_reason") == "missing_spec_refs"
            and fallback_issue.get("suggested_spec_refs") == ["problem", "goals"]
        )
        if not checks["full_spec_fallback_has_reason"]:
            failures.append("readiness audit should include full-spec fallback reason and suggestions")
```

- [ ] **Step 3: Run RED**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
```

Expected: FAIL because fallback mapping does not yet include reason/suggestions.

- [ ] **Step 4: Implement fallback diagnosis helpers**

In `skills/kws-codex-plan-executor/scripts/build_task_packet.py`, add:

```python
def fallback_reason(task: dict, candidate_scores: list[dict]) -> str:
    explicit = [item for item in task.get("spec_refs", []) if isinstance(item, str) and item.strip()]
    if not explicit and not candidate_scores:
        return "missing_spec_refs"
    if candidate_scores:
        return "weak_heuristic_match"
    return "manifest_gap"


def suggested_spec_refs(candidate_scores: list[dict]) -> list[str]:
    result: list[str] = []
    for item in candidate_scores[:3]:
        section_id = item.get("section_id")
        if isinstance(section_id, str) and section_id not in result:
            result.append(section_id)
    return result
```

In `resolve_sections()`, replace the fallback mapping payload with:

```python
    reason = fallback_reason(task, candidate_scores)
    return ["*"], True, {
        "selected_section_ids": ["*"],
        "candidate_scores": candidate_scores,
        "mapping_reason": "No task-specific spec section matched; using full spec fallback.",
        "requires_parent_mapping": True,
        "source": "fallback",
        "fallback_reason": reason,
        "suggested_spec_refs": suggested_spec_refs(candidate_scores),
        "operator_reviewed": False,
    }
```

- [ ] **Step 5: Propagate readiness evidence**

In `skills/kws-codex-plan-executor/scripts/audit_run_readiness.py`, change the `full_spec_fallback` issue block to:

```python
    if spec.get("fallback_used") is True:
        mapping = spec.get("mapping") if isinstance(spec.get("mapping"), dict) else {}
        reviewed = mapping.get("operator_reviewed") is True
        severity = "fixable" if not reviewed else "info"
        issues.append(
            issue(
                task_id,
                severity,
                "full_spec_fallback",
                "Task packet uses full spec fallback instead of task-specific spec sections.",
                fallback_reason=mapping.get("fallback_reason") or "unknown",
                suggested_spec_refs=list_strings(mapping.get("suggested_spec_refs")),
                operator_reviewed=reviewed,
            )
        )
```

Update summary counts so `info` issues do not increment blocking or fixable counts.

- [ ] **Step 6: Align plan executability audit**

In `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`, when packet `spec.fallback_used` is true, append `full_spec_fallback` to fixable issues only when `spec.mapping.operator_reviewed` is not true.

Use:

```python
    if packet and isinstance(packet.get("spec"), dict) and packet["spec"].get("fallback_used") is True:
        mapping = packet["spec"].get("mapping") if isinstance(packet["spec"].get("mapping"), dict) else {}
        if mapping.get("operator_reviewed") is not True:
            fixable.append("full_spec_fallback")
```

- [ ] **Step 7: Run GREEN**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
python3 evals/check_plan_executability_audit.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/build_task_packet.py \
  skills/kws-codex-plan-executor/scripts/audit_run_readiness.py \
  skills/kws-codex-plan-executor/scripts/audit_plan_executability.py \
  skills/kws-codex-plan-executor/evals/check_task_packet.py \
  skills/kws-codex-plan-executor/evals/check_run_readiness.py \
  skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py
git commit -m "feat(cpe): diagnose full spec fallback quality"
```

---

### Task 3: Run-Level Delegation Capability And AgentLens Status

**Files:**
- Modify: `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`
- Modify: `skills/kws-codex-plan-executor/scripts/run_quality_debt.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_state_schema.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_cpe_replay.py`

**Interfaces:**
- Produces state field `delegation_capability: dict`.
- Produces normalized fields `agentlens_status`, `delegation_capability_effective_mode`.
- Consumes existing `delegation_policy` and `dispatch_decisions`.

- [ ] **Step 1: Add failing dispatch eval for run-level capability**

In `skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`, add a case that runs `preflight_dispatch.py` with:

```bash
--spawn-policy explicit-request-required
--explicit-delegation-requested false
--requested-subagents on
```

Assert:

```python
checks["run_level_delegation_capability_emitted"] = (
    data.get("state_updates", {}).get("delegation_capability", {}).get("run_level_effective_mode") == "local_fallback"
    and data["state_updates"]["delegation_capability"]["reason"] == "spawn_agent tool policy requires explicit user delegation intent"
)
```

- [ ] **Step 2: Add failing state schema eval**

In `skills/kws-codex-plan-executor/evals/check_state_schema.py`, add a valid state fixture with:

```python
state["delegation_capability"] = {
    "schema_version": "1",
    "spawn_policy": "explicit-request-required",
    "explicit_user_delegation_request": False,
    "run_level_effective_mode": "local_fallback",
    "reason": "spawn_agent tool policy requires explicit user delegation intent",
}
state["agentlens_status"] = {
    "schema_version": "1",
    "status": "agentlens_unavailable",
    "blocking": False,
}
```

Assert validator return code is `0`.

- [ ] **Step 3: Run RED**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
```

Expected: FAIL because `delegation_capability` and `agentlens_status` are not validated/emitted yet.

- [ ] **Step 4: Emit delegation capability**

In `skills/kws-codex-plan-executor/scripts/preflight_dispatch.py`, add:

```python
def delegation_capability_payload(args: argparse.Namespace, reason: str, decision: str) -> dict:
    return {
        "schema_version": "1",
        "spawn_policy": args.spawn_policy,
        "explicit_user_delegation_request": args.explicit_delegation_requested == "true",
        "run_level_effective_mode": "delegate" if decision == "delegate" else "local_fallback",
        "reason": reason,
    }
```

In `decision_payload()`, add a `delegation_capability` parameter and include it under `state_updates`.

At the final payload call, pass:

```python
delegation_capability_payload(args, reason, decision)
```

- [ ] **Step 5: Validate new optional fields**

In `skills/kws-codex-plan-executor/scripts/validate_state.py`, add validation helpers:

```python
def _validate_delegation_capability(data: dict, errors: list[str]) -> None:
    value = data.get("delegation_capability")
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append("delegation_capability must be an object")
        return
    if value.get("schema_version") != "1":
        errors.append("delegation_capability.schema_version must be 1")
    if value.get("spawn_policy") not in VALID_SPAWN_POLICIES:
        errors.append("delegation_capability.spawn_policy invalid")
    if not isinstance(value.get("explicit_user_delegation_request"), bool):
        errors.append("delegation_capability.explicit_user_delegation_request must be a boolean")
    if value.get("run_level_effective_mode") not in {"delegate", "local_fallback", "blocked", "off"}:
        errors.append("delegation_capability.run_level_effective_mode invalid")
    if not _has_substantive_value(value.get("reason")):
        errors.append("delegation_capability.reason must be non-empty")


def _validate_agentlens_status(data: dict, errors: list[str]) -> None:
    value = data.get("agentlens_status")
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append("agentlens_status must be an object")
        return
    if value.get("schema_version") != "1":
        errors.append("agentlens_status.schema_version must be 1")
    if value.get("status") not in {"agentlens_unavailable", "agentlens_emit_failed", "agentlens_not_applicable", "agentlens_recorded"}:
        errors.append("agentlens_status.status invalid")
    if not isinstance(value.get("blocking"), bool):
        errors.append("agentlens_status.blocking must be a boolean")
```

Call both helpers from `validate(data)`.

- [ ] **Step 6: Update run quality debt and replay**

In `run_quality_debt.py`, treat `delegation_capability.run_level_effective_mode == "local_fallback"` with explicit-request policy as `DELEGATION_POLICY_EXPECTED_LOCAL_FALLBACK` without requiring every task dispatch reason to repeat the same text.

In `normalize_cpe_run.py`, add:

```python
        "delegation_capability_effective_mode": (
            state.get("delegation_capability", {}).get("run_level_effective_mode")
            if isinstance(state.get("delegation_capability"), dict)
            else None
        ),
```

- [ ] **Step 7: Run GREEN**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_preflight_dispatch.py
python3 evals/check_operational_run_quality.py
python3 evals/check_state_schema.py
python3 evals/check_cpe_replay.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/preflight_dispatch.py \
  skills/kws-codex-plan-executor/scripts/run_quality_debt.py \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py \
  skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py \
  skills/kws-codex-plan-executor/evals/check_operational_run_quality.py \
  skills/kws-codex-plan-executor/evals/check_state_schema.py \
  skills/kws-codex-plan-executor/evals/check_cpe_replay.py
git commit -m "feat(cpe): summarize delegation and agentlens capability"
```

---

### Task 4: Validator Module Shell And Parity Harness

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/__init__.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/common.py`
- Create: `skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`

**Interfaces:**
- Produces: `cpe_state_validation.validate(data: dict) -> list[str]`.
- Public CLI remains: `python3 scripts/validate_state.py <state>`.

- [ ] **Step 1: Write parity eval**

Create `skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


VALIDATOR = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"


def base_state(run_dir: Path) -> dict:
    return {
        "schema_version": "1",
        "run_id": "parity-run",
        "mode": "interactive",
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "workspace": str(run_dir.parent / "worktrees" / "parity-run"),
        "worktree": str(run_dir.parent / "worktrees" / "parity-run"),
        "execution_worktree": str(run_dir.parent / "worktrees" / "parity-run"),
        "lifecycle_outcome": "finished",
        "subagents_requested": False,
        "context_snapshot_path": str(run_dir / "context.json"),
        "context_basis_hash": "a" * 64,
        "context_health": {"status": "green", "next_action": "complete", "handoff_ready": True},
        "completion_audit": {
            "passed": True,
            "prompt_to_artifact_checklist": ["artifact matches prompt"],
            "verification_evidence": [{"class": "verification_bundle", "name": "parity"}],
            "residual_risk": [],
        },
        "tasks": {},
    }


def run_validator(state: dict, path: Path) -> subprocess.CompletedProcess[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "context.json").write_text(json.dumps({"basis_hash": state["context_basis_hash"]}) + "\n", encoding="utf-8")
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(VALIDATOR), str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-validate-parity-") as temp:
        run_dir = Path(temp) / "orchestrator" / "parity-run"
        valid = base_state(run_dir)
        result = run_validator(valid, run_dir / "state.json")
        checks["valid_state_passes"] = result.returncode == 0
        invalid = base_state(run_dir / "invalid")
        invalid["completion_audit"]["passed"] = False
        result = run_validator(invalid, run_dir / "invalid" / "state.json")
        checks["invalid_finished_completion_fails"] = result.returncode != 0 and "completion_audit.passed" in (result.stderr + result.stdout)
    for name, passed in checks.items():
        if not passed:
            failures.append(name)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run baseline parity**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_validate_state_modular_parity.py
```

Expected: PASS against current CLI. This establishes the parity harness before extraction.

- [ ] **Step 3: Create module package shell**

Create `skills/kws-codex-plan-executor/scripts/cpe_state_validation/__init__.py`:

```python
from __future__ import annotations

from typing import Any


def validate(data: dict[str, Any]) -> list[str]:
    from validate_state import validate as legacy_validate

    return legacy_validate(data)
```

Create `skills/kws-codex-plan-executor/scripts/cpe_state_validation/common.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


def has_substantive_value(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def path_is_under(path: str, parent: str) -> bool:
    try:
        Path(path).resolve(strict=False).relative_to(Path(parent).resolve(strict=False))
        return True
    except ValueError:
        return False
```

This shell is intentionally a bridge. Later tasks replace the legacy import with domain modules.

- [ ] **Step 4: Wire eval harness**

Add to `skills/kws-codex-plan-executor/evals/run.sh`:

```bash
python3 "$EVAL_DIR/check_validate_state_modular_parity.py" >/dev/null
```

Place it after `check_state_schema.py`.

- [ ] **Step 5: Run GREEN**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_validate_state_modular_parity.py
./evals/run.sh
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/cpe_state_validation \
  skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "test(cpe): add validator modular parity harness"
```

---

### Task 5: Extract Completion, Audit, And Evidence Validators

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/completion.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/graphify.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/plan_audit.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/prompt_cache.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/__init__.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py`

**Interfaces:**
- Produces module functions:
  - `completion.validate_completion(data: dict, errors: list[str]) -> None`
  - `graphify.validate_graphify(data: dict, errors: list[str]) -> None`
  - `plan_audit.validate_plan_audit(data: dict, errors: list[str]) -> None`
  - `prompt_cache.validate_prompt_cache(data: dict, errors: list[str]) -> None`

- [ ] **Step 1: Add parity cases for each domain**

Extend `check_validate_state_modular_parity.py` with invalid states:

```python
        graphify_invalid = base_state(run_dir / "graphify-invalid")
        graphify_invalid["graphify_audit"] = {"schema_version": "1", "graphify_present": True, "update_required": False, "fresh": True, "errors": ["boom"], "warnings": []}
        result = run_validator(graphify_invalid, run_dir / "graphify-invalid" / "state.json")
        checks["graphify_errors_fail_finished_state"] = result.returncode != 0 and "graphify_audit.errors" in (result.stderr + result.stdout)

        prompt_invalid = base_state(run_dir / "prompt-invalid")
        prompt_invalid["prompt_audit"] = {"schema_version": "1", "dynamic_marker_violations": ["timestamp"]}
        result = run_validator(prompt_invalid, run_dir / "prompt-invalid" / "state.json")
        checks["prompt_dynamic_markers_fail_finished_state"] = result.returncode != 0 and "dynamic_marker_violations" in (result.stderr + result.stdout)

        plan_invalid = base_state(run_dir / "plan-invalid")
        plan_invalid["plan_executability_audit"] = {"path": "", "grade": "red", "blocking_issue_count": 1, "fixable_issue_count": 0}
        result = run_validator(plan_invalid, run_dir / "plan-invalid" / "state.json")
        checks["red_plan_audit_fails_finished_state"] = result.returncode != 0 and "plan_executability_audit" in (result.stderr + result.stdout)
```

- [ ] **Step 2: Run parity tests before extraction**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_validate_state_modular_parity.py
```

Expected: PASS against current validator.

- [ ] **Step 3: Move functions unchanged into modules**

Move these functions from `validate_state.py` into domain modules, preserving error text:

- `completion.py`: `_validate_completion_audit`, residual-risk helper functions, verification evidence validation helpers.
- `graphify.py`: `_validate_graphify_audit`.
- `plan_audit.py`: `_validate_plan_executability_audit`.
- `prompt_cache.py`: `_validate_prompt_audit`.

In each module, import shared helpers from `common.py`. If a helper is still in `validate_state.py`, move it to `common.py` with the same behavior and update imports.

Example module shape:

```python
from __future__ import annotations

from typing import Any

from .common import has_substantive_value


def validate_completion(data: dict[str, Any], errors: list[str]) -> None:
    audit = data.get("completion_audit")
    # Body copied from former _validate_completion_audit without changing error strings.
```

- [ ] **Step 4: Delegate from public validator**

In `validate_state.py`, import:

```python
from cpe_state_validation.completion import validate_completion
from cpe_state_validation.graphify import validate_graphify
from cpe_state_validation.plan_audit import validate_plan_audit
from cpe_state_validation.prompt_cache import validate_prompt_cache
```

Replace the corresponding private helper calls in `validate(data)` with the new functions.

- [ ] **Step 5: Run GREEN**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_validate_state_modular_parity.py
python3 evals/check_state_schema.py
python3 evals/check_graphify_freshness.py
python3 evals/check_prompt_cache_audit.py
python3 evals/check_plan_executability_audit.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/cpe_state_validation \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py
git commit -m "refactor(cpe): extract evidence state validators"
```

---

### Task 6: Extract Run Quality, Delegation, Task, Context, And Recovery Validators

**Files:**
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/run_quality.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/delegation.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/tasks.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/context.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/recovery.py`
- Modify: `skills/kws-codex-plan-executor/scripts/cpe_state_validation/__init__.py`
- Modify: `skills/kws-codex-plan-executor/scripts/validate_state.py`
- Modify: `skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py`

**Interfaces:**
- Produces module functions:
  - `run_quality.validate_run_quality(data: dict, errors: list[str]) -> None`
  - `delegation.validate_delegation(data: dict, errors: list[str]) -> None`
  - `tasks.validate_tasks(data: dict, errors: list[str]) -> None`
  - `context.validate_context(data: dict, errors: list[str]) -> None`
  - `recovery.validate_recovery(data: dict, errors: list[str]) -> None`

- [ ] **Step 1: Add parity cases for remaining domains**

Extend `check_validate_state_modular_parity.py` with:

```python
        quality_invalid = base_state(run_dir / "quality-invalid")
        quality_invalid["run_quality"] = {"schema_version": "1", "grade": "green", "validation_status": "passed", "open_followups": ["agentlens_missing"]}
        result = run_validator(quality_invalid, run_dir / "quality-invalid" / "state.json")
        checks["green_run_quality_with_followups_fails"] = result.returncode != 0 and "run_quality.grade" in (result.stderr + result.stdout)

        delegation_invalid = base_state(run_dir / "delegation-invalid")
        delegation_invalid["delegation_policy"] = {"requested_mode": "invalid"}
        result = run_validator(delegation_invalid, run_dir / "delegation-invalid" / "state.json")
        checks["invalid_delegation_policy_fails"] = result.returncode != 0 and "delegation_policy" in (result.stderr + result.stdout)

        task_invalid = base_state(run_dir / "task-invalid")
        task_invalid["subagents_requested"] = True
        task_invalid["tasks"] = {
            "task_1": {
                "status": "completed",
                "unit_manifest": {"tool_policy": "implementation", "allowed_write_globs": ["src/app.py"]},
            }
        }
        result = run_validator(task_invalid, run_dir / "task-invalid" / "state.json")
        checks["completed_write_task_requires_strategy"] = result.returncode != 0 and "subagent_strategy" in (result.stderr + result.stdout)
```

- [ ] **Step 2: Run parity tests before extraction**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_validate_state_modular_parity.py
```

Expected: PASS against current validator.

- [ ] **Step 3: Extract remaining validators**

Move these groups unchanged, preserving error text:

- `run_quality.py`: `_validate_operational_run_quality` and the `delegation_capability`/`agentlens_status` validation added in Task 3.
- `delegation.py`: `_validate_dispatch_decisions`, delegation policy validation helpers, subagent run store validation.
- `tasks.py`: task validation, `_validate_subagent_strategy`, task packet path/hash checks.
- `context.py`: context snapshot, context health, compaction, command cwd evidence checks.
- `recovery.py`: command observations, recovery attempts, blocker/failure decision validation.

Update imports so `validate_state.py` owns only CLI parsing, top-level orchestration, and backward-compatible `validate(data)`.

- [ ] **Step 4: Finalize `cpe_state_validation.__init__`**

Replace the temporary legacy bridge with:

```python
from __future__ import annotations

from typing import Any

from .completion import validate_completion
from .context import validate_context
from .delegation import validate_delegation
from .graphify import validate_graphify
from .plan_audit import validate_plan_audit
from .prompt_cache import validate_prompt_cache
from .recovery import validate_recovery
from .run_quality import validate_run_quality
from .tasks import validate_tasks


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    validate_completion(data, errors)
    validate_context(data, errors)
    validate_graphify(data, errors)
    validate_plan_audit(data, errors)
    validate_prompt_cache(data, errors)
    validate_delegation(data, errors)
    validate_run_quality(data, errors)
    validate_tasks(data, errors)
    validate_recovery(data, errors)
    return errors
```

If current `validate_state.py` has top-level validations not covered by these domains, keep those in `validate_state.py` and call `validate_domains(data, errors)` instead of replacing the entire function. Do not delete top-level validations without parity coverage.

- [ ] **Step 5: Run GREEN**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_validate_state_modular_parity.py
python3 evals/check_state_schema.py
python3 evals/check_operational_run_quality.py
python3 evals/check_inspect_runs.py
python3 evals/check_repair_runs.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/scripts/cpe_state_validation \
  skills/kws-codex-plan-executor/scripts/validate_state.py \
  skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py
git commit -m "refactor(cpe): modularize state validation domains"
```

---

### Task 7: Contract Docs, Release Alignment, And Full Verification

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- Modify: `skills/kws-codex-plan-executor/docs/state-and-logging.md`
- Modify: `skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Create: `skills/kws-codex-plan-executor/evals/baselines/v2.26.0.json`

**Interfaces:**
- Consumes: behavior and fields from Tasks 1-6.
- Produces: documented CPE contract and release-aligned eval baseline.

- [ ] **Step 1: Update skill contract docs**

Update `SKILL.md` Core Invariants with these bullets:

```markdown
- Recent-run inspection may aggregate finished states with `scripts/analyze_recent_runs.py`; rubric reports are derived evidence and never replace `state.json` or `completion_audit`.
- Full-spec fallback records a structured mapping reason and suggested `spec_refs`; unreviewed fallback remains operational-quality debt, while explicitly reviewed fallback may be context-green when the context budget is not red.
- Delegation capability may be recorded at run level when spawn policy prevents all task spawning; this only changes operational-debt accounting and does not skip local task gates.
- AgentLens status is best-effort and classified as recorded, unavailable, emit-failed, or not-applicable; AgentLens failure cannot block product verification.
- `validate_state.py` remains the public validation CLI even when validation logic is split across domain modules.
```

- [ ] **Step 2: Update reference docs**

In `references/state-schema.md`, add sections for:

```markdown
### delegation_capability

Optional object with `schema_version`, `spawn_policy`,
`explicit_user_delegation_request`, `run_level_effective_mode`, and `reason`.

### agentlens_status

Optional object with `schema_version`, `status`, and `blocking`.

### spec.mapping fallback diagnosis

Task packets may include `fallback_reason`, `suggested_spec_refs`,
and `operator_reviewed` inside `spec.mapping`.
```

In `references/execution-cycle.md`, add the new order:

```markdown
Run recent-run rubric only for inspection. During execution, create task packets,
run readiness and plan executability audits, record run-level delegation
capability before per-task dispatch, and preserve task-local gates even when
spawning is policy-disabled.
```

- [ ] **Step 3: Update README and architecture**

In `README.md`, add `scripts/analyze_recent_runs.py` to the validation/inspection list and document that it reads recent run state without raw transcripts.

In `ARCHITECTURE.md`, add a short paragraph:

```markdown
Recent-run rubric reports sit beside inspection and normalized replay. They
aggregate state-derived evidence across runs so operator debt can be improved
without weakening per-run completion gates.
```

- [ ] **Step 4: Update eval docs and history**

In `docs/evals-and-verification.md` and `docs/eval-coverage-cpe.md`, add entries for:

- `check_recent_run_rubric.py`
- `check_validate_state_modular_parity.py`
- full-spec fallback diagnosis coverage
- run-level delegation capability coverage

In `HISTORY.md`, add an unreleased entry:

```markdown
- Added recent-run operational-quality rubric, full-spec fallback diagnosis,
  run-level delegation capability evidence, AgentLens status classification,
  and modular state validation parity coverage.
```

- In `SKILL.md`, update `metadata.version` to `2.26.0`.

- [ ] **Step 5: Run full verification**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
bun run check
```

Expected:

- `./evals/run.sh`: PASS.
- `python3 -m py_compile scripts/*.py evals/*.py`: PASS.
- `bash -n evals/run.sh`: PASS.
- `git diff --check`: PASS.
- `bun run check`: PASS.

- [ ] **Step 6: Run Graphify update and audit**

```bash
cd /Users/kws/source/private/Archive
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . \
  --update-ran \
  --output /tmp/cpe-operational-quality-graphify.json
```

Expected: command completes. If `graphify-out/` is ignored or unchanged, record that in `docs/verification-log.md`.

- [ ] **Step 7: Update release baseline for 2.26.0**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh --update-baseline
```

Expected: creates `evals/baselines/v2.26.0.json` with `"version": "2.26.0"`.

- [ ] **Step 8: Commit Task 7**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/ARCHITECTURE.md \
  skills/kws-codex-plan-executor/references/state-schema.md \
  skills/kws-codex-plan-executor/references/execution-cycle.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md \
  skills/kws-codex-plan-executor/docs/state-and-logging.md \
  skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md \
  skills/kws-codex-plan-executor/docs/verification-log.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/evals/baselines/v2.26.0.json \
  graphify-out/GRAPH_REPORT.md \
  graphify-out/graph.json
git commit -m "docs(cpe): document operational quality umbrella"
```

If `graphify-out/` has no tracked changes, omit those paths from `git add`.

---

## Final Closeout

- [ ] Run final status check:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
```

Expected: only intentional branch-ahead state remains.

- [ ] Run final CPE smoke:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 scripts/analyze_recent_runs.py --codex-home ~/.codex --recent 5 --include-finished --output /tmp/cpe-recent-run-rubric.json
python3 -m json.tool /tmp/cpe-recent-run-rubric.json >/dev/null
```

Expected: both commands pass and the report contains `schema_version=1`, `summary`, `rubric`, and `runs`.

- [ ] Report changed commits, verification commands, and any residual non-blocking risk.
