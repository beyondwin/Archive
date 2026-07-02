#!/usr/bin/env python3
"""Static checks for eval harness failure and isolation behavior."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    run_sh = (skill_dir / "evals" / "run.sh").read_text(encoding="utf-8")
    check_execution = (skill_dir / "evals" / "check_execution.py").read_text(encoding="utf-8")
    baseline_utils = (skill_dir / "evals" / "baseline_utils.py").read_text(encoding="utf-8")
    checks: dict[str, bool] = {}
    failures: list[str] = []

    checks["aggregates_fixture_failures"] = "overall_status=0" in run_sh and "overall_status=1" in run_sh
    if not checks["aggregates_fixture_failures"]:
        failures.append("run.sh should aggregate fixture failures into a non-zero final status")

    checks["exits_with_aggregate_status"] = 'exit "$overall_status"' in run_sh
    if not checks["exits_with_aggregate_status"]:
        failures.append("run.sh should exit with the aggregate fixture status")

    checks["isolates_state_home"] = "CODEX_EVAL_HOME" in run_sh and "Path.home()" not in run_sh
    if not checks["isolates_state_home"]:
        failures.append("run.sh should use an eval-specific home for state fixtures, not the real home")

    checks["execution_checker_uses_eval_home"] = "CODEX_EVAL_HOME" in check_execution and "Path.home()" not in check_execution
    if not checks["execution_checker_uses_eval_home"]:
        failures.append("check_execution.py should locate state under CODEX_EVAL_HOME when present")

    checks["maps_headless_sandbox"] = "headless_sandbox" in run_sh and "HEADLESS_SANDBOX" in run_sh
    if not checks["maps_headless_sandbox"]:
        failures.append("run.sh should map headless_sandbox to HEADLESS_SANDBOX for the target process")

    checks["prompt_export_fast_path"] = "For mode=prompt or mode=handoff, do not load implementation-only skills" in run_sh
    if not checks["prompt_export_fast_path"]:
        failures.append("run.sh should keep prompt/handoff evals on an export-only fast path")

    checks["static_execution_runner"] = "static_execution_runner.py" in run_sh and 'mode" != "prompt"' in run_sh
    if not checks["static_execution_runner"]:
        failures.append("run.sh should use the deterministic static runner for execution fixtures")

    checks["static_prompt_runner"] = "static_prompt_runner.py" in run_sh
    if not checks["static_prompt_runner"]:
        failures.append("run.sh should use the deterministic static runner for prompt fixtures")

    checks["supports_update_baseline_option"] = "--update-baseline" in run_sh and "update_baseline=0" in run_sh
    if not checks["supports_update_baseline_option"]:
        failures.append("run.sh should support an explicit --update-baseline option")

    checks["cli_fixture_args_not_reassigned"] = "fixture_args=\"$(" not in run_sh
    if not checks["cli_fixture_args_not_reassigned"]:
        failures.append("run.sh should not reuse fixture_args for per-fixture YAML args after CLI parsing")

    checks["focused_run_flag_captures_cli_scope"] = "focused_run=0" in run_sh and 'focused_run=1' in run_sh
    if not checks["focused_run_flag_captures_cli_scope"]:
        failures.append("run.sh should preserve focused_run state immediately after CLI parsing")

    checks["default_compares_baseline"] = "compare_baseline" in run_sh and "baseline mismatch:" in baseline_utils
    if not checks["default_compares_baseline"]:
        failures.append("run.sh should compare generated results against the tracked baseline by default")

    checks["default_does_not_write_baseline_directly"] = (
        "generated_baseline=" in run_sh
        and '>"$BASELINE_FILE"' not in run_sh
        and '> "$BASELINE_FILE"' not in run_sh
    )
    if not checks["default_does_not_write_baseline_directly"]:
        failures.append("run.sh default path should not write directly to the tracked baseline file")

    checks["mismatch_guides_update_command"] = "./evals/run.sh --update-baseline" in run_sh
    if not checks["mismatch_guides_update_command"]:
        failures.append("baseline mismatch output should tell operators to run ./evals/run.sh --update-baseline")

    checks["subset_update_preserves_unexecuted_fixtures"] = (
        "merge_subset_baseline" in baseline_utils
        and "existing_by_fixture" in baseline_utils
        and "generated_by_fixture" in baseline_utils
    )
    if not checks["subset_update_preserves_unexecuted_fixtures"]:
        failures.append("fixture subset baseline updates should preserve unexecuted fixture entries")

    checks["full_compare_requires_exact_fixture_list"] = (
        'choices=["full", "subset"]' in baseline_utils
        and 'if mode == "full":' in baseline_utils
        and "expected_names != actual_names" in baseline_utils
    )
    if not checks["full_compare_requires_exact_fixture_list"]:
        failures.append("default full runs should require an exact fixture list match before payload comparison")

    checks["subset_compare_only_checks_executed_fixture_subset"] = (
        'compare_mode="subset"' in run_sh
        and "subset_expected.append" in baseline_utils
    )
    if not checks["subset_compare_only_checks_executed_fixture_subset"]:
        failures.append("focused subset runs should compare only the executed fixture subset")

    checks["compare_update_branches_use_focused_run"] = (
        'if [ "$focused_run" -eq 0 ]' in run_sh
        and 'if [ "$focused_run" -ne 0 ]' in run_sh
    )
    if not checks["compare_update_branches_use_focused_run"]:
        failures.append("run.sh compare/update branching should use focused_run instead of mutable fixture_args length")

    checks["subset_update_rejects_unknown_fixtures"] = (
        "refusing subset baseline update for unknown fixture:" in baseline_utils
        and "return 1" in baseline_utils
        and "fixture not in existing_by_fixture" in baseline_utils
    )
    if not checks["subset_update_rejects_unknown_fixtures"]:
        failures.append("focused subset baseline updates should fail when generated fixtures are absent from the tracked baseline")

    checks["baseline_utils_has_direct_eval"] = (
        "check_baseline_utils.py" in run_sh
        and (skill_dir / "evals" / "check_baseline_utils.py").is_file()
    )
    if not checks["baseline_utils_has_direct_eval"]:
        failures.append("run.sh should execute direct baseline helper eval coverage")

    checks["release_contract_eval_in_harness"] = (
        "check_release_contract.py" in run_sh
        and (skill_dir / "evals" / "check_release_contract.py").is_file()
    )
    if not checks["release_contract_eval_in_harness"]:
        failures.append("run.sh should execute release contract eval coverage")

    checks["cpe_replay_eval_in_harness"] = (
        "check_cpe_replay.py" in run_sh
        and (skill_dir / "evals" / "check_cpe_replay.py").is_file()
        and (skill_dir / "scripts" / "normalize_cpe_run.py").is_file()
    )
    if not checks["cpe_replay_eval_in_harness"]:
        failures.append("run.sh should execute normalized CPE replay eval coverage")

    checks["update_refuses_failed_fixture_results"] = (
        "refusing to update baseline because eval checks failed" in run_sh
        and 'if [ "$overall_status" -ne 0 ]' in run_sh
    )
    if not checks["update_refuses_failed_fixture_results"]:
        failures.append("--update-baseline should not write baseline output when fixture checks failed")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
