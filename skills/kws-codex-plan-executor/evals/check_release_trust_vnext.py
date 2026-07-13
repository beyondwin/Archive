#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
if sys.version_info < (3, 10):
    pinned_python = SKILL_ROOT / ".venv" / "bin" / "python3"
    if pinned_python.is_file() and Path(sys.executable).resolve() != pinned_python.resolve():
        os.execv(str(pinned_python), [str(pinned_python), str(Path(__file__).resolve())])
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
from cpe_runtime.public_result import validate_release_evidence_root
from cpe_runtime.dogfood_v4 import verify_v4_dogfood_run
from cpe import run_v4_dogfood_fixture
from live_migration.compiler import compile_vnext_manifest
from live_migration.contracts import CREDENTIALLED_CALL
from live_migration.ledger import (
    LedgerError,
    append_event,
    create_run,
    finalize_release_generation,
    recover_orphan_release_registration,
    register_release_run,
    replay_release_lineage,
    terminal_release_generation,
)
from live_migration.release_transaction import finalize_v4_release
from live_migration.runner import LiveRunnerError, execute_v4_slots, install_v4_sealed_artifacts


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


def expect_ledger_error(call, expected: str) -> bool:
    try:
        call()
    except LedgerError as exc:
        return str(exc) == expected
    return False


def release_durable_snapshot(root: Path) -> tuple[bytes | None, bytes | None, int]:
    events = root / "quality-release-events.jsonl"
    state = root / "quality-release-state.json"
    generations = root / "release-generations"
    return (
        events.read_bytes() if events.is_file() else None,
        state.read_bytes() if state.is_file() else None,
        len(tuple(generations.iterdir())) if generations.is_dir() else 0,
    )


