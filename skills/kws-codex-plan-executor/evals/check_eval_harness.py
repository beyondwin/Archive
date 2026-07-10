#!/usr/bin/env python3
"""Static checks for eval harness failure and isolation behavior."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    run_sh = (skill_dir / "evals" / "run.sh").read_text(encoding="utf-8")
    check_execution = (skill_dir / "evals" / "check_execution.py").read_text(encoding="utf-8")
    baseline_utils = (skill_dir / "evals" / "baseline_utils.py").read_text(encoding="utf-8")
    checks: dict[str, bool] = {}
    failures: list[str] = []

    preflight_position = run_sh.find("preflight_dependencies.py")
    fixture_yaml_position = run_sh.find("import json, os, sys, yaml")
    checks["dependency_preflight_precedes_fixture_yaml"] = (
        preflight_position >= 0
        and fixture_yaml_position >= 0
        and preflight_position < fixture_yaml_position
    )
    if not checks["dependency_preflight_precedes_fixture_yaml"]:
        failures.append("run.sh should check eval dependencies before reading fixture YAML")

    checks["uses_structured_check_runner"] = "run_check.py" in run_sh
    if not checks["uses_structured_check_runner"]:
        failures.append("run.sh should execute deterministic checks through run_check.py")

    fixture_checker_lines = [
        line
        for line in run_sh.splitlines()
        if "check_prompt.py" in line or "check_execution.py" in line
    ]
    checks["fixture_checkers_use_structured_runner"] = (
        len(fixture_checker_lines) == 2
        and all("run_check " in line for line in fixture_checker_lines)
    )
    if not checks["fixture_checkers_use_structured_runner"]:
        failures.append("run.sh should execute prompt and execution fixture checkers through run_check.py")

    checks["truncates_eval_report_once"] = (
        run_sh.count(': > "$EVAL_REPORT"') == 1
    )
    if not checks["truncates_eval_report_once"]:
        failures.append("run.sh should truncate eval-report.jsonl exactly once")

    checks["eval_report_is_outside_tracked_tree"] = (
        'EVAL_REPORT="$EVAL_DIR/eval-report.jsonl"' not in run_sh
        and "$CODEX_EVAL_HOME/.codex/eval-reports" in run_sh
        and 'REPORT_ROOT="${TMPDIR:-/tmp}"' in run_sh
        and 'mktemp -d "$REPORT_ROOT/' in run_sh
        and 'echo "eval report: $EVAL_REPORT"' in run_sh
    )
    if not checks["eval_report_is_outside_tracked_tree"]:
        failures.append("run.sh should write and announce eval reports outside the tracked skill tree")

    allocation_probe = r"""
