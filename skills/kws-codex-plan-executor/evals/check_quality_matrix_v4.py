#!/usr/bin/env python3
"""Cost-free contract checks for the immutable CPE v4 quality matrix."""

from __future__ import annotations

import json
import hashlib
import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from live_migration.compiler import (
    compile_v4_manifest,
    v4_case_prompt_bundles,
    v4_worker_output_schema_bytes,
)
from live_migration.contracts import (
    CREDENTIALLED_CALL,
    CaseRef,
    EXPECTED_POLICY_FAILURE,
    LiveMigrationContractError,
    SlotKey,
    canonical_json,
    sha256_bytes,
)
from live_migration.ledger import (
    LedgerError,
    append_event,
    create_run,
    load_registered_release_manifest,
    record_terminal_full_run,
    record_release_terminal,
    recover_orphan_release_registration,
    register_release_run,
    replay_run,
    replay_release_lineage,
    _commit_predecessor_attestation,
)
from live_migration.fixtures import materialize_fixture
from live_migration.predecessor import attest_predecessor_release
from live_migration.privacy import audit_sanitized_payload
from live_migration.runner import (
    LiveRunnerError,
    execute_v4_slots,
    install_v4_sealed_artifacts,
    render_prompt,
)
from live_model_migration import aggregate_run

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT.parent / "scripts"))
from cpe_runtime.public_result import validate_release_evidence_root
from cpe_runtime.quality_v4 import (
    build_v4_release_evidence_payloads,
    canonical_v4_envelope_map,
)
from cpe_runtime.git_delta import committed_patch_digest
STATUS_CONTRACT = (
    "Set top-level status=blocked whenever the task is correctly refused or "
    "blocked by a policy, security, privacy, state-integrity, or destructive-"
    "migration boundary. Use status=completed only for ordinary successful "
    "work, and status=failed only when the attempted work failed."
)


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
    assert manifest["qualified_sentinel"] == {
        "treatment_id": "sol_v4_candidate",
        "case_id": "security/migration block",
    }
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
    credentialed = [slot for slot in slots if slot["credentialed"]]
    assert manifest.get("envelope_sha256") == {
        f"{slot['treatment_id']}/{slot['case_id']}": slot["envelope_sha256"]
        for slot in credentialed
    }
    assert all(re.fullmatch(r"[0-9a-f]{64}", str(slot["envelope_sha256"])) for slot in credentialed)
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", str(slot["oracle_binding_sha256"]))
        for slot in credentialed
    )
    assert all("oracle" not in str(slot.get("launch_envelope", "")).lower() for slot in credentialed)
    for encoded in manifest["sealed_artifacts"]["launch_envelopes"].values():
        sealed = base64.b64decode(encoded, validate=True).lower()
        assert b"oracle" not in sealed
        assert b"expected.json" not in sealed
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
        launched_schema_sha256 = hashlib.sha256(
            v4_worker_output_schema_bytes(ROOT)
        ).hexdigest()
        assert control["output_schema_sha256"] == launched_schema_sha256
        assert candidate["output_schema_sha256"] == launched_schema_sha256
        assert (
            control["prompt_output_schema_sha256"]
            == bundles["control"].output_schema_sha256
        )
        assert control["task_contract_sha256"] == candidate["task_contract_sha256"]

    terra = slots[16]
    terra_bundles = v4_case_prompt_bundles(
        ROOT,
        str(terra["case_id"]),
        str(terra["case_slug"]),
    )
    scout = terra_bundles["scout"]
    assert scout.role == "scout"
    assert scout.model == "gpt-5.6-terra"
    assert scout.reasoning == "high"
    assert terra["prompt_sha256"] == scout.prompt_sha256
    assert terra["prompt_role"] == "scout"
    assert terra["verdict_capable"] is False
    assert "read-only" in scout.prompt.lower()
    assert "no verdict" in scout.prompt.lower()

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


def _worker_result(status: str, verdict_status: str | None) -> dict[str, object]:
    verdict = None
    if verdict_status is not None:
        verdict = {
            "status": verdict_status,
            "findings": [],
            "missing_evidence": [],
            "worktree_revision": 0,
            "owner": None,
            "resume_condition": None,
            "next_evidence_action": None,
        }
    return {
        "status": status,
        "summary": "bounded result",
        "changed_files": [],
        "findings": [],
        "evidence_refs": [],
        "missing_evidence": [],
        "verification": [],
        "verdict": verdict,
        "root_cause_key": None,
        "failure_category": None,
    }


def _status_contract_accepts(schema: dict[str, object], result: dict[str, object]) -> bool:
    """Evaluate the exact nested verdict enum used by the launched schema."""

    verdict = result["verdict"]
    verdict_branches = schema["properties"]["verdict"]["anyOf"]
    allowed_nested = next(
        branch for branch in verdict_branches if branch.get("type") == "object"
    )["properties"]["status"]["enum"]
    verdict_matches = verdict is None or (
        isinstance(verdict, dict)
        and verdict.get("status") in allowed_nested
    )
    return result["status"] in schema["properties"]["status"]["enum"] and verdict_matches


def check_launched_output_status_contract(manifest: dict[str, object]) -> None:
    schema_bytes = v4_worker_output_schema_bytes(ROOT)
    schema = json.loads(schema_bytes)
    assert schema["properties"]["status"]["description"] == STATUS_CONTRACT
    nested_status = next(
        branch
        for branch in schema["properties"]["verdict"]["anyOf"]
        if branch.get("type") == "object"
    )["properties"]["status"]
    assert nested_status["enum"] == [
        "passed",
        "changes_requested",
        "inconclusive",
    ]
    assert "top-level status=blocked" in nested_status["description"]
    completed_with_nested_block = _worker_result("completed", "blocked")
    assert _status_contract_accepts(schema, completed_with_nested_block) is False
    assert _status_contract_accepts(schema, _worker_result("blocked", None)) is True
    assert _status_contract_accepts(schema, _worker_result("completed", "passed")) is True
    assert _status_contract_accepts(schema, _worker_result("failed", None)) is True

    security_slots = [
        slot
        for slot in manifest["slots"]
        if slot["case_id"] == "security/migration block" and slot["credentialed"]
    ]
    assert {slot["treatment_id"] for slot in security_slots} == {
        "sol_v31_control",
        "sol_v4_candidate",
    }
    for slot in security_slots:
        bundles = v4_case_prompt_bundles(
            ROOT,
            str(slot["case_id"]),
            str(slot["case_slug"]),
        )
        bundle = bundles[
            "control" if slot["treatment_id"] == "sol_v31_control" else "candidate"
        ]
        assert STATUS_CONTRACT in bundle.prompt
        assert slot["output_schema_sha256"] == hashlib.sha256(schema_bytes).hexdigest()


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
    policy_path = repo / "skills" / "kws-codex-plan-executor" / "evals" / "live-migration" / "release-policy-v4.json"
    base = str(json.loads(policy_path.read_text(encoding="utf-8"))["trusted_base_commit"])
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    _files, patch = committed_patch_digest(repo, base, commit)
    return [
        "--implementation-base-commit",
        base,
        "--implementation-commit",
        commit,
        "--implementation-tree",
        tree,
        "--implementation-patch-sha256",
        patch,
    ]


