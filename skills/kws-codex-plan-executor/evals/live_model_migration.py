#!/usr/bin/env python3
"""Build and evaluate the bounded CPE v3 live-migration release matrix.

This harness deliberately has no provider-launch implementation. A dry run
emits the complete bounded plan. A non-dry run aggregates explicitly supplied
result evidence after the operator confirms the cost boundary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from live_migration.contracts import canonical_json, sha256_bytes
from live_migration.ledger import LedgerError, replay_run


MAX_BUDGET_USD = 50.00
ESTIMATED_RUN_COST_USD = 1.50
CHATGPT_SUBSCRIPTION = "chatgpt_subscription"
METERED_DOLLAR = "metered_dollar"
METERED_INJECTED_RESULTS = "metered_injected_results"
VALIDATED_LIVE_RUN_LEDGER = "validated_live_run_ledger"
SUBSCRIPTION_BILLING_BOUNDARY = (
    "The runner cannot prove which account-side subscription or existing-credit "
    "bucket OpenAI consumed; operator account settings remain an external billing boundary."
)
REQUIRED_TOKEN_REDUCTION = 0.25
CORE_TREATMENTS = ("gpt55_current", "sol_current", "sol_v3")
EXPECTED_TREATMENT_IDS = (*CORE_TREATMENTS, "terra_scout")
EXPECTED_TREATMENTS = (
    ("gpt55_current", "gpt-5.5", "high", "current-v2-prompt.txt"),
    ("sol_current", "gpt-5.6-sol", "high", "current-v2-prompt.txt"),
    ("sol_v3", "gpt-5.6-sol", "high", "../../templates/fresh-session-prompt.txt"),
    ("terra_scout", "gpt-5.6-terra", "high", "terra-scout-generated"),
)
PINNED_PRODUCTION_CONTROL_RENDERER = (
    "../control-bundles/cpe-3.1.0-production.json"
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


def as_sha256(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise MigrationContractError(f"result field {field!r} must be a lowercase SHA-256")
    return value


def rate(records: list[dict[str, Any]], field: str) -> float:
    return round(sum(1 for record in records if as_bool(record, field)) / len(records), 6)


def validate_result_record(
    record: dict[str, object], expected_policy: bool, evidence_source: str
) -> None:
    if as_bool(record, "expected_policy_failure") is not expected_policy:
        raise MigrationContractError("result cannot override expected policy outcome")
    if evidence_source == METERED_INJECTED_RESULTS:
        return
    if evidence_source != VALIDATED_LIVE_RUN_LEDGER:
        raise MigrationContractError(f"unsupported evidence source: {evidence_source}")

    if record.get("schema_version") not in {"2", "cpe-live-result.v2"}:
        raise MigrationContractError("results must use the v2 live-result schema")
    if not isinstance(record.get("run_id"), str) or not record["run_id"]:
        raise MigrationContractError("result field 'run_id' must be a non-empty string")
    if record.get("billing_mode") != CHATGPT_SUBSCRIPTION:
        raise MigrationContractError("results must use ChatGPT subscription billing")
    expected_outcome = (
        "expected_policy_failure" if expected_policy else "credentialed_call"
    )
    if record.get("outcome_kind") != expected_outcome:
        raise MigrationContractError("result has invalid outcome_kind")
    as_sha256(record, "evidence_sha256")
    if expected_policy:
        as_sha256(record, "matrix_policy_sha256")
        forbidden_usage = {
            "context_tokens",
            "cache_tokens",
            "output_tokens",
            "latency_ms",
            "cost_usd",
            "cost_observability",
        }
        present_usage = sorted(forbidden_usage.intersection(record))
        if present_usage:
            raise MigrationContractError(
                "expected policy failures cannot contain provider usage metrics: "
                f"{present_usage}"
            )
    elif record.get("cost_usd", object()) is not None:
        raise MigrationContractError(
            "ChatGPT subscription results must record cost_usd=null"
        )


def aggregate_results(
    matrix: dict[str, Any],
    cases: dict[str, Any],
    results: list[dict[str, Any]],
    evidence_source: str = METERED_INJECTED_RESULTS,
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
        is_policy_failure = expected_policy[key]
        try:
            validate_result_record(record, is_policy_failure, evidence_source)
        except MigrationContractError as exc:
            raise MigrationContractError(
                f"{exc}: {key[0]}/{key[1]}"
            ) from exc

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
        treatment_metrics: dict[str, Any] = {
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
            "model_attestation_rate": rate(eligible_records, "model_attested"),
            "worktree_isolation_rate": rate(eligible_records, "worktree_isolated"),
            "drift_free_rate": rate(eligible_records, "drift_free"),
        }
        if evidence_source == VALIDATED_LIVE_RUN_LEDGER:
            treatment_metrics.update(
                {
                    "output_tokens": int(
                        sum(
                            as_number(record, "output_tokens")
                            for record in eligible_records
                        )
                    ),
                    "cost_usd": None,
                    "cost_observability": "unavailable",
                }
            )
        else:
            treatment_metrics["cost_usd"] = round(
                sum(as_number(record, "cost_usd") for record in eligible_records), 6
            )
        metrics[treatment_id] = treatment_metrics

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

    aggregation: dict[str, Any] = {
        "billing_mode": (
            CHATGPT_SUBSCRIPTION
            if evidence_source == VALIDATED_LIVE_RUN_LEDGER
            else METERED_DOLLAR
        ),
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
    if evidence_source == VALIDATED_LIVE_RUN_LEDGER:
        aggregation.update(
            {
                "cost_usd": None,
                "cost_observability": "unavailable",
                "billing_boundary": SUBSCRIPTION_BILLING_BOUNDARY,
                "credentialed_call_count": sum(
                    record["outcome_kind"] == "credentialed_call"
                    for record in results
                ),
                "expected_policy_failure_count": sum(
                    record["outcome_kind"] == "expected_policy_failure"
                    for record in results
                ),
            }
        )
    return aggregation


def _slot_path(run_dir: Path, treatment_id: str, case_id: str) -> Path:
    return run_dir / "slots" / quote(treatment_id, safe="-._~") / quote(
        case_id, safe="-._~"
    )


def _validate_runner_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != "cpe-live-manifest.v2":
        raise MigrationContractError("run must use the v2 live manifest")
    if manifest.get("billing_mode") != CHATGPT_SUBSCRIPTION:
        raise MigrationContractError("run manifest must use ChatGPT subscription billing")
    if not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]:
        raise MigrationContractError("run manifest must contain one non-empty run_id")
    if re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("implementation_commit", ""))) is None:
        raise MigrationContractError("run manifest is missing its implementation digest")
    invocation_policy = manifest.get("invocation_policy")
    if invocation_policy is not None:
        if re.fullmatch(
            r"[0-9a-f]{40}", str(manifest.get("implementation_tree", ""))
        ) is None:
            raise MigrationContractError("run manifest is missing its implementation tree")
        as_sha256(manifest, "implementation_patch_sha256")
        if not isinstance(invocation_policy, dict) or not invocation_policy:
            raise MigrationContractError("run manifest has an invalid invocation policy")
        if sha256_bytes(canonical_json(invocation_policy)) != as_sha256(
            manifest, "invocation_policy_sha256"
        ):
            raise MigrationContractError("run manifest invocation policy digest does not match")
    as_sha256(manifest, "manifest_sha256")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise MigrationContractError("run manifest is missing input digests")
    for name, digest in inputs.items():
        as_sha256({"digest": digest}, "digest")
        if not isinstance(name, str) or not name:
            raise MigrationContractError("run manifest has an invalid input digest name")
    as_sha256(manifest, "model_catalog_sha256")

    slots = manifest.get("slots")
    if not isinstance(slots, list) or len(slots) != 32:
        raise MigrationContractError("run manifest must contain the exact 32 slots")
    expected_keys = {
        (treatment_id, case_id)
        for treatment_id in EXPECTED_TREATMENT_IDS
        for case_id in EXPECTED_CASES
    }
    actual_keys: set[tuple[str, str]] = set()
    treatment_contract = {
        treatment_id: (model, reasoning, prompt)
        for treatment_id, model, reasoning, prompt in EXPECTED_TREATMENTS
    }
    for slot in slots:
        if not isinstance(slot, dict):
            raise MigrationContractError("every run manifest slot must be an object")
        key = (slot.get("treatment_id"), slot.get("case_id"))
        if key in actual_keys:
            raise MigrationContractError(f"duplicate run manifest slot: {key}")
        actual_keys.add(key)
        expected_treatment = treatment_contract.get(str(slot.get("treatment_id")))
        actual_treatment = (
            slot.get("model"),
            slot.get("reasoning"),
            slot.get("prompt_renderer"),
        )
        pinned_control_compatibility = (
            slot.get("treatment_id") in {"gpt55_current", "sol_current"}
            and expected_treatment is not None
            and actual_treatment[:2] == expected_treatment[:2]
            and actual_treatment[2] == PINNED_PRODUCTION_CONTROL_RENDERER
        )
        if actual_treatment != expected_treatment and not pinned_control_compatibility:
            raise MigrationContractError("run manifest slot changed the treatment contract")
        expected_policy = (
            slot.get("treatment_id") == "terra_scout"
            and slot.get("case_id") != EXPECTED_CASES[-1]
        )
        expected_outcome = (
            "expected_policy_failure" if expected_policy else "credentialed_call"
        )
        if (
            slot.get("expected_policy_failure") is not expected_policy
            or slot.get("outcome_kind") != expected_outcome
        ):
            raise MigrationContractError("run manifest slot changed the policy contract")
        as_sha256(slot, "prompt_sha256")
        if slot.get("expected_policy_failure"):
            as_sha256(slot, "matrix_policy_sha256")
        else:
            for field in (
                "fixture_ref_sha256",
                "oracle_ref_sha256",
                "output_schema_ref_sha256",
            ):
                as_sha256(slot, field)
    if actual_keys != expected_keys:
        raise MigrationContractError("run manifest does not match the exact 4x8 matrix")
    if manifest.get("credentialed_call_count") != 25:
        raise MigrationContractError("run manifest must contain 25 credentialed calls")
    if manifest.get("expected_policy_failure_count") != 7:
        raise MigrationContractError("run manifest must contain seven policy failures")


def aggregate_run(run_dir: Path) -> dict[str, Any]:
    """Replay and aggregate one immutable runner-owned live evidence directory."""

    root = Path(run_dir).expanduser().resolve()
    try:
        projection = replay_run(root)
        manifest = load_json(root / "manifest.json")
    except (LedgerError, OSError) as exc:
        raise MigrationContractError(f"invalid live run ledger: {exc}") from exc
    _validate_runner_manifest(manifest)
    if (
        projection.get("lifecycle_outcome") != "completed"
        or len(projection.get("completed_slots", [])) != 32
        or projection.get("pending_slots")
        or projection.get("failed_slots")
        or projection.get("active_slot") is not None
    ):
        raise MigrationContractError("live run ledger is not completely resolved")
    if projection.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise MigrationContractError("ledger projection is not bound to its manifest")

    results: list[dict[str, Any]] = []
    result_digests: dict[str, str] = {}
    for slot in manifest["slots"]:
        treatment_id = str(slot["treatment_id"])
        case_id = str(slot["case_id"])
        evidence_dir = _slot_path(root, treatment_id, case_id)
        result = load_json(evidence_dir / "result.json")
        index = load_json(evidence_dir / "index.json")
        if result.get("run_id") != manifest["run_id"]:
            raise MigrationContractError("live results contain mixed run_id values")
        if slot.get("expected_policy_failure") and (
            result.get("manifest_sha256") != manifest["manifest_sha256"]
            or result.get("matrix_policy_sha256") != slot.get("matrix_policy_sha256")
        ):
            raise MigrationContractError("policy result is not bound to its manifest slot")
        digest = as_sha256(index, "result_sha256")
        if sha256_bytes(canonical_json(result)) != digest:
            raise MigrationContractError("slot result is not bound to its ledger index")
        result_digests[f"{treatment_id}/{case_id}"] = digest
        results.append(result)

    matrix = {
        "schema_version": "1",
        "treatments": [
            {
                "id": treatment_id,
                "model": model,
                "reasoning": reasoning,
                "prompt": prompt,
            }
            for treatment_id, model, reasoning, prompt in EXPECTED_TREATMENTS
        ],
    }
    cases = {"cases": list(EXPECTED_CASES)}
    aggregation = aggregate_results(
        matrix, cases, results, evidence_source=VALIDATED_LIVE_RUN_LEDGER
    )
    return {
        **aggregation,
        "run_id": manifest["run_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "implementation_commit": manifest["implementation_commit"],
        "implementation_tree": manifest.get("implementation_tree"),
        "implementation_patch_sha256": manifest.get("implementation_patch_sha256"),
        "invocation_policy_sha256": manifest.get("invocation_policy_sha256"),
        "input_sha256": manifest["inputs"],
        "model_catalog_sha256": manifest["model_catalog_sha256"],
        "result_sha256": result_digests,
        "evidence_source": VALIDATED_LIVE_RUN_LEDGER,
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
    parser.add_argument(
        "--billing-mode",
        choices=(CHATGPT_SUBSCRIPTION, METERED_DOLLAR),
        default=CHATGPT_SUBSCRIPTION,
    )
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--output", required=True)
    parser.add_argument("--confirm-live-cost", action="store_true")
    parser.add_argument("--confirm-subscription-usage", action="store_true")
    parser.add_argument("--run-dir")
    parser.add_argument(
        "--results-json",
        help="Pre-generated 4x8 result evidence to aggregate; this harness never launches providers.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.billing_mode == CHATGPT_SUBSCRIPTION:
        if args.budget_usd is not None:
            parser.error("ChatGPT subscription mode does not accept --budget-usd")
        if args.confirm_live_cost:
            parser.error("ChatGPT subscription mode does not use --confirm-live-cost")
        if args.results_json:
            parser.error("ChatGPT subscription aggregation requires --run-dir ledger evidence")
    else:
        if args.budget_usd is None or args.budget_usd <= 0:
            parser.error("metered dollar mode requires a positive --budget-usd")
        if args.budget_usd > MAX_BUDGET_USD:
            parser.error("--budget-usd exceeds the $50.00 hard cap")
        if args.confirm_subscription_usage:
            parser.error("metered dollar mode does not use --confirm-subscription-usage")
        if args.run_dir:
            parser.error("metered dollar aggregation requires --results-json evidence")

    try:
        matrix, cases = load_matrix_inputs(Path(__file__).resolve().parent)
        execution_plan = build_execution_plan(matrix, cases)
        estimated_max_cost_usd = round(len(execution_plan) * ESTIMATED_RUN_COST_USD, 2)
        if args.billing_mode == METERED_DOLLAR and estimated_max_cost_usd > args.budget_usd:
            parser.error(
                f"estimated maximum cost ${estimated_max_cost_usd:.2f} exceeds "
                f"the supplied budget ${args.budget_usd:.2f}"
            )

        common = {
            "schema_version": "2",
            "dry_run": args.dry_run,
            "billing_mode": args.billing_mode,
            "treatment_count": len(matrix["treatments"]),
            "case_count": len(cases["cases"]),
            "execution_plan": execution_plan,
        }
        if args.billing_mode == CHATGPT_SUBSCRIPTION:
            common.update(
                {
                    "cost_usd": None,
                    "cost_observability": "unavailable",
                    "billing_boundary": SUBSCRIPTION_BILLING_BOUNDARY,
                }
            )
        else:
            common.update(
                {
                    "budget_usd": round(args.budget_usd, 2),
                    "hard_cap_usd": MAX_BUDGET_USD,
                    "estimated_max_cost_usd": estimated_max_cost_usd,
                }
            )
        output = Path(args.output)
        if args.dry_run:
            if args.run_dir:
                parser.error("--run-dir cannot be used with --dry-run")
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

        if args.billing_mode == METERED_DOLLAR:
            if not args.confirm_live_cost:
                parser.error("--confirm-live-cost is required for non-dry execution")
            if not args.results_json:
                parser.error(
                    "--results-json is required; this cost-free harness never launches paid providers"
                )
            results_payload = load_json(Path(args.results_json))
            aggregation = aggregate_results(
                matrix,
                cases,
                results_payload.get("results"),
                evidence_source=METERED_INJECTED_RESULTS,
            )
            payload = {
                **common,
                "evidence_source": METERED_INJECTED_RESULTS,
                **aggregation,
            }
            write_payload(output, payload)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if payload["release_gate"]["passed"] else 1
        if not args.confirm_subscription_usage:
            parser.error("--confirm-subscription-usage is required for subscription aggregation")
        if not args.run_dir:
            parser.error(
                "--run-dir is required; this cost-free harness never launches paid providers"
            )
        aggregation = aggregate_run(Path(args.run_dir))
        payload = {
            **common,
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
