#!/usr/bin/env python3
"""Cost-free release-transaction checks for the CPE v4 critical proof."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "evals"))

from cpe import run_v4_dogfood_fixture
from cpe_runtime.dogfood_v4 import verify_v4_dogfood_run
from cpe_runtime.git_delta import committed_patch_digest
from cpe_runtime.public_result import validate_release_evidence_root
from cpe_runtime.release_policy_v4 import (
    load_release_policy,
    validate_release_checkpoint,
)
from live_migration.compiler import compile_v4_manifest
from live_migration.contracts import CREDENTIALLED_CALL, LiveMigrationContractError, canonical_json
from live_migration.ledger import (
    LedgerError,
    append_event,
    create_run,
    register_release_run,
)
from live_migration.release_transaction import finalize_v4_release
from live_migration.runner import (
    LiveRunnerError,
    QUALIFIED_SENTINEL,
    _start_v4_credentialed_attempt,
    execute_v4_slots,
    install_v4_sealed_artifacts,
)


FIXTURE = SKILL_ROOT / "evals" / "parser-fixtures" / "22-v4-dogfood-plan.md"
POLICY = SKILL_ROOT / "evals" / "live-migration" / "release-policy-v4.json"


def git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()


def check_tracked_release_policy() -> None:
    policy = load_release_policy()
    assert policy["trusted_base_commit"] == "344f6112a7254b87cfa25fe0f6d6f3acbc964487"
    assert policy["critical_matrix_attempt_limit"] == 2
    assert policy["dogfood_attempt_limit"] == 4
    assert policy["combined_attempt_limit"] == 6
    assert policy["critical_path_live_label"] == "critical-path-live verified"
    assert policy["full_paid_matrix_deferred_label"] == "full paid-live certification deferred"
    contract = Path(str(policy["dogfood_task_contract_absolute_path"]))
    assert contract.is_file()
    assert policy["dogfood_task_contract_sha256"] == __import__("hashlib").sha256(
        contract.read_bytes()
    ).hexdigest()

    with tempfile.TemporaryDirectory(prefix="cpe-policy-fixture-") as raw:
        repo = Path(raw)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
        (repo / "contract.json").write_text(contract.read_text(encoding="utf-8"), encoding="utf-8")
        (repo / "seed.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()
        (repo / "seed.txt").write_text("child\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-qam", "child"], cwd=repo, check=True)
        child = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()
        fixture_policy = json.loads(POLICY.read_text(encoding="utf-8"))
        fixture_policy["trusted_base_commit"] = base
        fixture_policy["dogfood_task_contract_path"] = "contract.json"
        fixture_policy["dogfood_task_contract_sha256"] = __import__("hashlib").sha256(
            (repo / "contract.json").read_bytes()
        ).hexdigest()
        (repo / "policy.json").write_text(
            json.dumps(fixture_policy, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "policy.json"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "policy"], cwd=repo, check=True)
        policy_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()
        loaded = load_release_policy(repo / "policy.json", repository=repo)
        binding = validate_release_checkpoint(repo, policy_commit, policy=loaded)
        assert binding["implementation_base_commit"] == base
        orphan = subprocess.run(
            ["git", "commit-tree", subprocess.run(["git", "rev-parse", f"{child}^{{tree}}"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()],
            cwd=repo,
            input="orphan\n",
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        for rejected in (base, orphan):
            try:
                validate_release_checkpoint(repo, rejected, policy=loaded)
            except ValueError:
                pass
            else:
                raise AssertionError("base==head or stale child checkpoint was accepted")


def check_critical_profile() -> None:
    head = git_text("rev-parse", "HEAD")
    base = git_text("merge-base", "main", head)
    tree = git_text("rev-parse", f"{head}^{{tree}}")
    _files, patch = committed_patch_digest(REPO_ROOT, base, head)
    manifest = compile_v4_manifest(
        head,
        "critical-proof",
        proof_profile="critical_path_live",
        implementation_base_commit=base,
    )
    assert manifest["proof_profile"] == "critical_path_live"
    assert manifest["implementation_base_commit"] == base
    assert manifest["implementation_tree"] == tree
    assert manifest["implementation_patch_sha256"] == patch
    assert len(manifest["slots"]) == 9
    assert manifest["credentialed_call_count"] == 2
    assert manifest["expected_policy_failure_count"] == 7
    credentialed = [slot for slot in manifest["slots"] if slot["credentialed"]]
    assert [(slot["treatment_id"], slot["case_id"]) for slot in credentialed] == [
        ("sol_v4_candidate", "security/migration block"),
        ("sol_v4_candidate", "single-file implementation"),
    ]
    try:
        compile_v4_manifest(
            head,
            "base-equals-head",
            proof_profile="critical_path_live",
            implementation_base_commit=head,
        )
    except LiveMigrationContractError:
        pass
    else:
        raise AssertionError("compiler accepted caller-selected base==head")


def check_production_dogfood_verifier() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-dogfood-") as raw:
        result = run_v4_dogfood_fixture(FIXTURE, Path(raw))
        run_dir = Path(result["run_dir"])
        dogfood_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        assert dogfood_manifest["attempt_budget_limit"] == 4
        assert dogfood_manifest["release_policy_sha256"] == load_release_policy()["policy_sha256"]
        verified = verify_v4_dogfood_run(
            run_dir,
            expected_implementation_commit=result["implementation_commit"],
            expected_implementation_tree=result["implementation_tree"],
            expected_task_contract_sha256=result["task_contract_sha256"],
        )
        assert verified["status"] == "passed"
        assert verified["run_ids_created"] == 1
        assert 1 <= verified["model_attempts"] <= 4
        assert verified["max_same_root_repairs"] <= 2
        assert len(verified["verified_checkpoints"]) == 1
        assert verified["source_checkout_unchanged"] is True
        assert verified["runtime_patch_required"] is False
        assert verified["elapsed_seconds"] <= 3600

        events = run_dir / "events.jsonl"
        original = events.read_text(encoding="utf-8")
        lines = original.splitlines()
        event = json.loads(lines[-1])
        event["payload"]["forged"] = True
        lines[-1] = json.dumps(event, sort_keys=True, separators=(",", ":"))
        events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            verify_v4_dogfood_run(
                run_dir,
                expected_implementation_commit=result["implementation_commit"],
                expected_implementation_tree=result["implementation_tree"],
                expected_task_contract_sha256=result["task_contract_sha256"],
            )
        except ValueError as exc:
            assert str(exc) == "dogfood_run_integrity_invalid"
        else:
            raise AssertionError("tampered CPE event chain was accepted")


def check_orphan_root_cannot_validate() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-release-orphan-") as raw:
        root = Path(raw)
        generation = root / "release-generations" / ("a" * 64)
        generation.mkdir(parents=True)
        for name in (
            "checkpoint.json",
            "manifest.json",
            "result.json",
            "privacy-audit.json",
            "dogfood-result.json",
        ):
            (generation / name).write_text("{}\n", encoding="utf-8")
        report = validate_release_evidence_root(root, git_text("rev-parse", "HEAD"), REPO_ROOT)
        assert report["passed"] is False
        assert report["errors"] == ["release_evidence_missing"]


def _critical_run(root: Path) -> tuple[Path, str, str]:
    head = git_text("rev-parse", "HEAD")
    base = git_text("merge-base", "main", head)
    tree = git_text("rev-parse", f"{head}^{{tree}}")
    manifest = compile_v4_manifest(
        head,
        "critical-release",
        proof_profile="critical_path_live",
        implementation_base_commit=base,
    )
    manifest["model_catalog_sha256"] = "c" * 64
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    import hashlib

    manifest["manifest_sha256"] = hashlib.sha256(canonical_json(body)).hexdigest()
    register_release_run(root, manifest)
    run = create_run(root / str(manifest["run_id"]), manifest)
    install_v4_sealed_artifacts(run)
    calls = 0

    def provider(slot: dict[str, object]):
        nonlocal calls
        calls += 1
        blocked = slot["case_id"] == "security/migration block"
        return {"fake-provider.json": canonical_json({"fake": True})}, {
            "schema_version": "cpe-quality-result.v4",
            "run_id": manifest["run_id"],
            "treatment_id": slot["treatment_id"],
            "case_id": slot["case_id"],
            "outcome_kind": CREDENTIALLED_CALL,
            "expected_policy_failure": False,
            "task_completed": True,
            "first_pass_success": True,
            "worker_status": "blocked" if blocked else "completed",
            "review_accurate": True,
            "evidence_complete": True,
            "critical_regression": False,
            "model_attested": True,
            "worktree_isolated": True,
            "drift_free": True,
        }

    assert execute_v4_slots(run, provider, sentinel_only=True)["provider_invocations"] == 1
    resumed = execute_v4_slots(run, provider)
    assert resumed["provider_invocations"] == 1
    assert calls == 2
    for retry, expected in ((False, "critical_attempt_budget_exhausted"), (True, "retry_failed_forbidden")):
        try:
            _start_v4_credentialed_attempt(run, QUALIFIED_SENTINEL, retry=retry)
        except LiveRunnerError as exc:
            assert exc.code == expected
        else:
            raise AssertionError("release attempt budget permitted another paid start")
    assert calls == 2
    append_event(run, "run_completed", {"completed_slots": 9})
    return run.run_dir, head, tree


def check_terminal_generation_and_recovery() -> None:
    for crash_at in (None, "generation_before_event", "event_before_state"):
        with tempfile.TemporaryDirectory(prefix="cpe-v4-release-txn-") as raw:
            root = Path(raw) / "evidence"
            root.mkdir()
            run_dir, head, tree = _critical_run(root)
            dogfood_root = Path(raw) / "dogfood"
            dogfood = run_v4_dogfood_fixture(FIXTURE, dogfood_root)
            kwargs = {
                "evidence_root": root,
                "run_dir": run_dir,
                "dogfood_run_dir": Path(dogfood["run_dir"]),
                "repository": REPO_ROOT,
            }
            if crash_at:
                try:
                    finalize_v4_release(**kwargs, crash_at=crash_at)
                except LedgerError as exc:
                    assert str(exc) == f"injected_{crash_at}"
                else:
                    raise AssertionError("crash injection did not interrupt finalization")
                before_recovery = validate_release_evidence_root(root, head, REPO_ROOT)
                assert before_recovery["passed"] is False
            finalized = finalize_v4_release(**kwargs)
            assert finalized["status"] == "critical-path-live verified"
            assert finalized["full_paid_matrix_status"] == "full paid-live certification deferred"
            assert finalize_v4_release(**kwargs) == finalized
            report = validate_release_evidence_root(root, head, REPO_ROOT)
            assert report["passed"] is True, report
            retained = root / "dogfood" / str(dogfood["run_id"])
            assert retained.is_dir()
            assert {"run_manifest.json", "events.jsonl", "state.json", "task-contract.json", "checkpoint.json"}.issubset(
                {path.name for path in retained.iterdir()}
            )
            generation = root / "release-generations" / str(finalized["generation_sha256"])
            result_path = generation / "result.json"
            original = result_path.read_bytes()
            result_path.write_bytes(original.replace(b'"passed":true', b'"passed":false', 1))
            assert validate_release_evidence_root(root, head, REPO_ROOT)["passed"] is False
            result_path.write_bytes(original)
            mutations = {
                "manifest.json": (
                    '"implementation_patch_sha256":"',
                    '"implementation_patch_sha256":"' + "f" * 64 + '","forged_patch":"',
                ),
                "checkpoint.json": ('"commit":"', '"commit":"' + "f" * 40 + '","forged_commit":"'),
                "dogfood-result.json": ('"status":"passed"', '"debug_oracle":"expected.json","status":"passed"'),
            }
            for name, (before, after) in mutations.items():
                path = generation / name
                original_bytes = path.read_bytes()
                mutated = original_bytes.replace(before.encode(), after.encode(), 1)
                assert mutated != original_bytes
                path.write_bytes(mutated)
                assert validate_release_evidence_root(root, head, REPO_ROOT)["passed"] is False
                path.write_bytes(original_bytes)
            retained_state = retained / "state.json"
            original_state = retained_state.read_bytes()
            retained_state.write_bytes(original_state.replace(b'"schema_version":"4"', b'"schema_version":"x"', 1))
            assert validate_release_evidence_root(root, head, REPO_ROOT)["passed"] is False
            retained_state.write_bytes(original_state)
            retained_contract = retained / "task-contract.json"
            original_contract = retained_contract.read_bytes()
            retained_contract.write_bytes(original_contract.replace(b'"task_id":"task_1"', b'"task_id":"other_1"', 1))
            assert validate_release_evidence_root(root, head, REPO_ROOT)["passed"] is False
            retained_contract.write_bytes(original_contract)
            removed = retained.with_name(retained.name + "-removed")
            retained.rename(removed)
            assert validate_release_evidence_root(root, head, REPO_ROOT)["passed"] is False
            removed.rename(retained)
            for forbidden in ("checkpoint.json", "manifest.json", "result.json", "privacy-audit.json", "dogfood-result.json", "aggregate.json"):
                marker = root / forbidden
                marker.write_text("{}\n", encoding="utf-8")
                assert validate_release_evidence_root(root, head, REPO_ROOT)["passed"] is False
                marker.unlink()
            unexpected = root / "unexpected.txt"
            unexpected.write_text("x\n", encoding="utf-8")
            assert validate_release_evidence_root(root, head, REPO_ROOT)["passed"] is False
            unexpected.unlink()


def main() -> int:
    check_tracked_release_policy()
    check_critical_profile()
    check_production_dogfood_verifier()
    check_orphan_root_cannot_validate()
    check_terminal_generation_and_recovery()
    print("release transaction v4 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
