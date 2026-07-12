#!/usr/bin/env python3
"""Cost-free contract checks for the immutable CPE v4 quality matrix."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from live_migration.compiler import compile_v4_manifest, v4_case_prompt_bundles
from live_migration.contracts import (
    CREDENTIALLED_CALL,
    CaseRef,
    EXPECTED_POLICY_FAILURE,
    LiveMigrationContractError,
    SlotKey,
    canonical_json,
)
from live_migration.ledger import (
    LedgerError,
    append_event,
    create_run,
    record_terminal_full_run,
    record_release_terminal,
    register_release_run,
    replay_run,
    replay_release_lineage,
)
from live_migration.fixtures import materialize_fixture
from live_migration.runner import execute_v4_slots, render_prompt


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


def check_production_faithful_case_prompts(manifest: dict[str, object]) -> None:
    slots = manifest["slots"]
    for case_position in range(8):
        control = slots[case_position]
        candidate = slots[case_position + 8]
        bundles = v4_case_prompt_bundles(
            ROOT,
            str(control["case_id"]),
            str(control["case_slug"]),
        )
        assert control["prompt_sha256"] == bundles["control"].prompt_sha256
        assert candidate["prompt_sha256"] == bundles["candidate"].prompt_sha256
        assert control["case_sha256"] == candidate["case_sha256"]
        assert control["case_sha256"] == bundles["control"].case_sha256
        assert control["output_schema_sha256"] == candidate["output_schema_sha256"]
        assert control["output_schema_sha256"] == bundles["control"].output_schema_sha256
        assert control["task_contract_sha256"] == candidate["task_contract_sha256"]

    with tempfile.TemporaryDirectory(prefix="cpe-v4-prompt-render-") as raw:
        control = slots[0]
        fixture = materialize_fixture(
            ROOT / "live-migration",
            CaseRef(str(control["case_id"]), str(control["case_slug"])),
            Path(raw) / "repo",
        )
        prompt = render_prompt(control, fixture, ROOT)
        assert prompt == v4_case_prompt_bundles(
            ROOT,
            str(control["case_id"]),
            str(control["case_slug"]),
        )["control"].prompt
        assert str(fixture.repo) not in prompt


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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _checkpoint_arguments(repo: Path) -> list[str]:
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    patch = hashlib.sha256(
        subprocess.run(
            ["git", "show", "--format=", "--binary", commit],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
    ).hexdigest()
    return [
        "--implementation-commit",
        commit,
        "--implementation-tree",
        tree,
        "--implementation-patch-sha256",
        patch,
    ]


def check_fake_cli_sentinel_resume_waits_for_aggregate() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-production-cli-") as raw:
        tmp = Path(raw)
        repo = tmp / "repo"
        skill = repo / "skills" / "kws-codex-plan-executor"
        shutil.copytree(ROOT.parent, skill)
        subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=CPE quality eval",
                "-c",
                "user.email=cpe-quality@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "reviewed quality runtime",
            ],
            cwd=repo,
            check=True,
        )
        evidence_root = tmp / "evidence"
        auth_home = tmp / "auth-home"
        auth_home.mkdir()
        (auth_home / "auth.json").write_text("{}\n", encoding="utf-8")
        invocation_log = tmp / "invocations.jsonl"
        env = {
            **os.environ,
            "CODEX_HOME": str(auth_home),
            "CPE_FAKE_LOGIN": "chatgpt",
            "CPE_FAKE_MODELS": json.dumps(
                [
                    {"model": model, "reasoning_efforts": ["high"]}
                    for model in ("gpt-5.6-sol", "gpt-5.6-terra")
                ]
            ),
            "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        runner = skill / "evals" / "live_model_runner.py"
        run_id = "fake-v4-initial"
        start = subprocess.run(
            [
                sys.executable,
                str(runner),
                "start",
                "--matrix",
                "v4",
                "--billing-mode",
                "chatgpt_subscription",
                "--confirm-subscription-usage",
                "--sentinel-only",
                "--evidence-root",
                str(evidence_root),
                "--run-id",
                run_id,
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
                "--slot-timeout-seconds",
                "5",
                *_checkpoint_arguments(repo),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert start.returncode == 0, (start.stdout, start.stderr)
        assert json.loads(start.stdout)["status"] == "sentinel_completed"
        run_dir = evidence_root / run_id
        assert json.loads((run_dir / "state.json").read_text())["terminal_full_runs"] == 0

        resume = subprocess.run(
            [
                sys.executable,
                str(runner),
                "resume",
                "--confirm-subscription-usage",
                "--run-dir",
                str(run_dir),
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
                "--slot-timeout-seconds",
                "5",
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert resume.returncode == 0, (resume.stdout, resume.stderr)
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        assert len(state["completed_slots"]) == 24
        assert state["pending_slots"] == []
        assert state["terminal_full_runs"] == 0
        calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        provider_calls = [call for call in calls if call["argv"][:1] == ["exec"]]
        assert len(provider_calls) == 17
        assert all(
            re.search(
                r"/(?:Users|home|private|tmp|var/folders)/",
                str(call["stdin"]),
            )
            is None
            for call in provider_calls
        )
        policy_results = list((run_dir / "slots" / "terra_v4").glob("*/result.json"))
        assert sum(
            json.loads(path.read_text())["expected_policy_failure"] is True
            for path in policy_results
        ) == 7

        aggregate_output = evidence_root / "aggregate.json"
        aggregate = subprocess.run(
            [
                sys.executable,
                str(runner),
                "aggregate",
                "--run-dir",
                str(run_dir),
                "--output",
                str(aggregate_output),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert aggregate.returncode in {0, 1}, (aggregate.stdout, aggregate.stderr)
        aggregate_payload = json.loads(aggregate_output.read_text(encoding="utf-8"))
        assert aggregate_payload["credentialed_call_count"] == 17
        assert aggregate_payload["policy_outcome_count"] == 7
        assert aggregate_payload["duplicate_slot_count"] == 0
        assert aggregate_payload["pending_slot_count"] == 0
        assert aggregate_payload["release_gate"]["passed"] is False
        lineage = json.loads(
            (evidence_root / "quality-release-state.json").read_text(encoding="utf-8")
        )
        assert lineage["terminal_full_runs"] == 1
        assert lineage["terminal_full_failures"] == 1

        (repo / "corrected-checkpoint.txt").write_text(
            "corrected quality checkpoint\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "corrected-checkpoint.txt"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=CPE quality eval",
                "-c",
                "user.email=cpe-quality@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "corrected checkpoint",
            ],
            cwd=repo,
            check=True,
        )
        corrected_id = "fake-v4-corrected"
        corrected_start = subprocess.run(
            [
                sys.executable,
                str(runner),
                "start",
                "--matrix",
                "v4",
                "--billing-mode",
                "chatgpt_subscription",
                "--confirm-subscription-usage",
                "--sentinel-only",
                "--evidence-root",
                str(evidence_root),
                "--run-id",
                corrected_id,
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
                "--slot-timeout-seconds",
                "5",
                *_checkpoint_arguments(repo),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert corrected_start.returncode == 0, (
            corrected_start.stdout,
            corrected_start.stderr,
        )
        corrected_dir = evidence_root / corrected_id
        corrected_resume = subprocess.run(
            [
                sys.executable,
                str(runner),
                "resume",
                "--confirm-subscription-usage",
                "--run-dir",
                str(corrected_dir),
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
                "--slot-timeout-seconds",
                "5",
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert corrected_resume.returncode == 0, (
            corrected_resume.stdout,
            corrected_resume.stderr,
        )
        corrected_aggregate = subprocess.run(
            [
                sys.executable,
                str(runner),
                "aggregate",
                "--run-dir",
                str(corrected_dir),
                "--output",
                str(evidence_root / "aggregate-corrected.json"),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert corrected_aggregate.returncode == 1, corrected_aggregate.stdout
        lineage = json.loads(
            (evidence_root / "quality-release-state.json").read_text(encoding="utf-8")
        )
        assert lineage["terminal_full_runs"] == 2
        assert lineage["terminal_full_failures"] == 2
        assert lineage["release_blocked"] is True
        all_calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        assert sum(call["argv"][:1] == ["exec"] for call in all_calls) == 34

        (repo / "forbidden-third.txt").write_text("third\n", encoding="utf-8")
        subprocess.run(["git", "add", "forbidden-third.txt"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=CPE quality eval",
                "-c",
                "user.email=cpe-quality@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "forbidden third checkpoint",
            ],
            cwd=repo,
            check=True,
        )
        third = subprocess.run(
            [
                sys.executable,
                str(runner),
                "start",
                "--matrix",
                "v4",
                "--billing-mode",
                "chatgpt_subscription",
                "--confirm-subscription-usage",
                "--sentinel-only",
                "--evidence-root",
                str(evidence_root),
                "--run-id",
                "forbidden-third",
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
                *_checkpoint_arguments(repo),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert third.returncode == 1
        assert "terminal full run limit reached" in json.loads(third.stdout)["message"]
        all_calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        assert sum(call["argv"][:1] == ["exec"] for call in all_calls) == 34


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
        first_slot = manifest["slots"][0]
        first_dir = (
            run.run_dir
            / "slots"
            / quote(str(first_slot["treatment_id"]), safe="-._~")
            / quote(str(first_slot["case_id"]), safe="-._~")
        )
        result = json.loads((first_dir / "result.json").read_text(encoding="utf-8"))
        for field in (
            "prompt_sha256",
            "task_contract_sha256",
            "case_sha256",
            "output_schema_sha256",
        ):
            assert result[field] == first_slot[field]
        index = json.loads((first_dir / "index.json").read_text(encoding="utf-8"))
        assert "prompt-binding.json" in index["files"]

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


def check_release_lineage_preserves_corrected_run_cap() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-release-lineage-") as raw:
        root = Path(raw)
        first_manifest = compile_v4_manifest(commit="1" * 40, run_id="initial")
        second_manifest = compile_v4_manifest(commit="2" * 40, run_id="corrected")
        register_release_run(root, first_manifest)
        record_release_terminal(
            root,
            run_id="initial",
            passed=False,
            aggregate_sha256="a" * 64,
            privacy_sha256="b" * 64,
        )
        register_release_run(root, second_manifest)
        record_release_terminal(
            root,
            run_id="corrected",
            passed=False,
            aggregate_sha256="c" * 64,
            privacy_sha256="d" * 64,
        )
        lineage = replay_release_lineage(root)
        assert lineage["terminal_full_runs"] == 2
        assert lineage["terminal_full_failures"] == 2
        assert lineage["release_blocked"] is True
        expect_error(
            lambda: register_release_run(
                root,
                compile_v4_manifest(commit="3" * 40, run_id="forbidden-third"),
            ),
            LedgerError,
            "a third release-lineage run must be rejected before provider execution",
        )


def check_success_is_terminal_only_after_aggregate_and_privacy() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-success-gates-") as raw:
        root = Path(raw) / "evidence"
        manifest = compile_v4_manifest(commit="4" * 40, run_id="passing-run")
        register_release_run(root, manifest)
        run = create_run(root / "passing-run", manifest)

        def passing_provider(
            slot: dict[str, object],
        ) -> tuple[dict[str, bytes], dict[str, object]]:
            return (
                {"fake-provider.json": canonical_json({"passed": True})},
                {
                    "schema_version": "cpe-quality-result.v4",
                    "run_id": manifest["run_id"],
                    "treatment_id": slot["treatment_id"],
                    "case_id": slot["case_id"],
                    "outcome_kind": CREDENTIALLED_CALL,
                    "expected_policy_failure": False,
                    "task_completed": True,
                    "critical_regression": False,
                    "evidence_complete": True,
                    "model_attested": True,
                    "worktree_isolated": True,
                    "drift_free": True,
                },
            )

        execute_v4_slots(run, passing_provider)
        append_event(run, "run_completed", {"completed_slots": 24})
        before = replay_release_lineage(root)
        assert before["terminal_full_runs"] == 0
        output = root / "passing-aggregate.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "aggregate",
                "--run-dir",
                str(run.run_dir),
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
        assert payload["release_gate"]["passed"] is True
        assert payload["privacy_audit"]["passed"] is True
        after = replay_release_lineage(root)
        assert after["terminal_full_runs"] == 1
        assert after["release_passed"] is True


def main() -> int:
    manifest = check_exact_manifest()
    check_production_faithful_case_prompts(manifest)
    check_registry_fails_closed()
    check_v4_dry_run_cli()
    check_fake_cli_sentinel_resume_waits_for_aggregate()
    check_sentinel_resume_and_immutable_ledger(manifest)
    check_release_lineage_preserves_corrected_run_cap()
    check_success_is_terminal_only_after_aggregate_and_privacy()
    print("quality matrix v4 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
