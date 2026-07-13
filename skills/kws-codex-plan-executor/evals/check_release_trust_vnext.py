#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

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


@contextmanager
def git_environment(**updates: str):
    original = dict(os.environ)
    os.environ.update(updates)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def write(repository: Path, relative: str, content: bytes) -> None:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_object_delta_body(
    repository: Path, predecessor: str, commit: str
) -> dict[str, object]:
    def entries(revision: str) -> dict[bytes, dict[str, str]]:
        raw = git_bytes(
            repository,
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            f"{revision}^{{tree}}",
        )
        result: dict[bytes, dict[str, str]] = {}
        for record in raw.split(b"\0"):
            if not record:
                continue
            metadata, path = record.split(b"\t", 1)
            mode, object_type, oid = metadata.decode("ascii").split(" ")
            result[path] = {"mode": mode, "type": object_type, "oid": oid}
        return result

    old_entries = entries(predecessor)
    new_entries = entries(commit)
    delta_entries = []
    for path in sorted(set(old_entries) | set(new_entries)):
        old_entry = old_entries.get(path)
        new_entry = new_entries.get(path)
        if old_entry != new_entry:
            delta_entries.append(
                {
                    "path": os.fsdecode(path),
                    "old": old_entry,
                    "new": new_entry,
                }
            )
    return {
        "schema_version": "cpe.canonical-object-delta.v1",
        "predecessor_commit": predecessor,
        "commit": commit,
        "entries": delta_entries,
    }