set -euo pipefail
umask 077
REPORT_ROOT="$1"
REPORT_DIR="$(mktemp -d "$REPORT_ROOT/kws-codex-plan-executor-eval.XXXXXX")"
chmod 700 "$REPORT_DIR"
EVAL_REPORT="$REPORT_DIR/eval-report.jsonl"
: > "$EVAL_REPORT"
printf '%s\n' "$EVAL_REPORT"
"""
    allocated_paths: list[Path] = []
    allocated_modes: list[int] = []
    allocated_files_exist: list[bool] = []
    allocation_results: list[subprocess.CompletedProcess[str]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        expected_root = Path(temp_dir)
        for _ in range(2):
            result = subprocess.run(
                ["bash", "-c", allocation_probe, "allocation-probe", temp_dir],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            allocation_results.append(result)
            report_lines = result.stdout.splitlines()
            if len(report_lines) == 1:
                report_path = Path(report_lines[0])
                allocated_paths.append(report_path)
                allocated_modes.append(report_path.parent.stat().st_mode & 0o777)
                allocated_files_exist.append(report_path.is_file())
        allocations_use_expected_root = all(
            path.parent.parent == expected_root for path in allocated_paths
        )
    checks["eval_report_allocation_is_private_and_unique"] = (
        len(allocation_results) == 2
        and all(result.returncode == 0 for result in allocation_results)
        and len(allocated_paths) == 2
        and allocated_paths[0] != allocated_paths[1]
        and allocated_modes == [0o700, 0o700]
        and allocated_files_exist == [True, True]
        and allocations_use_expected_root
    )
    if not checks["eval_report_allocation_is_private_and_unique"]:
        failures.append("run.sh should allocate a unique private report directory for each run")

    preflight_calls = re.findall(r'^\s*run_check\s+"([^"]+)"', run_sh, flags=re.MULTILINE)
    preflight_call_position = run_sh.find('run_check "preflight_dependencies"')
    checks["environment_cannot_bypass_preflight"] = (
        "CPE_EVAL_REPORT_ALLOCATE_ONLY" not in run_sh
        and preflight_call_position >= 0
        and not re.search(r"(?m)^\s*exit(?:\s|$)", run_sh[:preflight_call_position])
        and preflight_calls[:1] == ["preflight_dependencies"]
    )
    if not checks["environment_cannot_bypass_preflight"]:
        failures.append("run.sh should not allow environment-controlled success before preflight")

    with tempfile.TemporaryDirectory() as temp_dir:
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_EVAL_HOME": temp_dir,
                "CPE_INNOCUOUS_ENV": "1",
                "PATH": f"{Path(sys.executable).parent}{os.pathsep}{environment['PATH']}",
            }
        )
        result = subprocess.run(
            ["bash", str(skill_dir / "evals" / "run.sh"), "__missing_fixture_for_preflight_probe__"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        report_lines = [
            line.removeprefix("eval report: ")
            for line in result.stdout.splitlines()
            if line.startswith("eval report: ")
        ]
        report_rows = (
            [
                json.loads(line)
                for line in Path(report_lines[0]).read_text(encoding="utf-8").splitlines()
            ]
            if len(report_lines) == 1 and Path(report_lines[0]).is_file()
            else []
        )
    checks["innocuous_environment_still_runs_preflight"] = (
        result.returncode == 1
        and len(report_rows) == 1
        and report_rows[0]["name"] == "preflight_dependencies"
        and report_rows[0]["status"] == "passed"
    )
    if not checks["innocuous_environment_still_runs_preflight"]:
        failures.append("run.sh should record preflight before rejecting an unrelated fixture argument")

    checks["checker_output_is_not_discarded"] = not re.search(
        r"check_[^\n]*\.py[^\n]*>/dev/null",
        run_sh,
    )
    if not checks["checker_output_is_not_discarded"]:
        failures.append("run.sh should not redirect checker output to /dev/null")

    failure_marker = "first failing command output is visible"
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "report.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                str(skill_dir / "evals" / "run_check.py"),
                "--report",
                str(report_path),
                "--name",
                "expected-failure",
                "--",
                sys.executable,
                "-c",
                f"import sys; print({failure_marker!r}); raise SystemExit(7)",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        report_rows = [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]
    checks["first_failure_output_is_visible"] = (
        result.returncode == 7
        and failure_marker in result.stdout
        and len(report_rows) == 1
        and report_rows[0]["status"] == "failed"
        and failure_marker in report_rows[0]["failure_output"]
    )
    if not checks["first_failure_output_is_visible"]:
        failures.append("run_check.py should report and display the first failing command output")

    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "launch-failure.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                str(skill_dir / "evals" / "run_check.py"),
                "--report",
                str(report_path),
                "--name",
                "missing-executable",
                "--",
                str(Path(temp_dir) / "does-not-exist"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        report_rows = (
            [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]
            if report_path.is_file()
            else []
        )
    checks["launch_failure_is_reported"] = (
        result.returncode == 127
        and len(report_rows) == 1
        and report_rows[0]["status"] == "failed"
        and report_rows[0]["returncode"] == 127
        and bool(report_rows[0]["failure_output"])
    )
    if not checks["launch_failure_is_reported"]:
        failures.append("run_check.py should append a stable failed row when command launch fails")

    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "non-utf8.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                str(skill_dir / "evals" / "run_check.py"),
                "--report",
                str(report_path),
                "--name",
                "non-utf8-output",
                "--",
                sys.executable,
                "-c",
                "import os; os.write(1, bytes([255])); raise SystemExit(9)",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        report_rows = (
            [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]
            if report_path.is_file()
            else []
        )
    checks["non_utf8_output_is_reported"] = (
        result.returncode == 9
        and len(report_rows) == 1
        and report_rows[0]["returncode"] == 9
        and "\ufffd" in report_rows[0]["failure_output"]
    )
    if not checks["non_utf8_output_is_reported"]:
        failures.append("run_check.py should replace undecodable bytes and append the failed row")

    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "stream-order.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                str(skill_dir / "evals" / "run_check.py"),
                "--report",
                str(report_path),
                "--name",
                "stream-order",
                "--",
                sys.executable,
                "-c",
                (
                    "import os; "
                    "os.write(2, b'stderr-first\\n'); "
                    "os.write(1, b'stdout-second\\n'); "
                    "raise SystemExit(8)"
                ),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        report_rows = (
            [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]
            if report_path.is_file()
            else []
        )
    ordered_output = report_rows[0]["failure_output"] if len(report_rows) == 1 else ""
    checks["combined_output_preserves_order"] = (
        result.returncode == 8
        and "stderr-first" in ordered_output
        and "stdout-second" in ordered_output
        and ordered_output.index("stderr-first") < ordered_output.index("stdout-second")
    )
    if not checks["combined_output_preserves_order"]:
        failures.append("run_check.py should preserve chronological stdout/stderr ordering")

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

    checks["release_contract_allows_new_version_baseline_update"] = (
        'if [ "$update_baseline" -eq 0 ]; then\n'
        '  run_check "release_contract" python3 "$EVAL_DIR/check_release_contract.py"\n'
        "fi" in run_sh
        and 'write_full_baseline "$generated_baseline" "$BASELINE_FILE"' in run_sh
        and 'run_check "release_contract_after_update" python3 "$EVAL_DIR/check_release_contract.py"\n'
        '  cat "$BASELINE_FILE"' in run_sh
    )
    if not checks["release_contract_allows_new_version_baseline_update"]:
        failures.append("run.sh should not block --update-baseline before a new version baseline exists")

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
