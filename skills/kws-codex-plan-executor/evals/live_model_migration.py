#!/usr/bin/env python3
"""Build and evaluate the bounded CPE v3 live-migration release matrix.

This harness deliberately has no provider-launch implementation. A dry run
emits the complete bounded plan. A non-dry run aggregates explicitly supplied
result evidence after the operator confirms the cost boundary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


MAX_BUDGET_USD = 50.00
ESTIMATED_RUN_COST_USD = 1.50
REQUIRED_TOKEN_REDUCTION = 0.25
CORE_TREATMENTS = ("gpt55_current", "sol_current", "sol_v3")
EXPECTED_TREATMENT_IDS = (*CORE_TREATMENTS, "terra_scout")
EXPECTED_TREATMENTS = (
    ("gpt55_current", "gpt-5.5", "high", "current-v2-prompt.txt"),
    ("sol_current", "gpt-5.6-sol", "high", "current-v2-prompt.txt"),
    ("sol_v3", "gpt-5.6-sol", "high", "../../templates/fresh-session-prompt.txt"),
    ("terra_scout", "gpt-5.6-terra", "high", "terra-scout-generated"),
)
EXPECTED_CASES = (
    "single-file implementation",
    "cross-package implementation",
    "root-cause repair",
    "defect review",
    "failed-test interpretation",
    "security/migration block",
    "resume/state repair",
    "large read-only exploration",
)


class MigrationContractError(ValueError):
    """Raised when deterministic migration evidence violates the contract."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationContractError(f"missing JSON input: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MigrationContractError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MigrationContractError(f"JSON input must be an object: {path}")
    return payload