def canonical_object_delta_digest(
    repository: Path, predecessor: str, commit: str
) -> str:
    return sha256_bytes(
        canonical_json(canonical_object_delta_body(repository, predecessor, commit))
    )


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
        expected_patch = canonical_object_delta_digest(repo, base, reviewed_commit)

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

        git(repo, "config", "diff.noprefix", "true")
        noprefix_root = load_trust_root(repo, reviewed_commit)
        git(repo, "config", "--unset", "diff.noprefix")
        checks["diff_noprefix_cannot_change_patch_root"] = (
            noprefix_root.patch_sha256 == root.patch_sha256
            and noprefix_root.trust_root_sha256 == root.trust_root_sha256
        )

        info_attributes = repo / ".git" / "info" / "attributes"
        info_attributes.write_text("* -diff\n", encoding="utf-8")
        git(repo, "config", "diff.external", "/bin/false")
        hostile_diff_root = load_trust_root(repo, reviewed_commit)
        git(repo, "config", "--unset", "diff.external")
        info_attributes.unlink()
        checks["hostile_diff_attributes_cannot_change_patch_root"] = (
            hostile_diff_root.patch_sha256 == root.patch_sha256
            and hostile_diff_root.trust_root_sha256 == root.trust_root_sha256
        )

        with tempfile.TemporaryDirectory(prefix="cpe-object-delta-modes-") as modes_raw:
            modes_repo = Path(modes_raw)
            git(modes_repo, "init", "-q")
            git(modes_repo, "config", "user.name", "CPE Eval")
            git(modes_repo, "config", "user.email", "cpe-eval@example.invalid")
            write(modes_repo, "entry", b"target")
            modes_base = commit_all(modes_repo, "regular blob")

            git(modes_repo, "update-index", "--chmod=+x", "entry")
            git(modes_repo, "commit", "-qm", "executable blob")
            executable_commit = git(modes_repo, "rev-parse", "HEAD")
            git(modes_repo, "reset", "--hard", "-q", modes_base)

            (modes_repo / "entry").unlink()
            os.symlink("target", modes_repo / "entry")
            symlink_commit = commit_all(modes_repo, "symlink blob")
            git(modes_repo, "reset", "--hard", "-q", modes_base)

            git(modes_repo, "rm", "-q", "entry")
            git(
                modes_repo,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{modes_base},entry",
            )
            git(modes_repo, "commit", "-qm", "gitlink")
            gitlink_commit = git(modes_repo, "rev-parse", "HEAD")

            modes_source = GitObjectSource(modes_repo)
            regular_entry = modes_source._tree_entries(modes_base)[b"entry"]
            executable_entry = modes_source._tree_entries(executable_commit)[b"entry"]
            symlink_entry = modes_source._tree_entries(symlink_commit)[b"entry"]
            gitlink_entry = modes_source._tree_entries(gitlink_commit)[b"entry"]
            mode_digests = {
                committed_patch_digest(modes_repo, modes_base, executable_commit),
                committed_patch_digest(modes_repo, modes_base, symlink_commit),
                committed_patch_digest(modes_repo, modes_base, gitlink_commit),
            }
        checks["canonical_object_delta_modes_are_unambiguous"] = (
            regular_entry == {
                "mode": "100644",
                "type": "blob",
                "oid": executable_entry["oid"],
            }
            and executable_entry["mode"] == "100755"
            and executable_entry["type"] == "blob"
            and symlink_entry["mode"] == "120000"
            and symlink_entry["type"] == "blob"
            and symlink_entry["oid"] == regular_entry["oid"]
            and gitlink_entry
            == {"mode": "160000", "type": "commit", "oid": modes_base}
            and len(mode_digests) == 3
        )

        with tempfile.TemporaryDirectory(prefix="cpe-object-delta-shape-") as shape_raw:
            shape_repo = Path(shape_raw)
            git(shape_repo, "init", "-q")
            git(shape_repo, "config", "user.name", "CPE Eval")
            git(shape_repo, "config", "user.email", "cpe-eval@example.invalid")
            write(shape_repo, "dir/z-last", b"kept then changed\n")
            write(shape_repo, "dir/m-delete", b"deleted\n")
            shape_base = commit_all(shape_repo, "shape base")
            (shape_repo / "dir/m-delete").unlink()
            write(shape_repo, "dir/a-add", b"added\n")
            write(shape_repo, "dir/z-last", b"changed\n")
            shape_commit = commit_all(shape_repo, "shape delta")
            shape_body = canonical_object_delta_body(
                shape_repo, shape_base, shape_commit
            )
            shape_entries = shape_body["entries"]
        assert isinstance(shape_entries, list)
        shape_by_path = {entry["path"]: entry for entry in shape_entries}
        checks["canonical_object_delta_order_and_nulls"] = (
            [entry["path"] for entry in shape_entries]
            == sorted(entry["path"] for entry in shape_entries)
            and set(shape_by_path)
            == {"dir/a-add", "dir/m-delete", "dir/z-last"}
            and "dir" not in shape_by_path
            and shape_by_path["dir/a-add"]["old"] is None
            and shape_by_path["dir/a-add"]["new"] is not None
            and shape_by_path["dir/m-delete"]["old"] is not None
            and shape_by_path["dir/m-delete"]["new"] is None
            and shape_by_path["dir/z-last"]["old"] is not None
            and shape_by_path["dir/z-last"]["new"] is not None
        )

        replacement_file = repo / "seed.txt"
        replacement_file.write_bytes(b"replacement tree\n")
        replacement_commit = commit_all(repo, "replacement commit")
        git(repo, "replace", reviewed_commit, replacement_commit)
        replacement_root = load_trust_root(repo, reviewed_commit)
        git(repo, "replace", "-d", reviewed_commit)
        expected_replacement_safe_patch = canonical_object_delta_digest(
            repo, base, reviewed_commit
        )
        checks["git_replacement_cannot_change_patch_root"] = (
            replacement_root.patch_sha256 == expected_replacement_safe_patch
        )
        git(repo, "reset", "--hard", "-q", reviewed_commit)

        with tempfile.TemporaryDirectory(prefix="cpe-release-trust-redirect-") as decoy_raw:
            decoy = Path(decoy_raw)
            fixture(decoy)
            with git_environment(
                GIT_DIR=str(decoy / ".git"),
                GIT_WORK_TREE=str(decoy),
                GIT_INDEX_FILE=str(decoy / ".git" / "index"),
            ):
                try:
                    redirected_root = load_trust_root(repo, reviewed_commit)
                except ValueError:
                    redirected_root = None
        checks["ambient_git_repository_redirect_rejected"] = bool(
            redirected_root is not None and redirected_root.body() == root.body()
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

        git(repo, "update-index", "--skip-worktree", POLICY_PATH)
        policy_file.write_bytes(policy_bytes(base, contract, hidden_by_skip_worktree=True))
        checks["skip_worktree_fixed_path_rejected"] = expect_value_error(
            lambda: load_trust_root(repo, reviewed_commit), "release_trust_worktree_dirty"
        )
        git(repo, "update-index", "--no-skip-worktree", POLICY_PATH)
        git(repo, "checkout", "--", POLICY_PATH)

        git(repo, "update-index", "--assume-unchanged", POLICY_PATH)
        policy_file.write_bytes(policy_bytes(base, contract, hidden_by_assume_unchanged=True))
        checks["assume_unchanged_fixed_path_rejected"] = expect_value_error(
            lambda: load_trust_root(repo, reviewed_commit), "release_trust_worktree_dirty"
        )
        git(repo, "update-index", "--no-assume-unchanged", POLICY_PATH)
        git(repo, "checkout", "--", POLICY_PATH)

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

        substituted_policy = replace(
            root.policy,
            sha256="0" * 64,
            content=root.policy.content + b"substituted\n",
        )
        substituted_payload = dict(validate_policy_bytes(root.policy.content))
        substituted_payload["release_labels"] = ["caller supplied"]
        checks["direct_untrusted_build_rejected"] = (
            expect_value_error(
                lambda: TrustRoot.build(
                    repo,
                    reviewed_commit,
                    root.reviewed_tree,
                    base,
                    root.trusted_base_tree,
                    substituted_policy,
                    root.dogfood_contract,
                    validate_policy_bytes(root.policy.content),
                ),
                "release_trust_policy_mismatch",
            )
            and expect_value_error(
                lambda: TrustRoot.build(
                    repo,
                    reviewed_commit,
                    root.reviewed_tree,
                    base,
                    root.trusted_base_tree,
                    root.policy,
                    root.dogfood_contract,
                    substituted_payload,
                ),
                "release_trust_policy_payload_mismatch",
            )
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