def strip_generated_trust_and_rebind(root: Path) -> None:
    events_path = root / "quality-release-events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    terminal = events[-1]
    payload = terminal["payload"]
    old_generation = root / "release-generations" / payload["generation_sha256"]
    objects = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in old_generation.iterdir()
    }
    for name in ("manifest.json", "result.json", "dogfood-result.json"):
        objects[name].pop("trust_root", None)
        objects[name].pop("trust_root_sha256", None)
    objects["result.json"]["manifest_sha256"] = sha256_bytes(
        canonical_json(objects["manifest.json"])
    )
    for key, name in (
        ("manifest_sha256", "manifest.json"),
        ("result_sha256", "result.json"),
        ("dogfood_sha256", "dogfood-result.json"),
    ):
        objects["checkpoint.json"][key] = sha256_bytes(canonical_json(objects[name]))
    raw = {name: canonical_json(value) for name, value in objects.items()}
    file_sha256 = {name: sha256_bytes(raw[name]) for name in raw}
    generation_sha256 = sha256_bytes(
        canonical_json(
            {"schema_version": "cpe.release-generation.v4", "file_sha256": file_sha256}
        )
    )
    new_generation = root / "release-generations" / generation_sha256
    new_generation.mkdir()
    for name, content in raw.items():
        (new_generation / name).write_bytes(content)
    shutil.rmtree(old_generation)
    payload.update(
        {
            "generation_sha256": generation_sha256,
            "file_sha256": file_sha256,
            "checkpoint_sha256": file_sha256["checkpoint.json"],
            "dogfood_sha256": file_sha256["dogfood-result.json"],
            "privacy_sha256": file_sha256["privacy-audit.json"],
        }
    )
    body = {key: terminal[key] for key in terminal if key != "event_sha256"}
    terminal["event_sha256"] = sha256_bytes(canonical_json(body))
    events_path.write_bytes(b"".join(canonical_json(event) for event in events))
    replay_release_lineage(root)


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

    repository = SKILL_ROOT.parents[1]
    reviewed_commit = git(repository, "rev-parse", "HEAD")
    trust_root = load_trust_root(repository, reviewed_commit)
    manifest = compile_vnext_manifest(
        reviewed_commit,
        "release-trust-vnext",
        trust_root=trust_root,
        eval_dir=SKILL_ROOT / "evals",
        proof_profile="critical_path_live",
    )
    checks["manifest_cross_binding"] = (
        manifest["trust_root"] == trust_root.body()
        and manifest["trust_root_sha256"] == trust_root.trust_root_sha256
        and all(
            slot.get("trust_root_sha256") == trust_root.trust_root_sha256
            for slot in manifest["slots"]
        )
    )

    with tempfile.TemporaryDirectory(prefix="cpe-release-trust-register-negative-") as raw:
        registration_root = Path(raw)
        mutated = json.loads(json.dumps(manifest))
        mutated["slots"][0]["trust_root_sha256"] = "0" * 64
        mutated["manifest_sha256"] = sha256_bytes(
            canonical_json(
                {key: value for key, value in mutated.items() if key != "manifest_sha256"}
            )
        )
        before = release_durable_snapshot(registration_root)
        rejected = expect_ledger_error(
            lambda: register_release_run(
                registration_root, mutated, expected_trust_root=trust_root
            ),
            "release_trust_root_mismatch",
        )
        checks["registration_rejects_slot_trust_before_durable_write"] = (
            rejected
            and release_durable_snapshot(registration_root) == before
            and not (registration_root / "quality-release-manifests").exists()
        )

    orphan_mutations_rejected = 0
    for mutation in ("body", "slot", "stripped"):
        with tempfile.TemporaryDirectory(
            prefix=f"cpe-release-trust-orphan-{mutation}-"
        ) as raw:
            orphan_root = Path(raw)
            orphan = json.loads(json.dumps(manifest))
            orphan["run_id"] = f"orphan-{mutation}"
            orphan["manifest_sha256"] = sha256_bytes(
                canonical_json(
                    {key: value for key, value in orphan.items() if key != "manifest_sha256"}
                )
            )

            def crash_before_registration(*_args, **_kwargs):
                raise LedgerError("injected_registration_crash")

            expect_ledger_error(
                lambda: register_release_run(
                    orphan_root,
                    orphan,
                    expected_trust_root=trust_root,
                    append_event_fn=crash_before_registration,
                ),
                "injected_registration_crash",
            )
            artifact = next((orphan_root / "quality-release-manifests").iterdir())
            stored = json.loads(artifact.read_text(encoding="utf-8"))
            if mutation == "body":
                stored["trust_root"]["reviewed_tree"] = "0" * 40
                stored["trust_root_sha256"] = sha256_bytes(
                    canonical_json(stored["trust_root"])
                )
                for slot in stored["slots"]:
                    slot["trust_root_sha256"] = stored["trust_root_sha256"]
            else:
                stored["slots"][0]["trust_root_sha256"] = "0" * 64
            if mutation == "stripped":
                stored.pop("trust_root", None)
                stored.pop("trust_root_sha256", None)
                for slot in stored["slots"]:
                    slot.pop("trust_root_sha256", None)
            stored["manifest_sha256"] = sha256_bytes(
                canonical_json(
                    {key: value for key, value in stored.items() if key != "manifest_sha256"}
                )
            )
            artifact.write_bytes(canonical_json(stored))
            before = release_durable_snapshot(orphan_root)
            if expect_ledger_error(
                lambda: recover_orphan_release_registration(
                    orphan_root,
                    str(stored["run_id"]),
                    **(
                        {"repository": repository}
                        if mutation == "stripped"
                        else {"expected_trust_root": trust_root}
                    ),
                ),
                "release_trust_root_mismatch",
            ) and release_durable_snapshot(orphan_root) == before:
                orphan_mutations_rejected += 1
    checks["orphan_trust_mutations_rejected_without_durable_append"] = (
        orphan_mutations_rejected == 3
    )

    with tempfile.TemporaryDirectory(prefix="cpe-release-trust-v4-state-") as raw:
        legacy_manifest = json.loads(json.dumps(manifest))
        legacy_manifest["run_id"] = "legacy-state-shape"
        legacy_manifest.pop("trust_root", None)
        legacy_manifest.pop("trust_root_sha256", None)
        for slot in legacy_manifest["slots"]:
            slot.pop("trust_root_sha256", None)
        legacy_manifest["manifest_sha256"] = sha256_bytes(
            canonical_json(
                {
                    key: value
                    for key, value in legacy_manifest.items()
                    if key != "manifest_sha256"
                }
            )
        )
        legacy_root = Path(raw)
        register_release_run(legacy_root, legacy_manifest)
        legacy_state = replay_release_lineage(legacy_root)
        checks["legacy_v4_projection_omits_new_trust_root_key"] = (
            "trust_root" not in legacy_state
            and "trust_root_sha256" in legacy_state
            and legacy_state["trust_root_sha256"] is None
        )
    with tempfile.TemporaryDirectory(prefix="cpe-release-trust-cli-") as raw:
        output = Path(raw) / "dry-run.json"
        cli = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "evals" / "live_model_runner.py"),
                "dry-run",
                "--matrix",
                "vnext",
                "--proof-profile",
                "critical_path_live",
                "--billing-mode",
                "chatgpt_subscription",
                "--output",
                str(output),
            ],
            cwd=repository,
            text=True,
            capture_output=True,
            check=True,
        )
        cli_payload = json.loads(output.read_text(encoding="utf-8"))
        checks["guarded_cli_vnext_binding"] = (
            cli.returncode == 0
            and cli_payload["trust_root"] == trust_root.body()
            and cli_payload["trust_root_sha256"]
            == trust_root.trust_root_sha256
        )
        help_text = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "evals" / "live_model_runner.py"),
                "start",
                "--help",
            ],
            cwd=repository,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        checks["sentinel_help_names_v4_and_vnext"] = (
            "--sentinel-only" in help_text
            and "--matrix v4 or vnext" in " ".join(help_text.split())
        )

    with tempfile.TemporaryDirectory(prefix="cpe-release-trust-ledger-") as raw:
        release_root = Path(raw)
        register_release_run(release_root, manifest, expected_trust_root=trust_root)
        ledger_state = replay_release_lineage(release_root)
        checks["ledger_cross_binding"] = (
            ledger_state["trust_root_sha256"] == trust_root.trust_root_sha256
            and ledger_state["runs"][0]["trust_root_sha256"]
            == trust_root.trust_root_sha256
        )

        run = create_run(release_root / str(manifest["run_id"]), manifest)
        install_v4_sealed_artifacts(run)
        provider_invocations = 0

        def fake_provider(slot: dict[str, object]):
            nonlocal provider_invocations
            provider_invocations += 1
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

        execute_v4_slots(run, fake_provider, sentinel_only=True, expected_trust_root=trust_root)
        checks["trusted_fake_provider_invoked_once"] = provider_invocations == 1

        mutation_calls = 0

        def mutation_provider(_slot: dict[str, object]):
            nonlocal mutation_calls
            mutation_calls += 1
            raise AssertionError("trust mutation reached provider")

        mutation_cases = {
            "digest": lambda payload: payload.update(
                {"trust_root_sha256": "0" * 64}
            ),
            "body": lambda payload: payload["trust_root"].update(
                {"reviewed_tree": "0" * 40}
            ),
            "slot": lambda payload: payload["slots"][0].update(
                {"trust_root_sha256": "0" * 64}
            ),
        }
        rejected_mutations = 0
        for name, mutate in mutation_cases.items():
            mutated = json.loads(json.dumps(manifest))
            mutate(mutated)
            mutated_body = {
                key: value
                for key, value in mutated.items()
                if key != "manifest_sha256"
            }
            mutated["manifest_sha256"] = sha256_bytes(canonical_json(mutated_body))
            mutated_run = create_run(release_root / f"mutated-{name}", mutated)
            try:
                execute_v4_slots(
                    mutated_run,
                    mutation_provider,
                    sentinel_only=True,
                    expected_trust_root=trust_root,
                )
            except LiveRunnerError as exc:
                rejected_mutations += exc.code == "release_trust_root_mismatch"
        checks["trust_mutations_rejected_before_provider"] = (
            rejected_mutations == len(mutation_cases) and mutation_calls == 0
        )

        append_event(
            run,
            "run_blocked",
            {"code": "test_terminal", "message": "cost-free trust binding check"},
        )
        generation_payloads = {
            name: canonical_json(
                {
                    "name": name,
                    **(
                        {
                            "trust_root_sha256": trust_root.trust_root_sha256,
                        }
                        if name
                        in {"manifest.json", "result.json", "dogfood-result.json"}
                        else {}
                    ),
                }
            )
            for name in (
                "checkpoint.json",
                "manifest.json",
                "result.json",
                "privacy-audit.json",
                "dogfood-result.json",
            )
        }

        terminal_before = release_durable_snapshot(release_root)
        missing_rejected = expect_ledger_error(
            lambda: finalize_release_generation(
                release_root,
                run_id=str(manifest["run_id"]),
                payload_bytes=generation_payloads,
                child_manifest_sha256=str(manifest["manifest_sha256"]),
                aggregate_sha256="1" * 64,
                dogfood_sha256=sha256_bytes(
                    generation_payloads["dogfood-result.json"]
                ),
                checkpoint_sha256=sha256_bytes(
                    generation_payloads["checkpoint.json"]
                ),
                privacy_sha256=sha256_bytes(
                    generation_payloads["privacy-audit.json"]
                ),
                proof_profile="critical_path_live",
            ),
            "release_trust_root_mismatch",
        )
        mismatched_rejected = expect_ledger_error(
            lambda: finalize_release_generation(
                release_root,
                run_id=str(manifest["run_id"]),
                payload_bytes=generation_payloads,
                child_manifest_sha256=str(manifest["manifest_sha256"]),
                aggregate_sha256="1" * 64,
                dogfood_sha256=sha256_bytes(
                    generation_payloads["dogfood-result.json"]
                ),
                checkpoint_sha256=sha256_bytes(
                    generation_payloads["checkpoint.json"]
                ),
                privacy_sha256=sha256_bytes(
                    generation_payloads["privacy-audit.json"]
                ),
                proof_profile="critical_path_live",
                trust_root=replace(trust_root, trust_root_sha256="0" * 64),
            ),
            "release_trust_root_mismatch",
        )
        checks["terminal_missing_or_mismatched_trust_has_no_durable_mutation"] = (
            missing_rejected
            and mismatched_rejected
            and release_durable_snapshot(release_root) == terminal_before
        )

        finalize_release_generation(
            release_root,
            run_id=str(manifest["run_id"]),
            payload_bytes=generation_payloads,
            child_manifest_sha256=str(manifest["manifest_sha256"]),
            aggregate_sha256="1" * 64,
            dogfood_sha256=sha256_bytes(generation_payloads["dogfood-result.json"]),
            checkpoint_sha256=sha256_bytes(generation_payloads["checkpoint.json"]),
            privacy_sha256=sha256_bytes(generation_payloads["privacy-audit.json"]),
            proof_profile="critical_path_live",
            trust_root=trust_root,
        )
        generation, _generation_path = terminal_release_generation(release_root)
        checks["terminal_generation_cross_binding"] = (
            generation["trust_root_sha256"] == trust_root.trust_root_sha256
        )
        checks["validator_rejects_synthetic_generation"] = (
            validate_release_evidence_root(
                release_root,
                reviewed_commit,
                repository,
                expected_trust_root=trust_root,
            )["passed"]
            is False
        )

    with tempfile.TemporaryDirectory(prefix="cpe-release-trust-terminal-") as raw:
        release_root = Path(raw) / "evidence"
        release_root.mkdir()
        terminal_manifest = compile_vnext_manifest(
            reviewed_commit,
            "release-trust-vnext-terminal",
            trust_root=trust_root,
            eval_dir=SKILL_ROOT / "evals",
            proof_profile="critical_path_live",
        )
        terminal_manifest["model_catalog_sha256"] = "c" * 64
        terminal_body = {
            key: value
            for key, value in terminal_manifest.items()
            if key != "manifest_sha256"
        }
        terminal_manifest["manifest_sha256"] = sha256_bytes(
            canonical_json(terminal_body)
        )
        register_release_run(
            release_root,
            terminal_manifest,
            expected_trust_root=trust_root,
        )
        terminal_run = create_run(
            release_root / str(terminal_manifest["run_id"]), terminal_manifest
        )
        install_v4_sealed_artifacts(terminal_run)
        terminal_calls = 0

        def terminal_provider(slot: dict[str, object]):
            nonlocal terminal_calls
            terminal_calls += 1
            blocked = slot["case_id"] == "security/migration block"
            return {"fake-provider.json": canonical_json({"fake": True})}, {
                "schema_version": "cpe-quality-result.v4",
                "run_id": terminal_manifest["run_id"],
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

        executed = execute_v4_slots(
            terminal_run,
            terminal_provider,
            expected_trust_root=trust_root,
        )
        append_event(terminal_run, "run_completed", {"completed_slots": 9})
        with git_environment(
            CPE_SUPERPOWERS_ROOT=str(
                SKILL_ROOT / "evals" / "fixtures" / "superpowers-capabilities"
            )
        ):
            dogfood = run_v4_dogfood_fixture(
                SKILL_ROOT
                / "evals"
                / "parser-fixtures"
                / "22-v4-dogfood-plan.md",
                Path(raw) / "dogfood-run",
            )
        dogfood_manifest = json.loads(
            (Path(dogfood["run_dir"]) / "run_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        dogfood_clone = Path(str(dogfood_manifest["workspace_ref"]))
        clone_root = load_trust_root(dogfood_clone, reviewed_commit)
        checks["dogfood_rejects_clone_repository_identity_relabel"] = expect_value_error(
            lambda: verify_v4_dogfood_run(
                Path(dogfood["run_dir"]),
                expected_implementation_commit=reviewed_commit,
                expected_implementation_tree=str(terminal_manifest["implementation_tree"]),
                expected_task_contract_sha256=trust_root.dogfood_contract.sha256,
                expected_trust_root_sha256=clone_root.trust_root_sha256,
                expected_trust_root=clone_root,
                trust_repository=dogfood_clone,
            ),
            "dogfood_trust_root_invalid",
        )
        finalized = finalize_v4_release(
            evidence_root=release_root,
            run_dir=terminal_run.run_dir,
            dogfood_run_dir=Path(dogfood["run_dir"]),
            repository=repository,
        )
        generation, _generation_path = terminal_release_generation(release_root)
        validation = validate_release_evidence_root(
            release_root,
            reviewed_commit,
            repository,
            expected_trust_root=trust_root,
        )
        generation_manifest = json.loads(
            (_generation_path / "manifest.json").read_text(encoding="utf-8")
        )
        generation_dogfood = json.loads(
            (_generation_path / "dogfood-result.json").read_text(encoding="utf-8")
        )
        retained_checkpoint = json.loads(
            (
                release_root
                / "dogfood"
                / str(generation_dogfood["retained_run_id"])
                / "checkpoint.json"
            ).read_text(encoding="utf-8")
        )
        checks["dogfood_retains_reconstructed_trust_body_and_digest"] = (
            generation_manifest.get("trust_root_sha256")
            == trust_root.trust_root_sha256
            and generation_dogfood.get("trust_root_sha256")
            == trust_root.trust_root_sha256
            and retained_checkpoint.get("trust_root") == trust_root.body()
            and retained_checkpoint.get("trust_root_sha256")
            == trust_root.trust_root_sha256
            and retained_checkpoint.get("result", {}).get("trust_root")
            == trust_root.body()
        )

        registered_path = (
            release_root
            / "quality-release-manifests"
            / f"{terminal_manifest['run_id']}.json"
        )
        public_mutations_rejected = 0
        for target_path in (registered_path, terminal_run.run_dir / "manifest.json"):
            original = target_path.read_bytes()
            mutated = json.loads(original)
            mutated["trust_root"]["reviewed_tree"] = "0" * 40
            target_path.write_bytes(canonical_json(mutated))
            try:
                rejected = validate_release_evidence_root(
                    release_root,
                    reviewed_commit,
                    repository,
                    expected_trust_root=trust_root,
                )["passed"] is False
            finally:
                target_path.write_bytes(original)
            public_mutations_rejected += rejected
        checks["public_validator_rejects_registered_and_child_body_rewrite"] = (
            public_mutations_rejected == 2
        )
        downgraded_root = Path(raw) / "downgraded-evidence"
        shutil.copytree(release_root, downgraded_root)
        strip_generated_trust_and_rebind(downgraded_root)
        checks["public_validator_rejects_generated_trust_downgrade"] = (
            validate_release_evidence_root(
                downgraded_root,
                reviewed_commit,
                repository,
            )["passed"]
            is False
        )
        checks["terminal_release_cross_binding"] = (
            executed["provider_invocations"] == 2
            and terminal_calls == 2
            and finalized["generation_sha256"] == generation["generation_sha256"]
            and generation["trust_root_sha256"] == trust_root.trust_root_sha256
            and validation.get("trust_root_sha256") == trust_root.trust_root_sha256
            and validation["passed"] is True
        )

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