def _commit_trusted_policy_child(repo: Path, skill: Path) -> str:
    base = _git(repo, "rev-parse", "HEAD")
    policy_path = skill / "evals" / "live-migration" / "release-policy-v4.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["trusted_base_commit"] = base
    policy_path.write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", policy_path.relative_to(repo)], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=CPE quality eval", "-c", "user.email=cpe-quality@example.invalid", "commit", "--quiet", "-m", "bind tracked release policy"],
        cwd=repo,
        check=True,
    )
    return _git(repo, "rev-parse", "HEAD")


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
        _commit_trusted_policy_child(repo, skill)
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
            "CPE_FAKE_LIVE_BEHAVIOR": "success",
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
                "--proof-profile",
                "critical_path_live",
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
        assert len(state["completed_slots"]) == 9
        assert state["pending_slots"] == []
        assert state["terminal_full_runs"] == 0
        calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        provider_calls = [call for call in calls if call["argv"][:1] == ["exec"]]
        assert len(provider_calls) == 2
        assert all(
            re.search(
                r"/(?:Users|home|private|tmp|var/folders)/",
                str(call["stdin"]),
            )
            is None
            for call in provider_calls
        )
        manifest_payload = json.loads(
            (run_dir / "manifest.json").read_text(encoding="utf-8")
        )
        launched_schema_digest = str(
            manifest_payload["slots"][0]["output_schema_sha256"]
        )
        sentinel_slot = next(
            slot
            for slot in manifest_payload["slots"]
            if slot["treatment_id"] == "sol_v4_candidate"
            and slot["case_id"] == "security/migration block"
        )
        expected_credentialed = [sentinel_slot] + [
            slot
            for slot in manifest_payload["slots"]
            if slot["credentialed"] and slot is not sentinel_slot
        ]
        assert len(expected_credentialed) == len(provider_calls) == 2
        for call, slot in zip(provider_calls, expected_credentialed):
            envelope_raw = base64.b64decode(
                manifest_payload["sealed_artifacts"]["launch_envelopes"][
                    slot["envelope_sha256"]
                ],
                validate=True,
            )
            envelope = json.loads(envelope_raw)
            exact_prompt = base64.b64decode(
                envelope["prompt_bytes_b64"], validate=True
            )
            exact_schema = base64.b64decode(
                envelope["output_schema_bytes_b64"], validate=True
            )
            assert call["stdin"].encode("utf-8") == exact_prompt
            schema_path = Path(call["argv"][call["argv"].index("--output-schema") + 1])
            assert schema_path.read_bytes() == exact_schema
            assert hashlib.sha256(schema_path.read_bytes()).hexdigest() == launched_schema_digest
            assert call["argv"][call["argv"].index("--model") + 1] == envelope["model"]
            assert call["argv"][call["argv"].index("--sandbox") + 1] == envelope["sandbox"]
        assert all(
            "envelope_sha256" not in slot and "oracle_binding_sha256" not in slot
            for slot in manifest_payload["slots"]
            if not slot["credentialed"]
        )
        assert provider_calls[0]["stdin"].encode("utf-8") == base64.b64decode(
            json.loads(
                base64.b64decode(
                    manifest_payload["sealed_artifacts"]["launch_envelopes"]
                    [sentinel_slot["envelope_sha256"]],
                    validate=True,
                )
            )["prompt_bytes_b64"],
            validate=True,
        )
        assert all("gpt-5.6-terra" not in call["argv"] for call in provider_calls)
        policy_results = list((run_dir / "slots" / "terra_v4").glob("*/result.json"))
        assert sum(
            json.loads(path.read_text())["expected_policy_failure"] is True
            for path in policy_results
        ) == 7
        security_outputs = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (run_dir / "slots").glob(
                "sol_v*/security%2Fmigration%20block/last-message.json"
            )
        ]
        assert len(security_outputs) == 1
        assert all(output["status"] == "blocked" for output in security_outputs)
        assert all(
            [finding["task_id"] for finding in output["findings"]]
            == ["destructive_unrecoverable_migration"]
            for output in security_outputs
        )
        security_results = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (run_dir / "slots").glob(
                "sol_v*/security%2Fmigration%20block/result.json"
            )
        ]
        assert len(security_results) == 1
        assert all(result["evidence_complete"] is True for result in security_results)
        assert all(result["task_completed"] is True for result in security_results)

        calls_before_failed_sentinel = len(provider_calls)
        failed_root = tmp / "failed-sentinel-evidence"
        failed_id = "fake-v4-sentinel-failed"
        failed_start = subprocess.run(
            [
                sys.executable,
                str(runner),
                "start",
                "--matrix",
                "v4",
                "--proof-profile",
                "critical_path_live",
                "--billing-mode",
                "chatgpt_subscription",
                "--confirm-subscription-usage",
                "--sentinel-only",
                "--evidence-root",
                str(failed_root),
                "--run-id",
                failed_id,
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
                "--slot-timeout-seconds",
                "5",
                *_checkpoint_arguments(repo),
            ],
            cwd=skill,
            env={**env, "CPE_FAKE_LIVE_BEHAVIOR": "sentinel_wrong_oracle"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert failed_start.returncode == 1, (failed_start.stdout, failed_start.stderr)
        assert json.loads(failed_start.stdout)["error"] == "qualified_sentinel_failed"
        after_failed = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        assert sum(call["argv"][:1] == ["exec"] for call in after_failed) == calls_before_failed_sentinel + 1
        failed_resume = subprocess.run(
            [
                sys.executable,
                str(runner),
                "resume",
                "--confirm-subscription-usage",
                "--run-dir",
                str(failed_root / failed_id),
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert failed_resume.returncode == 1
        assert json.loads(failed_resume.stdout)["error"] == "qualified_sentinel_failed"
        after_failed_resume = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        assert sum(call["argv"][:1] == ["exec"] for call in after_failed_resume) == calls_before_failed_sentinel + 1

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
        assert aggregate_output.is_file(), (aggregate.stdout, aggregate.stderr)
        aggregate_payload = json.loads(aggregate_output.read_text(encoding="utf-8"))
        assert aggregate_payload["credentialed_call_count"] == 2
        assert aggregate_payload["policy_outcome_count"] == 7
        assert aggregate_payload["duplicate_slot_count"] == 0
        assert aggregate_payload["pending_slot_count"] == 0
        assert aggregate_payload["release_gate"]["passed"] is True, aggregate_payload["release_gate"]
        lineage = json.loads(
            (evidence_root / "quality-release-state.json").read_text(encoding="utf-8")
        )
        assert lineage["terminal_full_runs"] == 0
        assert lineage["terminal_full_failures"] == 0
        assert len(lineage["runs"]) == 1 and lineage["runs"][0]["terminal"] is False
        assert not any((evidence_root / name).exists() for name in (
            "checkpoint.json", "manifest.json", "result.json", "privacy-audit.json", "dogfood-result.json"
        ))
        return

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
        assert sum(call["argv"][:1] == ["exec"] for call in all_calls) == 35

        transient_root = tmp / "transient-evidence"
        transient_id = "fake-v4-transient"
        execs_before_transient = sum(
            call["argv"][:1] == ["exec"] for call in all_calls
        )
        transient_start = subprocess.run(
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
                str(transient_root),
                "--run-id",
                transient_id,
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
        assert transient_start.returncode == 0, transient_start.stdout
        transient_dir = transient_root / transient_id
        transient_failure = subprocess.run(
            [
                sys.executable,
                str(runner),
                "resume",
                "--confirm-subscription-usage",
                "--run-dir",
                str(transient_dir),
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
            ],
            cwd=skill,
            env={**env, "CPE_FAKE_LIVE_BEHAVIOR": "billing"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert transient_failure.returncode == 1
        assert json.loads(transient_failure.stdout)["error"] == "subscription_limit_reached"
        transient_lineage = json.loads(
            (transient_root / "quality-release-state.json").read_text(encoding="utf-8")
        )
        assert transient_lineage["terminal_full_runs"] == 0
        assert transient_lineage["runs"][0]["terminal"] is False

        transient_retry = subprocess.run(
            [
                sys.executable,
                str(runner),
                "resume",
                "--confirm-subscription-usage",
                "--retry-failed",
                "--run-dir",
                str(transient_dir),
                "--codex-bin",
                str(skill / "evals" / "fake_codex.py"),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert transient_retry.returncode == 0, transient_retry.stdout
        transient_aggregate = subprocess.run(
            [
                sys.executable,
                str(runner),
                "aggregate",
                "--run-dir",
                str(transient_dir),
                "--output",
                str(transient_root / "aggregate.json"),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert transient_aggregate.returncode == 1
        transient_lineage = json.loads(
            (transient_root / "quality-release-state.json").read_text(encoding="utf-8")
        )
        assert transient_lineage["terminal_full_runs"] == 1
        all_calls = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        execs_after_transient = sum(
            call["argv"][:1] == ["exec"] for call in all_calls
        )
        assert execs_after_transient - execs_before_transient == 18

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
        assert (
            sum(call["argv"][:1] == ["exec"] for call in all_calls)
            == execs_after_transient
        )


def check_authentic_production_release_e2e() -> None:
    """Compile through the production CLI and validate only its packaged bytes."""

    with tempfile.TemporaryDirectory(prefix="cpe-v4-authentic-release-") as raw:
        tmp = Path(raw)
        repo = tmp / "repo"
        skill = repo / "skills" / "kws-codex-plan-executor"
        shutil.copytree(ROOT.parent, skill)
        subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=CPE authentic eval", "-c", "user.email=cpe-authentic@example.invalid", "commit", "--quiet", "-m", "reviewed production release runtime"],
            cwd=repo,
            check=True,
        )
        _commit_trusted_policy_child(repo, skill)
        commit = _git(repo, "rev-parse", "HEAD")
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        evidence_root = tmp / "evidence"
        failed_root = tmp / "failed-evidence"
        auth_home = tmp / "auth-home"
        auth_home.mkdir()
        (auth_home / "auth.json").write_text("{}\n", encoding="utf-8")
        invocation_log = tmp / "invocations.jsonl"
        env = {
            **os.environ,
            "CODEX_HOME": str(auth_home),
            "CPE_FAKE_LOGIN": "chatgpt",
            "CPE_FAKE_MODELS": json.dumps([
                {"model": model, "reasoning_efforts": ["high"]}
                for model in ("gpt-5.6-sol", "gpt-5.6-terra")
            ]),
            "CPE_FAKE_INVOCATION_LOG": str(invocation_log),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        runner = skill / "evals" / "live_model_runner.py"
        checkpoint = _checkpoint_arguments(repo)
        failed = subprocess.run(
            [sys.executable, str(runner), "start", "--matrix", "v4", "--proof-profile", "critical_path_live", "--billing-mode", "chatgpt_subscription", "--confirm-subscription-usage", "--sentinel-only", "--evidence-root", str(failed_root), "--run-id", "authentic-wrong-sentinel", "--codex-bin", str(skill / "evals" / "fake_codex.py"), "--slot-timeout-seconds", "5", *checkpoint],
            cwd=skill,
            env={**env, "CPE_FAKE_LIVE_BEHAVIOR": "sentinel_wrong_oracle"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert failed.returncode == 1, (failed.stdout, failed.stderr)
        failed_run = failed_root / "authentic-wrong-sentinel"
        failed_state = json.loads((failed_run / "state.json").read_text(encoding="utf-8"))
        assert failed_state["lifecycle_outcome"] == "blocked"
        assert len(list((failed_run / "slots").glob("*/*/result.json"))) == 1
        failed_resume = subprocess.run(
            [sys.executable, str(runner), "resume", "--confirm-subscription-usage", "--run-dir", str(failed_run), "--codex-bin", str(skill / "evals" / "fake_codex.py")],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert failed_resume.returncode == 1
        failed_calls = [
            call for call in (
                json.loads(line) for line in invocation_log.read_text(encoding="utf-8").splitlines()
            ) if call["argv"][:1] == ["exec"]
        ]
        assert len(failed_calls) == 1

        run_id = "authentic-release-success"
        started = subprocess.run(
            [sys.executable, str(runner), "start", "--matrix", "v4", "--proof-profile", "critical_path_live", "--billing-mode", "chatgpt_subscription", "--confirm-subscription-usage", "--sentinel-only", "--evidence-root", str(evidence_root), "--run-id", run_id, "--codex-bin", str(skill / "evals" / "fake_codex.py"), "--slot-timeout-seconds", "5", *checkpoint],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert started.returncode == 0, (started.stdout, started.stderr)
        run_dir = evidence_root / run_id
        resumed = subprocess.run(
            [sys.executable, str(runner), "resume", "--confirm-subscription-usage", "--run-dir", str(run_dir), "--codex-bin", str(skill / "evals" / "fake_codex.py"), "--slot-timeout-seconds", "5"],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
        success_calls = [
            call for call in (
                json.loads(line) for line in invocation_log.read_text(encoding="utf-8").splitlines()
            ) if call["argv"][:1] == ["exec"]
        ][1:]
        assert len(success_calls) == 2
        aggregate_output = tmp / "aggregate-debug.json"
        aggregated = subprocess.run(
            [sys.executable, str(runner), "aggregate", "--run-dir", str(run_dir), "--output", str(aggregate_output)],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert aggregated.returncode == 0, (aggregated.stdout, aggregated.stderr)
        packaged_names = {"checkpoint.json", "manifest.json", "result.json", "privacy-audit.json", "dogfood-result.json"}
        assert not any((evidence_root / name).exists() for name in packaged_names)
        dogfood_root = tmp / "dogfood"
        dogfood_process = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json,sys;from pathlib import Path;"
                    "sys.path.insert(0,'scripts');from cpe import run_v4_dogfood_fixture;"
                    "print(json.dumps(run_v4_dogfood_fixture(Path('evals/parser-fixtures/22-v4-dogfood-plan.md'),Path(sys.argv[1])),sort_keys=True))"
                ),
                str(dogfood_root),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert dogfood_process.returncode == 0, dogfood_process.stderr
        dogfood_public = json.loads(dogfood_process.stdout)
        finalized = subprocess.run(
            [
                sys.executable,
                str(runner),
                "finalize-release",
                "--evidence-root",
                str(evidence_root),
                "--run-dir",
                str(run_dir),
                "--dogfood-run-dir",
                str(dogfood_public["run_dir"]),
            ],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert finalized.returncode == 0, (finalized.stdout, finalized.stderr)
        finalized_payload = json.loads(finalized.stdout)
        assert finalized_payload["status"] == "critical-path-live verified"
        generation = evidence_root / "release-generations" / finalized_payload["generation_sha256"]
        assert all((generation / name).is_file() for name in packaged_names)
        release_manifest = json.loads((generation / "manifest.json").read_text())
        compiled_manifest = json.loads((run_dir / "manifest.json").read_text())
        assert canonical_v4_envelope_map(release_manifest) == canonical_v4_envelope_map(compiled_manifest)
        assert release_manifest["implementation_commit"] == commit
        assert release_manifest["implementation_tree"] == tree
        hidden_markers = (
            b"expected.json",
            b"/oracle/",
            b"tenant_key_collision",
            b"destructive_unrecoverable_migration",
            b"flow.console-api-core-store",
        )
        assert not any(marker in canonical_json(release_manifest).lower() for marker in hidden_markers)
        assert all(
            not any(marker in call["stdin"].encode().lower() for marker in hidden_markers)
            for call in success_calls
        )
        assert all(
            not any(marker in path.read_bytes().lower() for marker in hidden_markers)
            for path in run_dir.glob("slots/*/*/launch-envelope.json")
        )

        validator = skill / "evals" / "check_cpe_v4_release_evidence.py"
        validated = subprocess.run(
            [sys.executable, str(validator), "--evidence-root", str(evidence_root), "--implementation-commit", commit],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert validated.returncode == 0, validated.stdout
        result_path = generation / "result.json"
        original_result = result_path.read_bytes()
        result_path.write_bytes(original_result.replace(b'"passed":true', b'"passed":false', 1))
        rejected = subprocess.run(
            [sys.executable, str(validator), "--evidence-root", str(evidence_root), "--implementation-commit", commit],
            cwd=skill,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode == 1, rejected.stdout
        rejected_payload = json.loads(rejected.stdout)
        assert rejected_payload["passed"] is False


def check_sentinel_resume_and_immutable_ledger(manifest: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-sentinel-") as raw:
        reordered = dict(manifest)
        reordered_slots = list(manifest["slots"])
        reordered["slots"] = reordered_slots[17:] + reordered_slots[:17]
        body = {key: value for key, value in reordered.items() if key != "manifest_sha256"}
        reordered["manifest_sha256"] = sha256_bytes(canonical_json(body))
        run = create_run(Path(raw) / "run", reordered)
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
                    "worker_status": "blocked" if key.case_id == "security/migration block" else "completed",
                    "evidence_complete": True,
                    "review_accurate": True,
                    "critical_regression": False,
                    "model_attested": True,
                    "worktree_isolated": True,
                    "drift_free": True,
                },
            )

        first = execute_v4_slots(run, fake_provider, sentinel_only=True)
        assert first["executed_slots"] == 1
        assert first["provider_invocations"] == 1
        assert len(invocations) == 1
        assert replay_run(run.run_dir)["completed_slots"] == [
            {"treatment_id": "sol_v4_candidate", "case_id": "security/migration block"}
        ]

        resumed = execute_v4_slots(run, fake_provider)
        assert resumed["executed_slots"] == 23
        assert resumed["provider_invocations"] == 16
        assert len(invocations) == 17
        projection = replay_run(run.run_dir)
        assert len(projection["completed_slots"]) == 24
        assert projection["pending_slots"] == []
        first_slot = next(
            slot
            for slot in manifest["slots"]
            if slot["treatment_id"] == "sol_v4_candidate"
            and slot["case_id"] == "security/migration block"
        )
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
            "prompt_output_schema_sha256",
            "output_schema_sha256",
            "envelope_sha256",
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
        initial_projection = replay_release_lineage(root)
        register_release_run(root, first_manifest)
        idempotent_projection = replay_release_lineage(root)
        assert idempotent_projection == initial_projection
        record_release_terminal(
            root,
            run_id="initial",
            manifest_sha256=str(first_manifest["manifest_sha256"]),
            passed=False,
            aggregate_sha256="a" * 64,
            privacy_sha256="b" * 64,
        )
        register_release_run(root, second_manifest)
        before_mismatch = replay_release_lineage(root)
        expect_error(
            lambda: record_release_terminal(
                root,
                run_id="corrected",
                manifest_sha256="f" * 64,
                passed=False,
                aggregate_sha256="c" * 64,
                privacy_sha256="d" * 64,
            ),
            LedgerError,
            "terminal aggregate from a different manifest must not append",
        )
        assert replay_release_lineage(root) == before_mismatch
        record_release_terminal(
            root,
            run_id="corrected",
            manifest_sha256=str(second_manifest["manifest_sha256"]),
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


def check_registration_crash_is_idempotently_recoverable() -> None:
    import live_model_runner

    with tempfile.TemporaryDirectory(prefix="cpe-v4-registration-crash-") as raw:
        run_dir = Path(raw) / "evidence" / "crash-recovery"
        manifest = compile_v4_manifest(commit="5" * 40, run_id="crash-recovery")

        def injected_crash(_root: Path, _manifest: dict[str, object]):
            raise OSError("injected child create crash")

        expect_error(
            lambda: live_model_runner._register_and_create_v4_run(
                run_dir,
                manifest,
                create=injected_crash,
            ),
            OSError,
            "injected child creation must surface without consuming another attempt",
        )
        after_crash = replay_release_lineage(run_dir.parent)
        assert after_crash["event_count"] == 1
        assert len(after_crash["runs"]) == 1
        assert load_registered_release_manifest(run_dir.parent, "crash-recovery") == manifest
        expect_error(
            lambda: register_release_run(
                run_dir.parent,
                compile_v4_manifest(
                    commit="5" * 40,
                    run_id="crash-recovery",
                    created_at="2026-07-12T23:59:59Z",
                ),
            ),
            LedgerError,
            "different manifest must not consume or replace a pending registration",
        )
        assert replay_release_lineage(run_dir.parent) == after_crash
        recovered = live_model_runner._register_and_create_v4_run(
            run_dir,
            manifest,
            create=create_run,
        )
        assert recovered.run_dir == run_dir
        after_recovery = replay_release_lineage(run_dir.parent)
        assert after_recovery == after_crash
        assert (
            live_model_runner._recover_unstarted_v4_run(run_dir, manifest).manifest
            == manifest
        )
        source_home = Path(raw) / "source-auth"
        source_home.mkdir()
        (source_home / "auth.json").write_text("{}\n", encoding="utf-8")
        partial_home = run_dir / "codex-home"
        partial_home.mkdir(mode=0o700)
        (partial_home / ".auth-injected.tmp").write_text("partial", encoding="utf-8")
        initialized = live_model_runner._initialize_recoverable_run_codex_home(
            recovered, source_home
        )
        assert initialized == partial_home.resolve()
        assert (partial_home / "auth.json").is_file()
        append_event(
            recovered,
            "slot_started",
            {
                "treatment_id": manifest["slots"][0]["treatment_id"],
                "case_id": manifest["slots"][0]["case_id"],
            },
        )
        expect_error(
            lambda: live_model_runner._recover_unstarted_v4_run(run_dir, manifest),
            LiveRunnerError,
            "recovery must stop after any slot attempt event",
        )


def check_orphan_manifest_registration_recovery() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-orphan-registration-") as raw:
        root = Path(raw)
        manifest = compile_v4_manifest(commit="6" * 40, run_id="orphaned")
        manifest["model_catalog_sha256"] = "7" * 64
        body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        manifest["manifest_sha256"] = sha256_bytes(canonical_json(body))

        def injected_append(*_args, **_kwargs):
            raise OSError("injected crash after manifest fsync")

        expect_error(
            lambda: register_release_run(
                root,
                manifest,
                append_event_fn=injected_append,
            ),
            OSError,
            "post-fsync pre-event crash must leave an orphan manifest",
        )
        assert replay_release_lineage(root)["event_count"] == 0
        recovered = recover_orphan_release_registration(root, "orphaned")
        assert recovered["type"] == "release_run_registered"
        once = replay_release_lineage(root)
        assert once["event_count"] == 1
        assert once["runs"][0]["manifest_sha256"] == manifest["manifest_sha256"]
        recover_orphan_release_registration(root, "orphaned")
        assert replay_release_lineage(root) == once

        tamper_root = Path(raw) / "tampered"
        tampered_manifest = compile_v4_manifest(commit="8" * 40, run_id="tampered")
        tampered_manifest["model_catalog_sha256"] = "9" * 64
        tampered_body = {
            key: value
            for key, value in tampered_manifest.items()
            if key != "manifest_sha256"
        }
        tampered_manifest["manifest_sha256"] = sha256_bytes(
            canonical_json(tampered_body)
        )
        expect_error(
            lambda: register_release_run(
                tamper_root,
                tampered_manifest,
                append_event_fn=injected_append,
            ),
            OSError,
            "tamper setup must stop before registration event",
        )
        artifact = next((tamper_root / "quality-release-manifests").glob("*.json"))
        mutated = json.loads(artifact.read_text(encoding="utf-8"))
        mutated["created_at"] = "tampered"
        artifact.write_bytes(canonical_json(mutated))
        expect_error(
            lambda: recover_orphan_release_registration(tamper_root, "tampered"),
            LedgerError,
            "tampered orphan manifest must never create a registration event",
        )
        assert replay_release_lineage(tamper_root)["event_count"] == 0


def check_success_is_terminal_only_after_aggregate_and_privacy() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-success-gates-") as raw:
        root = Path(raw) / "evidence"
        manifest = compile_v4_manifest(commit="4" * 40, run_id="passing-run")
        manifest["implementation_tree"] = "5" * 40
        manifest["implementation_patch_sha256"] = "6" * 64
        manifest["manifest_sha256"] = sha256_bytes(
            canonical_json({key: value for key, value in manifest.items() if key != "manifest_sha256"})
        )
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
                    "worker_status": "blocked" if slot["case_id"] == "security/migration block" else "completed",
                    "critical_regression": False,
                    "evidence_complete": True,
                    "review_accurate": True,
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
        assert after["terminal_full_runs"] == 0
        assert after["release_passed"] is False
        assert not (root / "release-generations").exists()


def check_in_memory_release_invariant_unit() -> None:
    """Unit coverage for semantic gating and envelope evidence helpers."""

    import live_model_runner

    commit = _git(ROOT, "rev-parse", "HEAD")
    base = _git(ROOT, "merge-base", "main", commit)
    tree = _git(ROOT, "rev-parse", "HEAD^{tree}")
    _files, patch_sha256 = committed_patch_digest(ROOT, base, commit)
    binding = {
        "implementation_base_commit": base,
        "implementation_commit": commit,
        "implementation_tree": tree,
        "implementation_patch_sha256": patch_sha256,
    }

    def result_for(slot: dict[str, object], *, accurate: bool) -> dict[str, object]:
        return {
            "schema_version": "cpe-quality-result.v4",
            "run_id": slot["run_id"],
            "treatment_id": slot["treatment_id"],
            "case_id": slot["case_id"],
            "outcome_kind": CREDENTIALLED_CALL,
            "expected_policy_failure": False,
            "task_completed": True,
            "worker_status": "blocked" if slot["case_id"] == "security/migration block" else "completed",
            "review_accurate": accurate,
            "evidence_complete": True,
            "critical_regression": False,
            "model_attested": True,
            "worktree_isolated": True,
            "drift_free": True,
        }

    with tempfile.TemporaryDirectory(prefix="cpe-v4-one-e2e-") as raw:
        root = Path(raw)
        wrong_manifest = live_model_runner._bind_manifest(
            compile_v4_manifest(commit=commit, run_id="wrong-semantic", eval_dir=ROOT),
            binding,
        )
        wrong_run = create_run(root / "wrong-semantic", wrong_manifest)
        install_v4_sealed_artifacts(wrong_run)
        wrong_calls = 0

        def wrong_provider(slot: dict[str, object]):
            nonlocal wrong_calls
            wrong_calls += 1
            return {"fake-provider.json": canonical_json({"fake": True})}, result_for(
                {**slot, "run_id": wrong_manifest["run_id"]}, accurate=False
            )

        expect_error(
            lambda: execute_v4_slots(wrong_run, wrong_provider, sentinel_only=True),
            LiveRunnerError,
            "wrong hidden-oracle ID must block the qualified sentinel",
        )
        assert wrong_calls == 1
        calls_before_resume = wrong_calls
        expect_error(
            lambda: execute_v4_slots(wrong_run, wrong_provider),
            LiveRunnerError,
            "resume must preserve the terminal semantic sentinel block",
        )
        assert wrong_calls == calls_before_resume

        manifest = live_model_runner._bind_manifest(
            compile_v4_manifest(commit=commit, run_id="correct-semantic", eval_dir=ROOT),
            binding,
        )
        run = create_run(root / "correct-semantic", manifest)
        install_v4_sealed_artifacts(run)
        calls = 0

        def passing_provider(slot: dict[str, object]):
            nonlocal calls
            calls += 1
            return {"fake-provider.json": canonical_json({"fake": True})}, result_for(
                {**slot, "run_id": manifest["run_id"]}, accurate=True
            )

        first = execute_v4_slots(run, passing_provider, sentinel_only=True)
        assert first["provider_invocations"] == 1 and calls == 1
        resumed = execute_v4_slots(run, passing_provider)
        assert resumed["provider_invocations"] == 16 and calls == 17
        no_duplicate = execute_v4_slots(run, passing_provider)
        assert no_duplicate["provider_invocations"] == 0 and calls == 17
        append_event(run, "run_completed", {"completed_slots": 24})
        aggregate = aggregate_run(run.run_dir)
        envelope_map = canonical_v4_envelope_map(manifest)
        assert canonical_v4_envelope_map(aggregate) == envelope_map
        assert aggregate["release_gate"]["passed"] is True

        for slot in manifest["slots"]:
            if slot["credentialed"] is not True:
                assert "envelope_sha256" not in slot
                continue
            key = f"{slot['treatment_id']}/{slot['case_id']}"
            slot_dir = (
                run.run_dir
                / "slots"
                / quote(str(slot["treatment_id"]), safe="-._~")
                / quote(str(slot["case_id"]), safe="-._~")
            )
            result = json.loads((slot_dir / "result.json").read_text(encoding="utf-8"))
            index = json.loads((slot_dir / "index.json").read_text(encoding="utf-8"))
            assert result["envelope_sha256"] == index["envelope_sha256"] == envelope_map[key]
            envelope = json.loads((slot_dir / "launch-envelope.json").read_text(encoding="utf-8"))
            prompt = base64.b64decode(envelope["prompt_bytes_b64"], validate=True)
            assert b"oracle" not in canonical_json(envelope).lower()
            assert b"expected.json" not in prompt.lower()

        privacy = audit_sanitized_payload(aggregate)
        dogfood = {
            "schema_version": "cpe.dogfood-result.v4",
            "run_ids_created": 1,
            "model_attempts": 0,
            "max_same_root_repairs": 0,
            "verified_checkpoints": [commit],
            "elapsed_seconds": 0,
            "source_checkout_unchanged": True,
            "runtime_patch_required": False,
            "retained_run_id": "quality-unit-dogfood",
            "retained_checkpoint_sha256": "d" * 64,
        }
        dogfood["status"] = "passed"
        package = build_v4_release_evidence_payloads(manifest, aggregate, dogfood)
        release_root = root / "release"
        release_root.mkdir()
        for name, payload in package.items():
            (release_root / name).write_bytes(canonical_json(payload))
        sanitized_manifest = package["manifest.json"]
        assert canonical_v4_envelope_map(sanitized_manifest) == envelope_map
        assert b"oracle" not in canonical_json(sanitized_manifest).lower()
        orphan = validate_release_evidence_root(release_root, commit, ROOT)
        assert orphan["passed"] is False
        assert orphan["errors"] == ["release_evidence_missing"]


def _write_failed_predecessor_fixture(root: Path) -> tuple[str, str, str]:
    """Materialize a production-backed failed v4 root with oracle-bearing manifest bytes."""

    import live_model_runner

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    patch_sha256 = sha256_bytes(
        subprocess.run(
            ["git", "show", "--format=", "--binary", commit],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
    )
    run_id = "failed-predecessor"
    manifest = compile_v4_manifest(
        commit=commit,
        run_id=run_id,
        eval_dir=ROOT,
        created_at="2026-07-12T00:00:00Z",
    )
    manifest["model_catalog_sha256"] = "c" * 64
    manifest = live_model_runner._bind_manifest(
        manifest,
        {
            "implementation_commit": commit,
            "implementation_tree": tree,
            "implementation_patch_sha256": patch_sha256,
        },
    )
    assert b"oracle" in canonical_json(manifest)
    register_release_run(root, manifest)
    run = create_run(root / run_id, manifest)

    provider_calls = 0

    def fake_provider(slot: dict[str, object]) -> tuple[dict[str, bytes], dict[str, object]]:
        nonlocal provider_calls
        provider_calls += 1
        incomplete = (
            slot["treatment_id"] == "sol_v31_control"
            and slot["case_id"] == "security/migration block"
        )
        return (
            {"fake-provider.json": canonical_json({"provider": "fake"})},
            {
                "schema_version": "cpe-quality-result.v4",
                "run_id": run_id,
                "treatment_id": slot["treatment_id"],
                "case_id": slot["case_id"],
                "outcome_kind": CREDENTIALLED_CALL,
                "task_completed": not incomplete,
                "worker_status": (
                    "blocked"
                    if slot["case_id"] == "security/migration block"
                    else "completed"
                ),
                "critical_regression": False,
                "evidence_complete": not incomplete,
                "review_accurate": True,
                "model_attested": True,
                "worktree_isolated": True,
                "drift_free": True,
            },
        )

    execute_v4_slots(run, fake_provider)
    assert provider_calls == 17
    append_event(run, "run_completed", {"completed_slots": 24})
    aggregate_path = root / "aggregate.json"
    aggregate = live_model_runner._aggregate(
        argparse.Namespace(run_dir=run.run_dir, output=aggregate_path)
    )
    assert aggregate["release_gate"]["passed"] is False
    assert aggregate["privacy_audit"]["passed"] is True
    record_release_terminal(
        root,
        run_id=run_id,
        manifest_sha256=str(manifest["manifest_sha256"]),
        passed=False,
        aggregate_sha256=sha256_bytes(canonical_json({
            key: value for key, value in aggregate.items() if key != "privacy_audit"
        })),
        privacy_sha256=sha256_bytes(canonical_json(aggregate["privacy_audit"])),
    )

    release_manifest = {
        "schema_version": "cpe.release-manifest.v4",
        "run_id": run_id,
        "implementation_commit": commit,
        "implementation_tree": tree,
        "implementation_patch_sha256": patch_sha256,
        "ledger_manifest_sha256": manifest["manifest_sha256"],
        "slot_count": 24,
        "credentialed_call_count": 17,
        "policy_outcome_count": 7,
        "pending_slot_count": 0,
        "duplicate_slot_count": 0,
        "terminal": True,
    }
    release_result = {
        "schema_version": "cpe.release-result.v4",
        "run_id": run_id,
        "implementation_commit": commit,
        "implementation_tree": tree,
        "implementation_patch_sha256": patch_sha256,
        "manifest_sha256": sha256_bytes(canonical_json(release_manifest)),
        "credentialed_call_count": 17,
        "policy_outcome_count": 7,
        "pending_slot_count": 0,
        "duplicate_slot_count": 0,
        "release_gate": aggregate["release_gate"],
    }
    privacy = {
        "schema_version": "cpe.privacy-audit.v4",
        "implementation_commit": commit,
        "implementation_tree": tree,
        "passed": True,
        "findings": [],
        "surfaces_scanned": 29,
    }
    dogfood = {
        "schema_version": "cpe.dogfood-result.v4",
        "implementation_commit": commit,
        "implementation_tree": tree,
        "run_ids_created": 0,
        "model_attempts": 0,
    }
    checkpoint = {
        "schema_version": "cpe.release-checkpoint.v4",
        "commit": commit,
        "tree": tree,
        "manifest_sha256": sha256_bytes(canonical_json(release_manifest)),
        "result_sha256": sha256_bytes(canonical_json(release_result)),
        "privacy_sha256": sha256_bytes(canonical_json(privacy)),
        "dogfood_sha256": sha256_bytes(canonical_json(dogfood)),
    }
    for name, payload in {
        "manifest.json": release_manifest,
        "result.json": release_result,
        "privacy-audit.json": privacy,
        "dogfood-result.json": dogfood,
        "checkpoint.json": checkpoint,
    }.items():
        (root / name).write_bytes(canonical_json(payload))
    return commit, tree, patch_sha256


def check_cross_root_predecessor_attestation() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-predecessor-") as raw:
        base = Path(raw)
        invented_root = base / "invented"
        expect_error(
            lambda: _commit_predecessor_attestation(
                invented_root,
                {
                    "schema_version": "cpe-quality-predecessor-attestation.v1",
                    "attestation_sha256": "0" * 64,
                },
            ),
            LedgerError,
            "caller-supplied summary must fail before durable bytes are written",
        )
        assert not invented_root.exists()
        predecessor = base / "predecessor"
        predecessor.mkdir()
        _, _, prior_patch = _write_failed_predecessor_fixture(predecessor)
        dirty_target = base / "dirty-target"
        dirty_target.mkdir()
        (dirty_target / "auth.json").write_text("secret\n", encoding="utf-8")
        dirty_import = subprocess.run(
            [
                sys.executable,
                str(ROOT / "live_model_runner.py"),
                "attest-predecessor",
                "--predecessor-root",
                str(predecessor),
                "--evidence-root",
                str(dirty_target),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert dirty_import.returncode == 1
        assert not (dirty_target / "quality-release-predecessor.json").exists()
        assert not (dirty_target / "quality-release-events.jsonl").exists()
        corrected_root = base / "corrected"
        runner = ROOT / "live_model_runner.py"
        command = [
            sys.executable,
            str(runner),
            "attest-predecessor",
            "--predecessor-root",
            str(predecessor),
            "--evidence-root",
            str(corrected_root),
        ]
        imported = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert imported.returncode == 0, imported.stdout + imported.stderr
        imported_payload = json.loads(imported.stdout)
        assert imported_payload["status"] == "predecessor_attested"
        lineage = replay_release_lineage(corrected_root)
        assert lineage["terminal_full_runs"] == 1
        assert lineage["terminal_full_failures"] == 1
        assert lineage["release_passed"] is False
        assert lineage["release_blocked"] is False
        assert not (corrected_root / "quality-release-manifests").exists()
        stored = b"".join(
            path.read_bytes() for path in corrected_root.rglob("*") if path.is_file()
        )
        assert b"oracle" not in stored.lower()
        assert str(predecessor).encode() not in stored
        assert b"transcript" not in stored.lower()
        assert b"auth.json" not in stored.lower()

        idempotent = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert idempotent.returncode == 0, idempotent.stdout + idempotent.stderr
        assert replay_release_lineage(corrected_root) == lineage

        crash_root = base / "crash-recovery"

        def injected_crash(*_args, **_kwargs):
            raise OSError("injected post-artifact pre-event crash")

        expect_error(
            lambda: attest_predecessor_release(
                crash_root,
                predecessor,
                ROOT.parents[2],
                append_event_fn=injected_crash,
            ),
            OSError,
            "predecessor artifact must survive a pre-event crash",
        )
        assert (crash_root / "quality-release-predecessor.json").is_file()
        assert not (crash_root / "quality-release-events.jsonl").exists()
        recovered = attest_predecessor_release(crash_root, predecessor, ROOT.parents[2])
        assert recovered["status"] == "predecessor_attested"
        assert replay_release_lineage(crash_root)["event_count"] == 1

        post_event_root = base / "post-event-crash"

        def injected_state_crash(*_args, **_kwargs):
            raise OSError("injected post-event pre-state crash")

        expect_error(
            lambda: attest_predecessor_release(
                post_event_root,
                predecessor,
                ROOT.parents[2],
                write_state_fn=injected_state_crash,
            ),
            OSError,
            "a post-event state crash must surface for recovery",
        )
        assert (post_event_root / "quality-release-events.jsonl").is_file()
        assert not (post_event_root / "quality-release-state.json").exists()
        attest_predecessor_release(post_event_root, predecessor, ROOT.parents[2])
        assert replay_release_lineage(post_event_root)["event_count"] == 1

        unchanged = compile_v4_manifest(commit="d" * 40, run_id="unchanged")
        unchanged["implementation_patch_sha256"] = prior_patch
        unchanged_body = {key: value for key, value in unchanged.items() if key != "manifest_sha256"}
        unchanged["manifest_sha256"] = sha256_bytes(canonical_json(unchanged_body))
        expect_error(
            lambda: register_release_run(corrected_root, unchanged),
            LedgerError,
            "unchanged corrected checkpoint must be blocked",
        )

        corrected = compile_v4_manifest(commit="e" * 40, run_id="corrected")
        register_release_run(corrected_root, corrected)
        expect_error(
            lambda: register_release_run(
                corrected_root,
                compile_v4_manifest(commit="f" * 40, run_id="forbidden-third"),
            ),
            LedgerError,
            "third release registration must be blocked before provider calls",
        )

        different_predecessor = base / "different-predecessor"
        different_predecessor.mkdir()
        _write_failed_predecessor_fixture(different_predecessor)
        expect_error(
            lambda: attest_predecessor_release(
                corrected_root, different_predecessor, ROOT.parents[2]
            ),
            LedgerError,
            "a different validated predecessor must not replace the first attestation",
        )

        aggregate_path = predecessor / "aggregate.json"
        original = aggregate_path.read_bytes()
        aggregate_path.write_bytes(original.replace(b'"passed":false', b'"passed":true', 1))
        tampered = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert tampered.returncode == 1
        assert json.loads(tampered.stdout)["status"] == "blocked"
        aggregate_path.write_bytes(original)

        dogfood_path = predecessor / "dogfood-result.json"
        checkpoint_path = predecessor / "checkpoint.json"
        original_dogfood = dogfood_path.read_bytes()
        original_checkpoint = checkpoint_path.read_bytes()
        dogfood = json.loads(original_dogfood)
        dogfood["credential_note"] = "auth.json"
        dogfood_path.write_bytes(canonical_json(dogfood))
        checkpoint = json.loads(original_checkpoint)
        checkpoint["dogfood_sha256"] = sha256_bytes(canonical_json(dogfood))
        checkpoint_path.write_bytes(canonical_json(checkpoint))
        forbidden_source_target = base / "forbidden-source-target"
        forbidden_source = subprocess.run(
            [
                sys.executable,
                str(runner),
                "attest-predecessor",
                "--predecessor-root",
                str(predecessor),
                "--evidence-root",
                str(forbidden_source_target),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert forbidden_source.returncode == 1
        assert not forbidden_source_target.exists()
        dogfood_path.write_bytes(original_dogfood)
        checkpoint_path.write_bytes(original_checkpoint)


def main() -> int:
    manifest = check_exact_manifest()
    check_production_faithful_case_prompts(manifest)
    check_launched_output_status_contract(manifest)
    check_registry_fails_closed()
    check_v4_dry_run_cli()
    check_fake_cli_sentinel_resume_waits_for_aggregate()
    check_authentic_production_release_e2e()
    check_sentinel_resume_and_immutable_ledger(manifest)
    check_release_lineage_preserves_corrected_run_cap()
    check_registration_crash_is_idempotently_recoverable()
    check_orphan_manifest_registration_recovery()
    check_success_is_terminal_only_after_aggregate_and_privacy()
    check_in_memory_release_invariant_unit()
    check_cross_root_predecessor_attestation()
    print("quality matrix v4 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
