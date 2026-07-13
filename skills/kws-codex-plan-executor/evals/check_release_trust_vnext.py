#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.git_delta import committed_patch_digest as measured_patch_digest
from cpe_runtime.git_objects import (
    GitObjectSource,
    TrustRoot,
    canonical_repository_identity,
    committed_patch_digest,
)
from cpe_runtime.release_policy_vnext import (
    DOGFOOD_CONTRACT_PATH,
    POLICY_PATH,
    load_trust_root,
    validate_policy_bytes,
)


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def git_bytes(repository: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=repository, capture_output=True, check=True
    ).stdout


def write(repository: Path, relative: str, content: bytes) -> None:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def policy_bytes(base: str, contract: bytes, **extra: object) -> bytes:
    return canonical_json(
        {
            "schema_version": "cpe.release-policy.vnext",
            "trusted_base_commit": base,
            "dogfood_contract_sha256": sha256_bytes(contract),
            "release_labels": [
                "critical-path-live verified",
                "full paid-live certification deferred",
            ],
            "attempt_ceilings": {
                "critical_matrix": 2,
                "dogfood": 4,
                "combined": 6,
            },
            **extra,
        }
    )


def commit_all(repository: Path, message: str) -> str:
    git(repository, "add", "-A")
    git(repository, "commit", "-qm", message)
    return git(repository, "rev-parse", "HEAD")


def expect_value_error(call, expected: str) -> bool:
    try:
        call()
    except ValueError as exc:
        return str(exc) == expected
    return False


def fixture(repository: Path) -> tuple[str, str, bytes]:
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "CPE Eval")
    git(repository, "config", "user.email", "cpe-eval@example.invalid")
    contract = canonical_json({"schema_version": "cpe.dogfood-contract.vnext", "task": "T1"})
    write(repository, DOGFOOD_CONTRACT_PATH, contract)
    write(repository, "seed.txt", b"trusted base\n")
    base = commit_all(repository, "trusted base")
    write(repository, POLICY_PATH, policy_bytes(base, contract))
    write(
        repository,
        "skills/kws-codex-plan-executor/evals/live-migration/alternate-policy.json",
        policy_bytes("0" * 40, contract),
    )
    reviewed = commit_all(repository, "reviewed release inputs")
    return base, reviewed, contract


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-release-trust-vnext-") as raw:
        repo = Path(raw)
        base, reviewed_commit, contract = fixture(repo)
        root = load_trust_root(repo, reviewed_commit)
        _files, expected_patch = measured_patch_digest(repo, base, reviewed_commit)

        checks["fixed_policy_git_blob"] = (
            root.policy.path == POLICY_PATH
            and root.policy.blob_oid
            == git(repo, "rev-parse", f"{reviewed_commit}:{root.policy.path}")
            and root.policy.sha256
            == hashlib.sha256(
                git_bytes(repo, "show", f"{reviewed_commit}:{root.policy.path}")
            ).hexdigest()
        )
        checks["fixed_contract_git_blob"] = (
            root.dogfood_contract.path == DOGFOOD_CONTRACT_PATH
            and root.dogfood_contract.content == contract
            and root.dogfood_contract.blob_oid
            == git(repo, "rev-parse", f"{reviewed_commit}:{DOGFOOD_CONTRACT_PATH}")
        )
        checks["canonical_repository_and_tree"] = (
            root.repository_identity == canonical_repository_identity(repo)
            and root.reviewed_tree == git(repo, "rev-parse", f"{reviewed_commit}^{{tree}}")
            and root.trusted_base_tree == git(repo, "rev-parse", f"{base}^{{tree}}")
            and root.body()["trusted_base_tree"] == root.trusted_base_tree
        )
        checks["canonical_patch_and_root_digest"] = (
            root.patch_sha256 == expected_patch
            and root.patch_sha256
            == committed_patch_digest(repo, root.trusted_base_commit, reviewed_commit)
            and root.trust_root_sha256 == sha256_bytes(canonical_json(root.body()))
            and root.body()["release_labels"] == list(root.release_labels)
            and root.body()["attempt_ceilings"] == dict(root.attempt_ceilings)
        )

        try:
            root.reviewed_commit = base  # type: ignore[misc]
        except FrozenInstanceError:
            checks["trust_root_is_frozen"] = True
        else:
            checks["trust_root_is_frozen"] = False
        try:
            root.attempt_ceilings["combined"] = 99  # type: ignore[index]
        except TypeError:
            checks["attempt_ceilings_are_deeply_immutable"] = True
        else:
            checks["attempt_ceilings_are_deeply_immutable"] = False

        alternate = repo / "skills/kws-codex-plan-executor/evals/live-migration/alternate-policy.json"
        alternate.write_bytes(policy_bytes("f" * 40, contract))
        checks["alternate_path_cannot_select_trust"] = (
            load_trust_root(repo, reviewed_commit).policy.path == POLICY_PATH
        )
        alternate.write_bytes(git_bytes(repo, "show", f"{reviewed_commit}:{alternate.relative_to(repo)}"))

        policy_file = repo / POLICY_PATH
        policy_file.write_bytes(policy_bytes(base, contract, dogfood_task_contract_path="elsewhere"))
        checks["dirty_fixed_path_rejected"] = expect_value_error(
            lambda: load_trust_root(repo, reviewed_commit), "release_trust_worktree_dirty"
        )
        git(repo, "checkout", "--", POLICY_PATH)
        policy_file.write_bytes(policy_bytes(base, contract, unexpected_staged_value=True))
        git(repo, "add", POLICY_PATH)
        policy_file.write_bytes(git_bytes(repo, "show", f"{reviewed_commit}:{POLICY_PATH}"))
        checks["staged_fixed_path_rejected"] = expect_value_error(
            lambda: load_trust_root(repo, reviewed_commit), "release_trust_worktree_dirty"
        )
        git(repo, "reset", "-q", "HEAD", "--", POLICY_PATH)

        checks["policy_path_key_rejected"] = expect_value_error(
            lambda: validate_policy_bytes(
                policy_bytes(base, contract, dogfood_task_contract_path="elsewhere")
            ),
            "release_policy_vnext_invalid",
        )
        checks["wrong_commit_rejected"] = expect_value_error(
            lambda: load_trust_root(repo, base), "git_object_missing"
        )
        checks["missing_object_rejected"] = expect_value_error(
            lambda: GitObjectSource(repo).read_blob("0" * 40, POLICY_PATH),
            "git_object_missing",
        )

        checks["substituted_base_tree_rejected"] = expect_value_error(
            lambda: TrustRoot.build(
                repo,
                reviewed_commit,
                root.reviewed_tree,
                base,
                root.reviewed_tree,
                root.policy,
                root.dogfood_contract,
                validate_policy_bytes(root.policy.content),
            ),
            "release_trust_base_tree_mismatch",
        )

        original_body = root.body()
        (repo / DOGFOOD_CONTRACT_PATH).write_bytes(contract + b"mutation\n")
        checks["post_load_mutation_rejected"] = (
            root.body() == original_body
            and expect_value_error(
                lambda: load_trust_root(repo, reviewed_commit),
                "release_trust_worktree_dirty",
            )
        )
        git(repo, "checkout", "--", DOGFOOD_CONTRACT_PATH)

        (repo / DOGFOOD_CONTRACT_PATH).write_bytes(contract + b"committed mutation\n")
        mismatched_commit = commit_all(repo, "mismatched contract")
        checks["contract_digest_mismatch_rejected"] = expect_value_error(
            lambda: load_trust_root(repo, mismatched_commit),
            "release_policy_vnext_contract_mismatch",
        )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