def load_matrix_inputs(eval_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    migration_dir = eval_dir / "live-migration"
    matrix = load_json(migration_dir / "matrix.json")
    cases = load_json(migration_dir / "cases.json")
    validate_matrix(matrix, cases)
    return matrix, cases


def validate_matrix(matrix: dict[str, Any], cases: dict[str, Any]) -> None:
    treatments = matrix.get("treatments")
    case_names = cases.get("cases")
    if matrix.get("schema_version") != "1" or not isinstance(treatments, list):
        raise MigrationContractError("migration matrix must use schema_version=1")
    treatment_contract = tuple(
        (item.get("id"), item.get("model"), item.get("reasoning"), item.get("prompt"))
        for item in treatments
        if isinstance(item, dict)
    )
    if treatment_contract != EXPECTED_TREATMENTS or len(treatments) != 4:
        raise MigrationContractError(
            "migration matrix does not match the exact four-treatment model/prompt contract"
        )
    if tuple(case_names or ()) != EXPECTED_CASES:
        raise MigrationContractError("migration cases must contain the exact eight bounded cases")


def build_execution_plan(
    matrix: dict[str, Any], cases: dict[str, Any]
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for treatment in matrix["treatments"]:
        for case_id in cases["cases"]:
            terra_policy_failure = (
                treatment["id"] == "terra_scout" and case_id != EXPECTED_CASES[-1]
            )
            plan.append(
                {
                    "treatment_id": treatment["id"],
                    "case_id": case_id,
                    "model": treatment["model"],
                    "reasoning": treatment["reasoning"],
                    "prompt": treatment["prompt"],
                    "expected_policy_failure": terra_policy_failure,
                }
            )
    return plan


def as_bool(record: dict[str, Any], field: str) -> bool:
    value = record.get(field)
    if not isinstance(value, bool):
        raise MigrationContractError(f"result field {field!r} must be boolean")
    return value


def as_number(record: dict[str, Any], field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise MigrationContractError(f"result field {field!r} must be a non-negative number")
    return float(value)


def rate(records: list[dict[str, Any]], field: str) -> float:
    return round(sum(1 for record in records if as_bool(record, field)) / len(records), 6)


def aggregate_results(
    matrix: dict[str, Any],
    cases: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate injected result records and evaluate the fixed release gate."""

    validate_matrix(matrix, cases)
    if not isinstance(results, list):
        raise MigrationContractError("results must be a list")

    expected_keys = {
        (item["treatment_id"], item["case_id"])
        for item in build_execution_plan(matrix, cases)
    }
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for record in results:
        if not isinstance(record, dict):
            raise MigrationContractError("every result must be an object")
        key = (record.get("treatment_id"), record.get("case_id"))
        if key in indexed:
            raise MigrationContractError(f"duplicate result: {key[0]}/{key[1]}")
        indexed[key] = record
    actual_keys = set(indexed)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unexpected = sorted(actual_keys - expected_keys)
        raise MigrationContractError(
            f"results must cover the exact 4x8 matrix; missing={missing}, unexpected={unexpected}"
        )

    expected_policy = {
        (item["treatment_id"], item["case_id"]): item["expected_policy_failure"]
        for item in build_execution_plan(matrix, cases)
    }
    for key, record in indexed.items():
        if as_bool(record, "expected_policy_failure") is not expected_policy[key]:
            raise MigrationContractError(
                f"result cannot override expected policy outcome: {key[0]}/{key[1]}"
            )

    metrics: dict[str, dict[str, Any]] = {}
    for treatment_id in EXPECTED_TREATMENT_IDS:
        treatment_records = [
            indexed[(treatment_id, case_id)] for case_id in EXPECTED_CASES
        ]
        eligible_records = [
            record
            for record in treatment_records
            if not as_bool(record, "expected_policy_failure")
        ]
        if not eligible_records:
            raise MigrationContractError(f"treatment has no eligible records: {treatment_id}")
        metrics[treatment_id] = {
            "eligible_case_count": len(eligible_records),
            "task_completion_rate": rate(eligible_records, "task_completed"),
            "first_pass_success_rate": rate(eligible_records, "first_pass_success"),
            "review_accuracy_rate": rate(eligible_records, "review_accurate"),
            "evidence_completeness_rate": rate(eligible_records, "evidence_complete"),
            "repair_count": int(sum(as_number(record, "repairs") for record in eligible_records)),
            "critical_regressions": sum(
                1 for record in eligible_records if as_bool(record, "critical_regression")
            ),
            "context_tokens": int(
                sum(as_number(record, "context_tokens") for record in eligible_records)
            ),
            "cache_tokens": int(
                sum(as_number(record, "cache_tokens") for record in eligible_records)
            ),
            "latency_ms": int(
                sum(as_number(record, "latency_ms") for record in eligible_records)
            ),
            "cost_usd": round(
                sum(as_number(record, "cost_usd") for record in eligible_records), 6
            ),
            "model_attestation_rate": rate(eligible_records, "model_attested"),
            "worktree_isolation_rate": rate(eligible_records, "worktree_isolated"),
            "drift_free_rate": rate(eligible_records, "drift_free"),
        }

    baseline_tokens = metrics["gpt55_current"]["context_tokens"]
    sol_v3_tokens = metrics["sol_v3"]["context_tokens"]
    if baseline_tokens <= 0:
        raise MigrationContractError("GPT-5.5 baseline context token total must be positive")
    token_reduction = round((baseline_tokens - sol_v3_tokens) / baseline_tokens, 6)
    metrics["sol_v3"]["context_token_reduction_vs_gpt55"] = token_reduction

    failures: list[str] = []
    if metrics["sol_v3"]["critical_regressions"] != 0:
        failures.append("critical_regressions_present")
    if (
        metrics["sol_v3"]["task_completion_rate"]
        < metrics["gpt55_current"]["task_completion_rate"]
    ):
        failures.append("task_success_regressed_vs_gpt55")
    if any(metrics[item]["model_attestation_rate"] != 1.0 for item in CORE_TREATMENTS):
        failures.append("core_model_attestation_below_100_percent")
    if metrics["sol_v3"]["worktree_isolation_rate"] != 1.0:
        failures.append("worktree_isolation_violation")
    if metrics["sol_v3"]["drift_free_rate"] != 1.0:
        failures.append("drift_detected")
    if token_reduction < REQUIRED_TOKEN_REDUCTION:
        failures.append("context_token_reduction_below_25_percent")

    return {
        "metrics": metrics,
        "release_gate": {
            "status": "passed" if not failures else "failed",
            "passed": not failures,
            "failures": failures,
            "thresholds": {
                "critical_regressions": 0,
                "task_success_regression_allowed": False,
                "core_model_attestation_rate": 1.0,
                "worktree_isolation_rate": 1.0,
                "drift_free_rate": 1.0,
                "minimum_context_token_reduction": REQUIRED_TOKEN_REDUCTION,
            },
        },
    }


def write_payload(path: Path, payload: dict[str, Any]) -> None:
    if not path.parent.is_dir():
        raise MigrationContractError(f"output parent does not exist: {path.parent}")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or aggregate the bounded CPE v3 live migration matrix."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--budget-usd", type=float, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--confirm-live-cost", action="store_true")
    parser.add_argument(
        "--results-json",
        help="Pre-generated 4x8 result evidence to aggregate; this harness never launches providers.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.budget_usd <= 0:
        parser.error("--budget-usd must be positive")
    if args.budget_usd > MAX_BUDGET_USD:
        parser.error("--budget-usd exceeds the $50.00 hard cap")

    try:
        matrix, cases = load_matrix_inputs(Path(__file__).resolve().parent)
        execution_plan = build_execution_plan(matrix, cases)
        estimated_max_cost_usd = round(len(execution_plan) * ESTIMATED_RUN_COST_USD, 2)
        if estimated_max_cost_usd > args.budget_usd:
            parser.error(
                f"estimated maximum cost ${estimated_max_cost_usd:.2f} exceeds "
                f"the supplied budget ${args.budget_usd:.2f}"
            )

        common = {
            "schema_version": "1",
            "dry_run": args.dry_run,
            "budget_usd": round(args.budget_usd, 2),
            "hard_cap_usd": MAX_BUDGET_USD,
            "estimated_max_cost_usd": estimated_max_cost_usd,
            "treatment_count": len(matrix["treatments"]),
            "case_count": len(cases["cases"]),
            "execution_plan": execution_plan,
        }
        output = Path(args.output)
        if args.dry_run:
            if args.results_json:
                parser.error("--results-json cannot be used with --dry-run")
            payload = {
                **common,
                "evidence_source": "plan_only",
                "release_gate": {
                    "status": "paid_pending",
                    "passed": False,
                    "failures": ["paid_live_evidence_required"],
                },
            }
            write_payload(output, payload)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if not args.confirm_live_cost:
            parser.error("--confirm-live-cost is required for non-dry execution")
        if not args.results_json:
            parser.error(
                "--results-json is required; this cost-free harness never launches paid providers"
            )
        results_payload = load_json(Path(args.results_json))
        aggregation = aggregate_results(matrix, cases, results_payload.get("results"))
        payload = {
            **common,
            "evidence_source": "injected_results",
            **aggregation,
        }
        write_payload(output, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["release_gate"]["passed"] else 1
    except MigrationContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
