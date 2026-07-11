#!/usr/bin/env python3
"""Deterministic contract checks for the subscription live-matrix compiler."""

from __future__ import annotations

import dataclasses
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable


EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))


def _raises_contract_error(
    operation: Callable[[], object],
    error_type: type[Exception],
) -> bool:
    try:
        operation()
    except error_type:
        return True
    return False


def _copy_inputs(destination: Path) -> Path:
    copied_eval_dir = destination / "evals"
    migration_dir = copied_eval_dir / "live-migration"
    templates_dir = destination / "templates"
    migration_dir.mkdir(parents=True)
    templates_dir.mkdir()
    for name in ("matrix.json", "cases.json", "current-v2-prompt.txt"):
        shutil.copy2(EVAL_DIR / "live-migration" / name, migration_dir / name)
    shutil.copy2(
        EVAL_DIR.parent / "templates" / "fresh-session-prompt.txt",
        templates_dir / "fresh-session-prompt.txt",
    )
    return copied_eval_dir


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    try:
        from live_migration.compiler import compile_manifest, load_registry
        from live_migration.contracts import (
            CaseRef,
            LiveMigrationContractError,
            SlotKey,
            Treatment,
            canonical_json,
            sha256_bytes,
        )
    except ImportError as exc:
        print(json.dumps({"passed": False, "failures": [f"compiler unavailable: {exc}"]}))
        return 1

    treatments, cases = load_registry(EVAL_DIR)
    import live_model_migration

    try:
        legacy_matrix, legacy_cases = live_model_migration.load_matrix_inputs(EVAL_DIR)
        legacy_plan = live_model_migration.build_execution_plan(legacy_matrix, legacy_cases)
    except live_model_migration.MigrationContractError:
        legacy_plan = []
    manifest = compile_manifest(
        eval_dir=EVAL_DIR,
        billing_mode="chatgpt_subscription",
        implementation_commit="a" * 40,
        created_at="2026-07-11T00:00:00Z",
        run_id="cpe-v3-live-test",
    )
    slots = manifest["slots"]

    checks["canonical_helpers"] = (
        sha256_bytes(b"contract")
        == "cc8321d6375c494d043fdd0260f21bc0ec51dacc9f6abb7f909cdcd3041b78bf"
        and canonical_json({"b": 2, "a": 1}) == b'{"a":1,"b":2}\n'
    )
    checks["immutable_types"] = (
        dataclasses.is_dataclass(Treatment)
        and dataclasses.is_dataclass(CaseRef)
        and dataclasses.is_dataclass(SlotKey)
        and Treatment.__dataclass_params__.frozen
        and CaseRef.__dataclass_params__.frozen
        and SlotKey.__dataclass_params__.frozen
    )
    checks["exact_registry"] = (
        len(treatments) == 4
        and len(cases) == 8
        and all(isinstance(item, Treatment) for item in treatments)
        and all(isinstance(item, CaseRef) for item in cases)
        and cases[0].slug == "single-file-implementation"
        and cases[-1].slug == "large-read-only-exploration"
    )
    checks["v2_registry_preserves_existing_consumer"] = (
        len(legacy_plan) == 32
        and legacy_plan[0]["case_id"] == cases[0].id
        and legacy_plan[-1]["case_id"] == cases[-1].id
    )
    checks["exact_contract_shape"] = (
        manifest["schema_version"] == "cpe-live-manifest.v2"
        and manifest["run_id"] == "cpe-v3-live-test"
        and manifest["created_at"] == "2026-07-11T00:00:00Z"
        and manifest["implementation_commit"] == "a" * 40
        and manifest["treatment_count"] == 4
        and manifest["case_count"] == 8
        and len(slots) == 32
        and len({(slot["treatment_id"], slot["case_id"]) for slot in slots}) == 32
    )
    checks["exact_outcome_counts"] = (
        manifest["credentialed_call_count"] == 25
        and manifest["expected_policy_failure_count"] == 7
        and sum(slot["outcome_kind"] == "credentialed_call" for slot in slots) == 25
        and sum(slot["outcome_kind"] == "expected_policy_failure" for slot in slots) == 7
    )
    credentialed_slots = [
        slot for slot in slots if slot["outcome_kind"] == "credentialed_call"
    ]
    policy_slots = [
        slot for slot in slots if slot["outcome_kind"] == "expected_policy_failure"
    ]
    checks["credentialed_slots_bind_all_inputs"] = all(
        isinstance(slot.get("fixture"), str)
        and isinstance(slot.get("oracle"), str)
        and isinstance(slot.get("prompt_renderer"), str)
        and isinstance(slot.get("output_schema"), str)
        and slot.get("fixture_ref_sha256")
        == sha256_bytes(slot["fixture"].encode("utf-8"))
        and slot.get("oracle_ref_sha256")
        == sha256_bytes(slot["oracle"].encode("utf-8"))
        and isinstance(slot.get("prompt_sha256"), str)
        and len(slot["prompt_sha256"]) == 64
        and slot.get("output_schema_ref_sha256")
        == sha256_bytes(slot["output_schema"].encode("utf-8"))
        for slot in credentialed_slots
    )
    checks["policy_slots_bind_matrix_policy"] = all(
        isinstance(slot.get("policy_reason"), dict)
        and isinstance(slot.get("matrix_policy_sha256"), str)
        and len(slot["matrix_policy_sha256"]) == 64
        for slot in policy_slots
    )
    checks["subscription_has_no_dollar_budget"] = (
        manifest["billing_mode"] == "chatgpt_subscription"
        and "budget_usd" not in manifest
    )
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    checks["manifest_is_bound"] = (
        manifest["manifest_sha256"] == sha256_bytes(canonical_json(body))
        and all(len(value) == 64 for value in manifest["inputs"].values())
    )

    metered = compile_manifest(
        eval_dir=EVAL_DIR,
        billing_mode="metered_dollar",
        implementation_commit="b" * 40,
        created_at="2026-07-11T00:00:01Z",
        run_id="cpe-v3-live-metered-test",
        budget_usd=50.0,
    )
    checks["metered_boundary"] = (
        metered["billing_mode"] == "metered_dollar"
        and metered["budget_usd"] == 50.0
        and _raises_contract_error(
            lambda: compile_manifest(
                eval_dir=EVAL_DIR,
                billing_mode="metered_dollar",
                implementation_commit="b" * 40,
                created_at="2026-07-11T00:00:01Z",
                run_id="cpe-v3-live-metered-test",
            ),
            LiveMigrationContractError,
        )
        and _raises_contract_error(
            lambda: compile_manifest(
                eval_dir=EVAL_DIR,
                billing_mode="metered_dollar",
                implementation_commit="b" * 40,
                created_at="2026-07-11T00:00:01Z",
                run_id="cpe-v3-live-metered-test",
                budget_usd=50.01,
            ),
            LiveMigrationContractError,
        )
        and all(
            _raises_contract_error(
                lambda value=value: compile_manifest(
                    eval_dir=EVAL_DIR,
                    billing_mode="metered_dollar",
                    implementation_commit="b" * 40,
                    created_at="2026-07-11T00:00:01Z",
                    run_id="cpe-v3-live-metered-test",
                    budget_usd=value,
                ),
                LiveMigrationContractError,
            )
            for value in (
                math.nan,
                math.inf,
                -math.inf,
                "50",
                [],
                {},
            )
        )
    )

    with tempfile.TemporaryDirectory(prefix="cpe-live-compiler-") as raw:
        copied_eval_dir = _copy_inputs(Path(raw))

        matrix_path = copied_eval_dir / "live-migration" / "matrix.json"
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        matrix["treatments"][0]["model"] = "drifted-model"
        matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
        checks["model_mutation_rejected"] = _raises_contract_error(
            lambda: load_registry(copied_eval_dir), LiveMigrationContractError
        )

        copied_eval_dir = _copy_inputs(Path(raw) / "case-mutation")
        cases_path = copied_eval_dir / "live-migration" / "cases.json"
        registry = json.loads(cases_path.read_text(encoding="utf-8"))
        registry["cases"][0], registry["cases"][1] = registry["cases"][1], registry["cases"][0]
        cases_path.write_text(json.dumps(registry), encoding="utf-8")
        checks["case_reordering_rejected"] = _raises_contract_error(
            lambda: load_registry(copied_eval_dir), LiveMigrationContractError
        )

        copied_eval_dir = _copy_inputs(Path(raw) / "prompt-mutation")
        prompt_path = copied_eval_dir / "live-migration" / "current-v2-prompt.txt"
        prompt_path.write_bytes(prompt_path.read_bytes() + b"x")
        checks["prompt_mutation_rejected"] = _raises_contract_error(
            lambda: compile_manifest(
                eval_dir=copied_eval_dir,
                billing_mode="chatgpt_subscription",
                implementation_commit="a" * 40,
                created_at="2026-07-11T00:00:00Z",
                run_id="cpe-v3-live-test",
            ),
            LiveMigrationContractError,
        )

    failures.extend(name for name, passed in checks.items() if not passed)
    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
