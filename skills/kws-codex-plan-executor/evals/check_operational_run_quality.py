#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import check_state_schema


def load_run_quality_debt():
    script_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import run_quality_debt

    return run_quality_debt


def run_validator(payload: dict) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"
    with tempfile.TemporaryDirectory(prefix="cpe-run-quality-") as temp:
        state_path = Path(temp) / "state.json"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(script), str(state_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def v222_state() -> dict:
    state = check_state_schema.v220_state()
    state["agentlens_orchestration_run"] = "agentlens-run-123"
    state["source_workspace"] = "/tmp/source"
    state["execution_worktree"] = state["worktree"]
    state["command_cwd_evidence"] = [
        {
            "command": 'python3 scripts/preflight_local_env.py --repo-root "$WORKTREE_ABS"',
            "cwd": state["worktree"],
            "phase": "preflight",
            "status": "passed",
        }
    ]
    state["delegation_policy"] = {
        "requested_mode": "on",
        "requested_source": "default",
        "explicit_user_delegation_request": False,
        "spawn_policy": "explicit-request-required",
        "effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
    }
    state["preflight_bootstrap"] = {
        "schema_version": "1",
        "warnings": [],
        "bootstrap_plan": [],
        "environment_capabilities": {"node": "present", "agentlens": "absent"},
    }
    state["run_quality"] = {
        "schema_version": "1",
        "validation_status": "passed",
        "terminal_state": "finished",
        "stale": False,
        "workspace_matches_execution_worktree": True,
        "score": 92,
        "grade": "green",
        "schema_drift": [],
        "open_followups": [],
        "readiness": {"task_count": 1, "fixable_issue_count": 0, "blocking_issue_count": 0},
        "dispatch_consistency": {"mismatch_count": 0, "override_count": 0},
        "context_quality": {"full_spec_fallback_count": 0},
        "verification_quality": {"completion_audit_passed": True},
        "recommendations": [],
        "summary": "Run finished with validated state.",
    }
    state["dispatch_decisions"] = [
        {
            "schema_version": "1",
            "task_id": "task_0",
            "decision": "delegate",
            "reason": "Default subagent-first execution for an eligible task packet.",
            "write_scope": ["docs/example.md"],
            "failed_prerequisites": [],
        }
    ]
    return state


def run_static_fixture() -> tuple[subprocess.CompletedProcess[str], dict]:
    script = Path(__file__).resolve().parent / "static_execution_runner.py"
    with tempfile.TemporaryDirectory(prefix="cpe-static-quality-") as temp:
        root = Path(temp)
        repo = root / "repo"
        eval_home = root / "home"
        repo.mkdir()
        eval_home.mkdir()
        (repo / "plan.md").write_text("### Task 0\n\n**Files:**\n- Create: docs/example.md\n", encoding="utf-8")
        (repo / "spec.md").write_text('Write exact text "hello static".\n', encoding="utf-8")
        fixture = root / "fixture.yaml"
        fixture.write_text(
            "\n".join(
                [
                    "name: operational quality fixture",
                    "mode: interactive",
                    "expected:",
                    "  files_changed:",
                    "    - docs/example.md",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--fixture",
                str(fixture),
                "--workdir",
                str(repo),
                "--eval-home",
                str(eval_home),
                "--final-output",
                str(root / "final.md"),
                "--run-log",
                str(root / "run.jsonl"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        state_paths = sorted((eval_home / ".codex" / "orchestrator").glob("*/state.json"))
        state = json.loads(state_paths[-1].read_text(encoding="utf-8")) if state_paths else {}
        return result, state


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    valid = run_validator(v222_state())
    checks["valid_v222_state_passes"] = valid.returncode == 0
    if not checks["valid_v222_state_passes"]:
        failures.append("valid v2.22 state should pass: " + (valid.stderr or valid.stdout))

    missing_quality = v222_state()
    missing_quality.pop("run_quality")
    invalid_missing_quality = run_validator(missing_quality)
    checks["finished_v222_requires_run_quality"] = (
        invalid_missing_quality.returncode != 0 and "run_quality must be present" in invalid_missing_quality.stderr
    )
    if not checks["finished_v222_requires_run_quality"]:
        failures.append("finished v2.22 state should require embedded run_quality")

    incomplete_quality = v222_state()
    incomplete_quality["run_quality"].pop("verification_quality")
    invalid_incomplete_quality = run_validator(incomplete_quality)
    checks["finished_run_quality_requires_verification_quality"] = (
        invalid_incomplete_quality.returncode != 0 and "run_quality.verification_quality" in invalid_incomplete_quality.stderr
    )
    if not checks["finished_run_quality_requires_verification_quality"]:
        failures.append("finished run_quality should include verification_quality")

    bad_policy = v222_state()
    bad_policy["delegation_policy"]["effective_mode"] = "maybe"
    invalid = run_validator(bad_policy)
    checks["invalid_delegation_policy_fails"] = (
        invalid.returncode != 0 and "delegation_policy.effective_mode" in invalid.stderr
    )
    if not checks["invalid_delegation_policy_fails"]:
        failures.append("invalid delegation_policy.effective_mode should fail")

    bad_worktree = v222_state()
    bad_worktree["execution_worktree"] = "/tmp/not-a-codex-worktree"
    invalid_worktree = run_validator(bad_worktree)
    checks["invalid_execution_worktree_fails"] = (
        invalid_worktree.returncode != 0 and "execution_worktree" in invalid_worktree.stderr
    )
    if not checks["invalid_execution_worktree_fails"]:
        failures.append("execution_worktree outside .codex/worktrees/<run_id> should fail")

    bad_quality = v222_state()
    bad_quality["run_quality"]["score"] = 120
    invalid_quality = run_validator(bad_quality)
    checks["invalid_run_quality_score_fails"] = (
        invalid_quality.returncode != 0 and "run_quality.score" in invalid_quality.stderr
    )
    if not checks["invalid_run_quality_score_fails"]:
        failures.append("run_quality.score outside 0..100 should fail")

    debt = load_run_quality_debt()

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
        and info_taxonomy.get("informational_followups")
        == ["agentlens_missing", "delegation_policy_expected_local_fallback"]
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

    unknown_state = v222_state()
    unknown_followups = ["mystery_followup_token"]
    unknown_taxonomy = debt.followup_taxonomy(unknown_state, unknown_followups)
    checks["taxonomy_defaults_unknown_followups_actionable"] = (
        unknown_taxonomy.get("actionable_followups") == ["mystery_followup_token"]
        and unknown_taxonomy.get("informational_followups") == []
        and debt.report_class_for(unknown_state, unknown_followups, unknown_taxonomy, "passed") == "yellow"
    )
    if not checks["taxonomy_defaults_unknown_followups_actionable"]:
        failures.append("unknown followups should default to actionable and keep the report yellow")

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
        "delegation_policy_expected_local_fallback",
    ]
    if not checks["debt_helper_reports_stable_followups"]:
        failures.append("run_quality_debt.stable_followups should report state-intrinsic debt in stable order")

    capability_state = v222_state()
    capability_state["dispatch_decisions"] = []
    capability_state["delegation_capability"] = {
        "schema_version": "1",
        "spawn_policy": "explicit-request-required",
        "explicit_user_delegation_request": False,
        "run_level_effective_mode": "local_fallback",
        "reason": "spawn_agent tool policy requires explicit user delegation intent",
    }
    checks["run_level_capability_reports_expected_local_fallback"] = (
        debt.stable_followups(capability_state) == ["delegation_policy_expected_local_fallback"]
    )
    if not checks["run_level_capability_reports_expected_local_fallback"]:
        failures.append("run-level delegation capability should report expected local fallback once")

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

    explicit_delegation_state = v222_state()
    explicit_delegation_state["delegation_policy"]["explicit_user_delegation_request"] = True
    explicit_delegation_state["delegation_policy"]["requested_source"] = "explicit"
    explicit_delegation_state["dispatch_decisions"] = [
        {
            "task_id": "task_0",
            "decision": "local_fallback",
            "reason": "spawn_agent tool policy requires explicit user delegation intent",
            "failed_prerequisites": ["spawn_policy_requires_explicit_user_request"],
        }
    ]
    explicit_followups = debt.stable_followups(explicit_delegation_state)
    checks["explicit_delegation_all_policy_fallback_reports_debt"] = (
        "delegation_policy_prevented_all_delegation" in explicit_followups
    )
    if not checks["explicit_delegation_all_policy_fallback_reports_debt"]:
        failures.append("explicit delegation request with all-policy fallback should report prevented delegation debt")

    missing_dispatch_state = v222_state()
    missing_dispatch_state["dispatch_decisions"] = []
    missing_dispatch_followups = debt.stable_followups(missing_dispatch_state)
    checks["write_capable_task_without_dispatch_reports_missing_evidence"] = (
        "delegation_policy_missing_dispatch_evidence" in missing_dispatch_followups
    )
    if not checks["write_capable_task_without_dispatch_reports_missing_evidence"]:
        failures.append("write-capable finished tasks without dispatch evidence should report missing evidence")

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

    plan_audit_quality = v222_state()
    plan_audit_quality["plan_executability_audit"] = {
        "path": f"{check_state_schema.run_dir()}/plan_executability_audit.json",
        "grade": "yellow",
        "blocking_issue_count": 0,
        "fixable_issue_count": 1,
    }
    plan_audit_quality["run_quality"]["grade"] = "yellow"
    plan_audit_quality["run_quality"]["open_followups"] = ["plan_executability_fixable_issues"]
    plan_audit_quality["run_quality"]["readiness"]["plan_executability_fixable_issue_count"] = 1
    plan_audit_quality["run_quality"]["operational_debt"] = {
        "schema_version": "1",
        "followups": list(plan_audit_quality["run_quality"]["open_followups"]),
        "count": 1,
        "blocking": False,
    }
    valid_plan_audit_quality = run_validator(plan_audit_quality)
    checks["plan_executability_fixable_yellow_quality"] = (
        valid_plan_audit_quality.returncode == 0
        and debt.stable_followups(plan_audit_quality) == ["plan_executability_fixable_issues"]
    )
    if not checks["plan_executability_fixable_yellow_quality"]:
        failures.append(
            "plan_executability_audit fixable issues should allow yellow run quality: "
            + valid_plan_audit_quality.stderr
        )

    missing_followup = v222_state()
    missing_followup["agentlens_orchestration_run"] = None
    missing_followup["run_quality"]["context_quality"]["full_spec_fallback_count"] = 1
    missing_followup["run_quality"]["open_followups"] = []
    invalid_missing_followup = run_validator(missing_followup)
    checks["invalid_missing_required_followup_fails"] = (
        invalid_missing_followup.returncode != 0
        and "run_quality.open_followups missing required followup: agentlens_missing" in invalid_missing_followup.stderr
        and "run_quality.open_followups missing required followup: full_spec_fallback_present"
        in invalid_missing_followup.stderr
    )
    if not checks["invalid_missing_required_followup_fails"]:
        failures.append("validator should reject finished quality missing required open_followups")

    green_with_followup = v222_state()
    green_with_followup["agentlens_orchestration_run"] = None
    green_with_followup["run_quality"]["open_followups"] = ["agentlens_missing"]
    invalid_green = run_validator(green_with_followup)
    checks["green_with_open_followups_fails"] = (
        invalid_green.returncode != 0
        and "run_quality.grade must be yellow or red when open_followups is non-empty" in invalid_green.stderr
    )
    if not checks["green_with_open_followups_fails"]:
        failures.append("validator should reject green run_quality with open followups")

    static_result, static_state = run_static_fixture()
    checks["static_runner_emits_v222_fields"] = (
        static_result.returncode == 0
        and static_state.get("execution_worktree") == static_state.get("worktree")
        and isinstance(static_state.get("delegation_policy"), dict)
        and isinstance(static_state.get("preflight_bootstrap"), dict)
        and isinstance(static_state.get("run_quality"), dict)
    )
    if not checks["static_runner_emits_v222_fields"]:
        failures.append("static_execution_runner should emit v2.22 operational quality fields")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
