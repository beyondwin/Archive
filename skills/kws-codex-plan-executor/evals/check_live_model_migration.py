#!/usr/bin/env python3
"""Deterministic contract checks for the cost-gated live migration harness."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


EXPECTED_TREATMENTS = [
    ("gpt55_current", "gpt-5.5", "high", "current-v2-prompt.txt"),
    ("sol_current", "gpt-5.6-sol", "high", "current-v2-prompt.txt"),
    ("sol_v3", "gpt-5.6-sol", "high", "../../templates/fresh-session-prompt.txt"),
    ("terra_scout", "gpt-5.6-terra", "high", "terra-scout-generated"),
]
EXPECTED_CASES = [
    "single-file implementation",
    "cross-package implementation",
    "root-cause repair",
    "defect review",
    "failed-test interpretation",
    "security/migration block",
    "resume/state repair",
    "large read-only exploration",
]


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("live_model_migration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result_records(*, sol_v3_tokens: int = 700) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    token_counts = {
        "gpt55_current": 1000,
        "sol_current": 950,
        "sol_v3": sol_v3_tokens,
        "terra_scout": 250,
    }
    for treatment_id, *_ in EXPECTED_TREATMENTS:
        for case_id in EXPECTED_CASES:
            terra_policy_failure = treatment_id == "terra_scout" and case_id != EXPECTED_CASES[-1]
            records.append(
                {
                    "treatment_id": treatment_id,
                    "case_id": case_id,
                    "task_completed": not terra_policy_failure,
                    "first_pass_success": not terra_policy_failure,
                    "review_accurate": not terra_policy_failure,
                    "evidence_complete": True,
                    "repairs": 0,
                    "critical_regression": False,
                    "context_tokens": token_counts[treatment_id],
                    "cache_tokens": 100,
                    "latency_ms": 1000,
                    "cost_usd": 0.10,
                    "model_attested": True,
                    "worktree_isolated": True,
                    "drift_free": True,
                    "expected_policy_failure": terra_policy_failure,
                }
            )
    return records


def run_harness(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    eval_dir = Path(__file__).resolve().parent
    script = eval_dir / "live_model_migration.py"
    migration_dir = eval_dir / "live-migration"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    matrix = json.loads((migration_dir / "matrix.json").read_text(encoding="utf-8"))
    cases_payload = json.loads((migration_dir / "cases.json").read_text(encoding="utf-8"))
    actual_treatments = [
        (item.get("id"), item.get("model"), item.get("reasoning"), item.get("prompt"))
        for item in matrix.get("treatments", [])
    ]
    checks["exact_four_treatments"] = (
        matrix.get("schema_version") == "1" and actual_treatments == EXPECTED_TREATMENTS
    )
    checks["exact_eight_cases"] = cases_payload.get("cases") == EXPECTED_CASES

    with tempfile.TemporaryDirectory(prefix="cpe-v3-live-check-") as raw:
        temp = Path(raw)
        dry_output = temp / "dry.json"
        dry = run_harness(
            script,
            "--dry-run",
            "--budget-usd",
            "50",
            "--output",
            str(dry_output),
        )
        dry_payload = json.loads(dry_output.read_text(encoding="utf-8")) if dry_output.is_file() else {}
        checks["dry_run_loads_matrix_without_model_calls"] = (
            dry.returncode == 0
            and dry_payload.get("treatment_count") == 4
            and dry_payload.get("case_count") == 8
            and len(dry_payload.get("execution_plan", [])) == 32
            and dry_payload.get("estimated_max_cost_usd", 51) <= 50
            and dry_payload.get("release_gate", {}).get("status") == "paid_pending"
            and dry_payload.get("release_gate", {}).get("passed") is False
        )

        over_cap = run_harness(
            script,
            "--dry-run",
            "--budget-usd",
            "50.01",
            "--output",
            str(temp / "over-cap.json"),
        )
        checks["hard_cap_above_fifty_is_refused"] = (
            over_cap.returncode != 0 and "$50.00" in over_cap.stderr
        )

        under_budget = run_harness(
            script,
            "--dry-run",
            "--budget-usd",
            "47",
            "--output",
            str(temp / "under-budget.json"),
        )
        checks["estimated_cost_above_budget_is_refused"] = (
            under_budget.returncode != 0 and "estimated" in under_budget.stderr.lower()
        )

        unconfirmed = run_harness(
            script,
            "--budget-usd",
            "50",
            "--output",
            str(temp / "unconfirmed.json"),
        )
        checks["non_dry_requires_explicit_cost_confirmation"] = (
            unconfirmed.returncode != 0 and "--confirm-live-cost" in unconfirmed.stderr
        )

        passing_results = temp / "passing-results.json"
        passing_results.write_text(
            json.dumps({"results": result_records()}, indent=2) + "\n",
            encoding="utf-8",
        )
        passing_output = temp / "passing-report.json"
        passing = run_harness(
            script,
            "--confirm-live-cost",
            "--budget-usd",
            "50",
            "--results-json",
            str(passing_results),
            "--output",
            str(passing_output),
        )
        passing_payload = (
            json.loads(passing_output.read_text(encoding="utf-8"))
            if passing_output.is_file()
            else {}
        )
        sol_metrics = passing_payload.get("metrics", {}).get("sol_v3", {})
        checks["deterministic_results_are_injectable"] = (
            passing.returncode == 0
            and passing_payload.get("evidence_source") == "injected_results"
            and passing_payload.get("release_gate", {}).get("passed") is True
        )
        checks["quality_metrics_cover_release_invariants"] = (
            sol_metrics.get("model_attestation_rate") == 1.0
            and sol_metrics.get("worktree_isolation_rate") == 1.0
            and sol_metrics.get("drift_free_rate") == 1.0
            and sol_metrics.get("context_token_reduction_vs_gpt55") == 0.3
            and sol_metrics.get("task_completion_rate") == 1.0
        )

        failing_results = temp / "failing-results.json"
        failing_results.write_text(
            json.dumps({"results": result_records(sol_v3_tokens=800)}, indent=2) + "\n",
            encoding="utf-8",
        )
        failing_output = temp / "failing-report.json"
        failing = run_harness(
            script,
            "--confirm-live-cost",
            "--budget-usd",
            "50",
            "--results-json",
            str(failing_results),
            "--output",
            str(failing_output),
        )
        failing_payload = (
            json.loads(failing_output.read_text(encoding="utf-8"))
            if failing_output.is_file()
            else {}
        )
        checks["failed_release_gate_exits_nonzero"] = (
            failing.returncode != 0
            and failing_payload.get("release_gate", {}).get("passed") is False
            and "context_token_reduction_below_25_percent"
            in failing_payload.get("release_gate", {}).get("failures", [])
        )

        no_results = run_harness(
            script,
            "--confirm-live-cost",
            "--budget-usd",
            "50",
            "--output",
            str(temp / "no-results.json"),
        )
        checks["paid_provider_launch_is_not_implicit"] = (
            no_results.returncode != 0 and "--results-json" in no_results.stderr
        )

    try:
        module = load_module(script)
        aggregate = getattr(module, "aggregate_results")
        aggregation = aggregate(matrix, cases_payload, result_records())
        checks["aggregation_api_is_pure_and_injectable"] = (
            aggregation.get("release_gate", {}).get("passed") is True
        )

        altered_matrix = json.loads(json.dumps(matrix))
        altered_matrix["treatments"][2]["model"] = "gpt-5.5"
        try:
            aggregate(altered_matrix, cases_payload, result_records())
        except ValueError:
            checks["aggregator_rejects_altered_treatment_contract"] = True
        else:
            checks["aggregator_rejects_altered_treatment_contract"] = False

        altered_results = result_records()
        altered_results[0]["expected_policy_failure"] = True
        try:
            aggregate(matrix, cases_payload, altered_results)
        except ValueError:
            checks["aggregator_derives_policy_failures_from_plan"] = True
        else:
            checks["aggregator_derives_policy_failures_from_plan"] = False
    except Exception as exc:  # noqa: BLE001 - report contract failure, not traceback
        checks["aggregation_api_is_pure_and_injectable"] = False
        failures.append(f"aggregation API unavailable: {exc}")

    for name, passed in checks.items():
        if not passed:
            failures.append(name)

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
