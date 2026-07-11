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

from live_migration.compiler import compile_manifest
from live_migration.contracts import SlotKey, canonical_json, sha256_bytes
from live_migration.ledger import append_event, commit_slot, create_run


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
EXPECTED_THRESHOLDS = {
    "critical_regressions": 0,
    "task_success_regression_allowed": False,
    "core_model_attestation_rate": 1.0,
    "worktree_isolation_rate": 1.0,
    "drift_free_rate": 1.0,
    "minimum_context_token_reduction": 0.25,
}
TEST_MODEL_CATALOG_SHA256 = "d" * 64


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("live_model_migration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result_records(
    manifest: dict[str, Any], *, sol_v3_tokens: int = 700
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    token_counts = {
        "gpt55_current": 1000,
        "sol_current": 950,
        "sol_v3": sol_v3_tokens,
        "terra_scout": 250,
    }
    for position, slot in enumerate(manifest["slots"]):
        treatment_id = slot["treatment_id"]
        case_id = slot["case_id"]
        terra_policy_failure = slot["expected_policy_failure"]
        record = {
                "schema_version": "cpe-live-result.v2",
                "run_id": manifest["run_id"],
                "treatment_id": treatment_id,
                "case_id": case_id,
                "outcome_kind": (
                    "expected_policy_failure"
                    if terra_policy_failure
                    else "credentialed_call"
                ),
                "task_completed": not terra_policy_failure,
                "first_pass_success": not terra_policy_failure,
                "review_accurate": not terra_policy_failure,
                "evidence_complete": True,
                "repairs": 0,
                "critical_regression": False,
                "billing_mode": "chatgpt_subscription",
                "model_attested": True,
                "worktree_isolated": True,
                "drift_free": True,
                "expected_policy_failure": terra_policy_failure,
                "evidence_sha256": f"{position + 1:064x}",
        }
        if terra_policy_failure:
            record["matrix_policy_sha256"] = slot["matrix_policy_sha256"]
            record["manifest_sha256"] = manifest["manifest_sha256"]
        else:
            record.update(
                {
                    "context_tokens": token_counts[treatment_id],
                    "cache_tokens": 100,
                    "output_tokens": 50,
                    "latency_ms": 1000,
                    "cost_usd": None,
                }
            )
        records.append(record)
    return records


def metered_result_records(*, sol_v3_tokens: int = 700) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    token_counts = {
        "gpt55_current": 1000,
        "sol_current": 950,
        "sol_v3": sol_v3_tokens,
        "terra_scout": 250,
    }
    for treatment_id, *_ in EXPECTED_TREATMENTS:
        for case_id in EXPECTED_CASES:
            terra_policy_failure = (
                treatment_id == "terra_scout" and case_id != EXPECTED_CASES[-1]
            )
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


def build_ledger_run(
    root: Path,
    *,
    sol_v3_tokens: int = 700,
    bind_model_catalog: bool = True,
) -> Path:
    manifest = compile_manifest(
        Path(__file__).resolve().parent,
        "chatgpt_subscription",
        "a" * 40,
        "2026-07-11T00:00:00Z",
        "cpe-v3-live-ledger-test",
    )
    if bind_model_catalog:
        manifest["model_catalog_sha256"] = TEST_MODEL_CATALOG_SHA256
        manifest_body = {
            key: value for key, value in manifest.items() if key != "manifest_sha256"
        }
        manifest["manifest_sha256"] = sha256_bytes(canonical_json(manifest_body))
    run_dir = root / "run"
    run = create_run(run_dir, manifest)
    for result in result_records(manifest, sol_v3_tokens=sol_v3_tokens):
        key = SlotKey(result["treatment_id"], result["case_id"])
        commit_slot(
            run,
            key,
            {
                "evidence.json": canonical_json(
                    {"treatment_id": key.treatment_id, "case_id": key.case_id}
                )
            },
            result,
        )
    append_event(run, "run_completed", {"completed_slots": 32})
    return run_dir


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
            "--output",
            str(dry_output),
        )
        dry_payload = json.loads(dry_output.read_text(encoding="utf-8")) if dry_output.is_file() else {}
        checks["dry_run_loads_matrix_without_model_calls"] = (
            dry.returncode == 0
            and dry_payload.get("treatment_count") == 4
            and dry_payload.get("case_count") == 8
            and len(dry_payload.get("execution_plan", [])) == 32
            and dry_payload.get("release_gate", {}).get("status") == "paid_pending"
            and dry_payload.get("release_gate", {}).get("passed") is False
            and dry_payload.get("billing_mode") == "chatgpt_subscription"
            and dry_payload.get("cost_usd") is None
        )

        over_cap = run_harness(
            script,
            "--dry-run",
            "--billing-mode",
            "metered_dollar",
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
            "--billing-mode",
            "metered_dollar",
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
            "--billing-mode",
            "metered_dollar",
            "--budget-usd",
            "50",
            "--output",
            str(temp / "unconfirmed.json"),
        )
        checks["non_dry_requires_explicit_cost_confirmation"] = (
            unconfirmed.returncode != 0 and "--confirm-live-cost" in unconfirmed.stderr
        )

        metered_results = temp / "metered-results.json"
        metered_results.write_text(
            json.dumps({"results": metered_result_records()}, indent=2) + "\n",
            encoding="utf-8",
        )
        metered_output = temp / "metered-report.json"
        metered = run_harness(
            script,
            "--billing-mode",
            "metered_dollar",
            "--confirm-live-cost",
            "--budget-usd",
            "50",
            "--results-json",
            str(metered_results),
            "--output",
            str(metered_output),
        )
        metered_payload = (
            json.loads(metered_output.read_text(encoding="utf-8"))
            if metered_output.is_file()
            else {}
        )
        checks["metered_injected_results_are_aggregated"] = (
            metered.returncode == 0
            and metered_payload.get("billing_mode") == "metered_dollar"
            and metered_payload.get("evidence_source") == "metered_injected_results"
            and metered_payload.get("metrics", {}).get("sol_v3", {}).get("cost_usd")
            == 0.8
            and metered_payload.get("release_gate", {}).get("passed") is True
        )

        passing_run = build_ledger_run(temp / "passing")
        passing_output = temp / "passing-report.json"
        passing = run_harness(
            script,
            "--confirm-subscription-usage",
            "--run-dir",
            str(passing_run),
            "--output",
            str(passing_output),
        )
        passing_payload = (
            json.loads(passing_output.read_text(encoding="utf-8"))
            if passing_output.is_file()
            else {}
        )
        sol_metrics = passing_payload.get("metrics", {}).get("sol_v3", {})
        checks["ledger_results_are_aggregated"] = (
            passing.returncode == 0
            and passing_payload.get("evidence_source") == "validated_live_run_ledger"
            and passing_payload.get("release_gate", {}).get("passed") is True
            and passing_payload.get("credentialed_call_count") == 25
            and passing_payload.get("expected_policy_failure_count") == 7
            and passing_payload.get("billing_mode") == "chatgpt_subscription"
            and passing_payload.get("cost_usd") is None
            and passing_payload.get("cost_observability") == "unavailable"
            and "cannot prove" in passing_payload.get("billing_boundary", "").lower()
        )
        checks["quality_metrics_cover_release_invariants"] = (
            sol_metrics.get("model_attestation_rate") == 1.0
            and sol_metrics.get("worktree_isolation_rate") == 1.0
            and sol_metrics.get("drift_free_rate") == 1.0
            and sol_metrics.get("context_token_reduction_vs_gpt55") == 0.3
            and sol_metrics.get("task_completion_rate") == 1.0
            and sol_metrics.get("output_tokens") == 400
            and sol_metrics.get("cost_usd") is None
            and passing_payload.get("release_gate", {}).get("thresholds")
            == EXPECTED_THRESHOLDS
        )

        failing_run = build_ledger_run(temp / "failing", sol_v3_tokens=800)
        failing_output = temp / "failing-report.json"
        failing = run_harness(
            script,
            "--confirm-subscription-usage",
            "--run-dir",
            str(failing_run),
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
            "--output",
            str(temp / "no-results.json"),
        )
        checks["paid_provider_launch_is_not_implicit"] = (
            no_results.returncode != 0 and "--run-dir" in no_results.stderr
        )

        subscription_with_budget = run_harness(
            script,
            "--dry-run",
            "--budget-usd",
            "50",
            "--output",
            str(temp / "subscription-budget.json"),
        )
        checks["subscription_mode_rejects_dollar_budget"] = (
            subscription_with_budget.returncode != 0
            and "subscription" in subscription_with_budget.stderr.lower()
        )

    try:
        module = load_module(script)
        aggregate_run = getattr(module, "aggregate_run")
        with tempfile.TemporaryDirectory(prefix="cpe-v3-live-api-") as raw:
            api_temp = Path(raw)
            api_run = build_ledger_run(api_temp / "passing")
            aggregation = aggregate_run(api_run)
            checks["aggregation_api_is_ledger_bound"] = (
                aggregation.get("release_gate", {}).get("passed") is True
                and aggregation.get("credentialed_call_count") == 25
                and aggregation.get("expected_policy_failure_count") == 7
                and len(aggregation.get("result_sha256", {})) == 32
                and aggregation.get("model_catalog_sha256")
                == TEST_MODEL_CATALOG_SHA256
            )

            missing_catalog_run = build_ledger_run(
                api_temp / "missing-catalog", bind_model_catalog=False
            )
            try:
                aggregate_run(missing_catalog_run)
            except ValueError:
                checks["aggregator_rejects_missing_model_catalog_binding"] = True
            else:
                checks["aggregator_rejects_missing_model_catalog_binding"] = False

            tampered_catalog_run = build_ledger_run(api_temp / "tampered-catalog")
            tampered_manifest = tampered_catalog_run / "manifest.json"
            tampered_payload = json.loads(
                tampered_manifest.read_text(encoding="utf-8")
            )
            tampered_payload["model_catalog_sha256"] = "e" * 64
            tampered_manifest.write_text(
                json.dumps(tampered_payload) + "\n", encoding="utf-8"
            )
            try:
                aggregate_run(tampered_catalog_run)
            except ValueError:
                checks["aggregator_rejects_tampered_model_catalog_binding"] = True
            else:
                checks["aggregator_rejects_tampered_model_catalog_binding"] = False

            mixed_run = build_ledger_run(api_temp / "mixed")
            mixed_result = (
                mixed_run
                / "slots"
                / "gpt55_current"
                / "single-file%20implementation"
                / "result.json"
            )
            mixed_payload = json.loads(mixed_result.read_text(encoding="utf-8"))
            mixed_payload["run_id"] = "another-run"
            mixed_result.write_text(json.dumps(mixed_payload) + "\n", encoding="utf-8")
            try:
                aggregate_run(mixed_run)
            except ValueError:
                checks["aggregator_rejects_mixed_run_evidence"] = True
            else:
                checks["aggregator_rejects_mixed_run_evidence"] = False

            synthetic = api_temp / "synthetic-results.json"
            synthetic.write_text(json.dumps({"results": []}), encoding="utf-8")
            synthetic_call = run_harness(
                script,
                "--confirm-subscription-usage",
                "--results-json",
                str(synthetic),
                "--output",
                str(api_temp / "synthetic-report.json"),
            )
            checks["aggregator_rejects_synthetic_subscription_evidence"] = (
                synthetic_call.returncode != 0
                and "--run-dir" in synthetic_call.stderr
            )
    except Exception as exc:  # noqa: BLE001 - report contract failure, not traceback
        checks["aggregation_api_is_ledger_bound"] = False
        failures.append(f"aggregation API unavailable: {exc}")

    for name, passed in checks.items():
        if not passed:
            failures.append(name)

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
