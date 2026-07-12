#!/usr/bin/env python3
"""Cost-free contract checks for the immutable CPE v4 quality matrix."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from live_migration.compiler import compile_v4_manifest
from live_migration.contracts import (
    CREDENTIALLED_CALL,
    EXPECTED_POLICY_FAILURE,
    LiveMigrationContractError,
    SlotKey,
    canonical_json,
)
from live_migration.ledger import (
    LedgerError,
    create_run,
    record_terminal_full_run,
    replay_run,
)
from live_migration.runner import execute_v4_slots


ROOT = Path(__file__).resolve().parent


def expect_error(callable_, error_type: type[Exception], message: str) -> None:
    try:
        callable_()
    except error_type:
        return
    raise AssertionError(message)


def check_exact_manifest() -> dict[str, object]:
    manifest = compile_v4_manifest(commit="a" * 40, run_id="v4-test")
    slots = manifest["slots"]
    assert manifest["schema_version"] == "cpe-quality-manifest.v4"
    assert len(slots) == 24
    assert manifest["credentialed_call_count"] == 17
    assert manifest["expected_policy_failure_count"] == 7
    assert {slot["model"] for slot in slots if slot["credentialed"]} == {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
    }
    assert {slot["reasoning"] for slot in slots} == {"high"}
    assert [slot["treatment_id"] for slot in slots[:8]] == ["sol_v31_control"] * 8
    assert [slot["treatment_id"] for slot in slots[8:16]] == ["sol_v4_candidate"] * 8
    assert slots[16]["treatment_id"] == "terra_v4"
    assert slots[16]["credentialed"] is True
    assert all(slot["treatment_id"] == "terra_v4" for slot in slots[17:])
    assert all(slot["outcome_kind"] == EXPECTED_POLICY_FAILURE for slot in slots[17:])
    assert all(slot["credentialed"] is False for slot in slots[17:])
    assert sum(slot["outcome_kind"] == CREDENTIALLED_CALL for slot in slots) == 17
    assert manifest["manifest_sha256"]
    assert manifest == compile_v4_manifest(commit="a" * 40, run_id="v4-test")
    return manifest


def check_registry_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-matrix-registry-") as raw:
        eval_dir = Path(raw)
        migration = eval_dir / "live-migration"
        migration.mkdir()
        (migration / "matrix-v4.json").write_text(
            '{"schema_version":"4","treatments":[]}\n', encoding="utf-8"
        )
        expect_error(
            lambda: compile_v4_manifest(
                commit="a" * 40,
                run_id="registry-drift",
                eval_dir=eval_dir,
            ),
            LiveMigrationContractError,
            "a drifted v4 treatment registry must fail closed",
        )


def check_v4_dry_run_cli() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-dry-run-") as raw:
        output = Path(raw) / "plan.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "dry-run",
                "--matrix",
                "v4",
                "--billing-mode",
                "chatgpt_subscription",
                "--run-id",
                "v4-cli-check",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["slot_count"] == 24
        assert payload["credentialed_call_count"] == 17
        assert payload["expected_policy_failure_count"] == 7
        assert {slot["model"] for slot in payload["slots"]} == {
            "gpt-5.6-sol",
            "gpt-5.6-terra",
        }
        assert "--sentinel-only" in subprocess.run(
            [sys.executable, str(ROOT / "live_model_runner.py"), "start", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout


def check_sentinel_resume_and_immutable_ledger(manifest: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-sentinel-") as raw:
        run = create_run(Path(raw) / "run", manifest)
        invocations: list[SlotKey] = []

        def fake_provider(slot: dict[str, object]) -> tuple[dict[str, bytes], dict[str, object]]:
            key = SlotKey(str(slot["treatment_id"]), str(slot["case_id"]))
            invocations.append(key)
            return (
                {"fake-provider.json": canonical_json({"slot": key.case_id})},
                {
                    "schema_version": "cpe-quality-result.v4",
                    "treatment_id": key.treatment_id,
                    "case_id": key.case_id,
                    "task_completed": True,
                },
            )

        first = execute_v4_slots(run, fake_provider, sentinel_only=True)
        assert first["executed_slots"] == 1
        assert first["provider_invocations"] == 1
        assert len(invocations) == 1
        assert replay_run(run.run_dir)["completed_slots"] == [
            {"treatment_id": "sol_v31_control", "case_id": "single-file implementation"}
        ]

        resumed = execute_v4_slots(run, fake_provider)
        assert resumed["executed_slots"] == 23
        assert resumed["provider_invocations"] == 16
        assert len(invocations) == 17
        projection = replay_run(run.run_dir)
        assert len(projection["completed_slots"]) == 24
        assert projection["pending_slots"] == []

        completed_again = execute_v4_slots(run, fake_provider)
        assert completed_again["executed_slots"] == 0
        assert completed_again["provider_invocations"] == 0
        assert len(invocations) == 17

        first_checkpoint = "1" * 64
        corrected_checkpoint = "2" * 64
        record_terminal_full_run(run, checkpoint_sha256=first_checkpoint, passed=False)
        after_first = replay_run(run.run_dir)
        assert after_first["terminal_full_runs"] == 1
        assert after_first["release_blocked"] is False
        expect_error(
            lambda: record_terminal_full_run(
                run, checkpoint_sha256=first_checkpoint, passed=False
            ),
            LedgerError,
            "a corrected full run must bind a changed checkpoint",
        )
        record_terminal_full_run(
            run, checkpoint_sha256=corrected_checkpoint, passed=False
        )
        after_second = replay_run(run.run_dir)
        assert after_second["terminal_full_runs"] == 2
        assert after_second["terminal_full_failures"] == 2
        assert after_second["release_blocked"] is True
        expect_error(
            lambda: record_terminal_full_run(
                run, checkpoint_sha256="3" * 64, passed=True
            ),
            LedgerError,
            "a third terminal full run must be rejected",
        )


def main() -> int:
    manifest = check_exact_manifest()
    check_registry_fails_closed()
    check_v4_dry_run_cli()
    check_sentinel_resume_and_immutable_ledger(manifest)
    print("quality matrix v4 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
