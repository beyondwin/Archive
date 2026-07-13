"""Immutable release trust bindings sourced from exact Git objects."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping, TypedDict

from .git_delta import committed_patch_digest as _measured_patch_digest


_OID = re.compile(r"^[0-9a-f]{40}$")


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _git(repository: Path, *args: str, text: bool = False) -> bytes | str:
    environment = dict(os.environ)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=text,
        )
    except OSError as exc:
        raise ValueError("git_object_missing") from exc
    if result.returncode:
        raise ValueError("git_object_missing")
    return result.stdout.strip() if text else result.stdout


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

    repository = repository.expanduser().resolve()
    common = str(_git(repository, "rev-parse", "--git-common-dir", text=True))
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = repository / common_path
    return "git-common-dir:" + str(common_path.resolve())


def committed_patch_digest(repository: Path, predecessor: str, commit: str) -> str:
    """Return only the canonical digest for one exact committed delta."""

    _files, digest = _measured_patch_digest(repository, predecessor, commit)
    return digest


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
        self.repository = repository.expanduser().resolve()
        _git(self.repository, "rev-parse", "--git-dir")

    def _commit(self, commit: str) -> str:
        if _OID.fullmatch(commit) is None:
            raise ValueError("git_object_missing")
        if _git(self.repository, "cat-file", "-t", commit, text=True) != "commit":
            raise ValueError("git_object_missing")
        return commit

    def tree(self, commit: str) -> str:
        commit = self._commit(commit)
        tree = str(_git(self.repository, "rev-parse", f"{commit}^{{tree}}", text=True))
        if _OID.fullmatch(tree) is None:
            raise ValueError("git_object_missing")
        return tree

    def read_blob(self, commit: str, path: str) -> GitBlob:
        commit = self._commit(commit)
        path = _safe_path(path)
        oid = str(_git(self.repository, "rev-parse", f"{commit}:{path}", text=True))
        if _OID.fullmatch(oid) is None or _git(
            self.repository, "cat-file", "-t", oid, text=True
        ) != "blob":
            raise ValueError("git_object_missing")
        content = bytes(_git(self.repository, "cat-file", "blob", oid))
        return GitBlob(path, oid, hashlib.sha256(content).hexdigest(), content)


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
        source = GitObjectSource(repository)
        if source.tree(reviewed_commit) != reviewed_tree:
            raise ValueError("release_trust_reviewed_tree_mismatch")
        if source.tree(trusted_base_commit) != trusted_base_tree:
            raise ValueError("release_trust_base_tree_mismatch")
        if trusted_base_commit == reviewed_commit:
            raise ValueError("release_trust_base_invalid")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", trusted_base_commit, reviewed_commit],
            cwd=source.repository,
            env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
            capture_output=True,
        )
        if ancestor.returncode:
            raise ValueError("release_trust_base_invalid")
        if dogfood_contract.sha256 != payload["dogfood_contract_sha256"]:
            raise ValueError("release_policy_vnext_contract_mismatch")
        patch_sha256 = committed_patch_digest(
            source.repository, trusted_base_commit, reviewed_commit
        )
        labels = tuple(payload["release_labels"])  # type: ignore[arg-type]
        ceilings = MappingProxyType(dict(payload["attempt_ceilings"]))  # type: ignore[arg-type]
        draft = cls(
            canonical_repository_identity(source.repository),
            reviewed_commit,
            reviewed_tree,
            trusted_base_commit,
            trusted_base_tree,
            patch_sha256,
            policy,
            dogfood_contract,
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
