"""Immutable release trust bindings sourced from exact Git objects."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping, TypedDict

_OID = re.compile(r"^[0-9a-f]{40}$")
_MODE = re.compile(r"^[0-7]{6}$")


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _discover_repository(repository: Path) -> tuple[Path, Path]:
    requested = repository.expanduser().resolve()
    try:
        root_result = subprocess.run(
            ["git", "-C", str(requested), "rev-parse", "--show-toplevel"],
            env=_git_environment(),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ValueError("git_object_missing") from exc
    if root_result.returncode:
        raise ValueError("git_object_missing")
    root = Path(root_result.stdout.strip()).resolve()
    try:
        git_dir_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--absolute-git-dir"],
            env=_git_environment(),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ValueError("git_object_missing") from exc
    if git_dir_result.returncode:
        raise ValueError("git_object_missing")
    return root, Path(git_dir_result.stdout.strip()).resolve()


def _safe_path(path: str) -> str:
    value = PurePosixPath(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise ValueError("git_object_path_invalid")
    canonical = value.as_posix()
    if canonical != path or any(part in ("", ".") for part in value.parts):
        raise ValueError("git_object_path_invalid")
    return canonical


def canonical_repository_identity(repository: Path) -> str:
    """Identify all worktrees sharing one canonical Git object database."""

    return _canonical_repository_identity(GitObjectSource(repository))


def _canonical_repository_identity(source: "GitObjectSource") -> str:
    common = str(source._git("rev-parse", "--git-common-dir", text=True))
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = source.repository / common_path
    return "git-common-dir:" + str(common_path.resolve())


def committed_patch_digest(repository: Path, predecessor: str, commit: str) -> str:
    """Return only the canonical digest for one exact committed delta."""

    return GitObjectSource(repository).patch_digest(predecessor, commit)


@dataclass(frozen=True)
class GitBlob:
    path: str
    blob_oid: str
    sha256: str
    content: bytes


class GitBlobBody(TypedDict):
    path: str
    blob_oid: str
    sha256: str


class TrustRootBody(TypedDict):
    repository_identity: str
    reviewed_commit: str
    reviewed_tree: str
    trusted_base_commit: str
    trusted_base_tree: str
    patch_sha256: str
    policy: GitBlobBody
    dogfood_contract: GitBlobBody
    release_labels: list[str]
    attempt_ceilings: dict[str, int]


class GitObjectSource:
    """Read repository-relative blobs from one explicitly named commit."""

    def __init__(self, repository: Path):
        self.repository, self.git_dir = _discover_repository(repository)
        self._environment = _git_environment()

    def _result(self, *args: str, text: bool = False) -> subprocess.CompletedProcess:
        argv = [
            "git",
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.repository}",
            *args,
        ]
        try:
            return subprocess.run(
                argv,
                cwd=self.repository,
                env=self._environment,
                capture_output=True,
                text=text,
            )
        except OSError as exc:
            raise ValueError("git_object_missing") from exc

    def _git(self, *args: str, text: bool = False) -> bytes | str:
        result = self._result(*args, text=text)
        if result.returncode:
            raise ValueError("git_object_missing")
        return result.stdout.strip() if text else result.stdout

    def _commit(self, commit: str) -> str:
        if _OID.fullmatch(commit) is None:
            raise ValueError("git_object_missing")
        if self._git("cat-file", "-t", commit, text=True) != "commit":
            raise ValueError("git_object_missing")
        return commit

    def tree(self, commit: str) -> str:
        commit = self._commit(commit)
        tree = str(self._git("rev-parse", f"{commit}^{{tree}}", text=True))
        if _OID.fullmatch(tree) is None:
            raise ValueError("git_object_missing")
        return tree

    def read_blob(self, commit: str, path: str) -> GitBlob:
        commit = self._commit(commit)
        path = _safe_path(path)
        oid = str(self._git("rev-parse", f"{commit}:{path}", text=True))
        if _OID.fullmatch(oid) is None or self._git(
            "cat-file", "-t", oid, text=True
        ) != "blob":
            raise ValueError("git_object_missing")
        content = bytes(self._git("cat-file", "blob", oid))
        return GitBlob(path, oid, hashlib.sha256(content).hexdigest(), content)

    def is_ancestor(self, predecessor: str, commit: str) -> bool:
        predecessor = self._commit(predecessor)
        commit = self._commit(commit)
        result = self._result("merge-base", "--is-ancestor", predecessor, commit)
        if result.returncode not in (0, 1):
            raise ValueError("git_object_missing")
        return result.returncode == 0

    def patch_digest(self, predecessor: str, commit: str) -> str:
        predecessor = self._commit(predecessor)
        commit = self._commit(commit)
        old_entries = self._tree_entries(predecessor)
        new_entries = self._tree_entries(commit)
        entries: list[dict[str, object]] = []
        for raw_path in sorted(set(old_entries) | set(new_entries)):
            old_entry = old_entries.get(raw_path)
            new_entry = new_entries.get(raw_path)
            if old_entry == new_entry:
                continue
            entries.append(
                {
                    "path": os.fsdecode(raw_path),
                    "old": old_entry,
                    "new": new_entry,
                }
            )
        body = {
            "schema_version": "cpe.canonical-object-delta.v1",
            "predecessor_commit": predecessor,
            "commit": commit,
            "entries": entries,
        }
        return hashlib.sha256(_canonical_json(body)).hexdigest()

    def _tree_entries(self, commit: str) -> dict[bytes, dict[str, str]]:
        tree = self.tree(commit)
        raw = bytes(self._git("ls-tree", "-r", "-z", "--full-tree", tree))
        entries: dict[bytes, dict[str, str]] = {}
        for record in raw.split(b"\0"):
            if not record:
                continue
            try:
                metadata, path = record.split(b"\t", 1)
                mode_raw, type_raw, oid_raw = metadata.split(b" ")
                mode = mode_raw.decode("ascii")
                object_type = type_raw.decode("ascii")
                oid = oid_raw.decode("ascii")
            except (ValueError, UnicodeError) as exc:
                raise ValueError("git_object_missing") from exc
            if (
                not path
                or path in entries
                or _MODE.fullmatch(mode) is None
                or object_type not in {"blob", "tree", "commit"}
                or _OID.fullmatch(oid) is None
            ):
                raise ValueError("git_object_missing")
            entries[path] = {"mode": mode, "type": object_type, "oid": oid}
        return entries

    def reject_fixed_path_mutation(
        self, reviewed_commit: str, blobs: tuple[GitBlob, ...]
    ) -> None:
        paths = tuple(blob.path for blob in blobs)
        try:
            status = bytes(
                self._git(
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    "--",
                    *paths,
                )
            )
            flags = bytes(self._git("ls-files", "-v", "-z", "--", *paths))
            stages = bytes(self._git("ls-files", "--stage", "-z", "--", *paths))
        except ValueError as exc:
            raise ValueError("release_trust_worktree_dirty") from exc
        if status:
            raise ValueError("release_trust_worktree_dirty")

        flag_records: dict[str, str] = {}
        for record in flags.split(b"\0"):
            if not record:
                continue
            if len(record) < 3 or record[1:2] != b" ":
                raise ValueError("release_trust_worktree_dirty")
            flag_records[os.fsdecode(record[2:])] = chr(record[0])
        if set(flag_records) != set(paths) or any(
            flag_records[path] != "H" for path in paths
        ):
            raise ValueError("release_trust_worktree_dirty")

        stage_records: dict[str, tuple[str, str]] = {}
        for record in stages.split(b"\0"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                _mode, oid, stage = metadata.decode("ascii").split(" ")
            except (ValueError, UnicodeError) as exc:
                raise ValueError("release_trust_worktree_dirty") from exc
            path = os.fsdecode(raw_path)
            if path in stage_records:
                raise ValueError("release_trust_worktree_dirty")
            stage_records[path] = (oid, stage)

        for blob in blobs:
            if self.read_blob(reviewed_commit, blob.path) != blob:
                raise ValueError("release_trust_worktree_dirty")
            if stage_records.get(blob.path) != (blob.blob_oid, "0"):
                raise ValueError("release_trust_worktree_dirty")
            path = self.repository.joinpath(*PurePosixPath(blob.path).parts)
            try:
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise ValueError("release_trust_worktree_dirty")
                    with os.fdopen(descriptor, "rb", closefd=False) as handle:
                        worktree_content = handle.read()
                finally:
                    os.close(descriptor)
            except OSError as exc:
                raise ValueError("release_trust_worktree_dirty") from exc
            if worktree_content != blob.content:
                raise ValueError("release_trust_worktree_dirty")


@dataclass(frozen=True)
class TrustRoot:
    repository_identity: str
    reviewed_commit: str
    reviewed_tree: str
    trusted_base_commit: str
    trusted_base_tree: str
    patch_sha256: str
    policy: GitBlob
    dogfood_contract: GitBlob
    release_labels: tuple[str, ...]
    attempt_ceilings: Mapping[str, int]
    trust_root_sha256: str

    def body(self) -> TrustRootBody:
        return {
            "repository_identity": self.repository_identity,
            "reviewed_commit": self.reviewed_commit,
            "reviewed_tree": self.reviewed_tree,
            "trusted_base_commit": self.trusted_base_commit,
            "trusted_base_tree": self.trusted_base_tree,
            "patch_sha256": self.patch_sha256,
            "policy": {
                "path": self.policy.path,
                "blob_oid": self.policy.blob_oid,
                "sha256": self.policy.sha256,
            },
            "dogfood_contract": {
                "path": self.dogfood_contract.path,
                "blob_oid": self.dogfood_contract.blob_oid,
                "sha256": self.dogfood_contract.sha256,
            },
            "release_labels": list(self.release_labels),
            "attempt_ceilings": dict(self.attempt_ceilings),
        }

    @classmethod
    def build(
        cls,
        repository: Path,
        reviewed_commit: str,
        reviewed_tree: str,
        trusted_base_commit: str,
        trusted_base_tree: str,
        policy: GitBlob,
        dogfood_contract: GitBlob,
        payload: Mapping[str, object],
    ) -> "TrustRoot":
        from .release_policy_vnext import (
            DOGFOOD_CONTRACT_PATH,
            POLICY_PATH,
            validate_policy_bytes,
            validate_trusted_base_commit,
        )

        source = GitObjectSource(repository)
        exact_policy = source.read_blob(reviewed_commit, POLICY_PATH)
        if policy != exact_policy:
            raise ValueError("release_trust_policy_mismatch")
        exact_contract = source.read_blob(reviewed_commit, DOGFOOD_CONTRACT_PATH)
        if dogfood_contract != exact_contract:
            raise ValueError("release_trust_contract_mismatch")
        validated_payload = validate_policy_bytes(exact_policy.content)
        if dict(payload) != dict(validated_payload):
            raise ValueError("release_trust_policy_payload_mismatch")
        exact_base_commit = validate_trusted_base_commit(
            validated_payload["trusted_base_commit"]
        )
        if trusted_base_commit != exact_base_commit:
            raise ValueError("release_trust_base_invalid")
        exact_reviewed_tree = source.tree(reviewed_commit)
        if exact_reviewed_tree != reviewed_tree:
            raise ValueError("release_trust_reviewed_tree_mismatch")
        exact_base_tree = source.tree(exact_base_commit)
        if exact_base_tree != trusted_base_tree:
            raise ValueError("release_trust_base_tree_mismatch")
        if trusted_base_commit == reviewed_commit:
            raise ValueError("release_trust_base_invalid")
        if not source.is_ancestor(trusted_base_commit, reviewed_commit):
            raise ValueError("release_trust_base_invalid")
        if exact_contract.sha256 != validated_payload["dogfood_contract_sha256"]:
            raise ValueError("release_policy_vnext_contract_mismatch")
        source.reject_fixed_path_mutation(
            reviewed_commit, (exact_policy, exact_contract)
        )
        patch_sha256 = source.patch_digest(trusted_base_commit, reviewed_commit)
        labels = tuple(validated_payload["release_labels"])
        ceilings = MappingProxyType(dict(validated_payload["attempt_ceilings"]))
        draft = cls(
            _canonical_repository_identity(source),
            reviewed_commit,
            exact_reviewed_tree,
            trusted_base_commit,
            exact_base_tree,
            patch_sha256,
            exact_policy,
            exact_contract,
            labels,
            ceilings,
            "",
        )
        return cls(
            **{
                **draft.__dict__,
                "trust_root_sha256": hashlib.sha256(_canonical_json(draft.body())).hexdigest(),
            }
        )
