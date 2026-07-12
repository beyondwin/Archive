"""Tracked trust anchors for the CPE v4 release transaction."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Mapping

from .git_delta import committed_patch_digest


POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "live-migration"
    / "release-policy-v4.json"
)
_OID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_POLICY_KEYS = frozenset(
    {
        "schema_version",
        "trusted_base_commit",
        "dogfood_task_contract_path",
        "dogfood_task_contract_sha256",
        "critical_matrix_attempt_limit",
        "dogfood_attempt_limit",
        "combined_attempt_limit",
        "critical_path_live_label",
        "full_paid_matrix_deferred_label",
    }
)


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository, text=True, capture_output=True
    )
    if result.returncode:
        raise ValueError("release_policy_git_invalid")
    return result.stdout.strip()


def _canonical(raw: object) -> bytes:
    return (json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_release_policy(
    path: Path | None = None, *, repository: Path | None = None
) -> dict[str, object]:
    """Load one canonical policy and prove both it and its contract are tracked."""

    policy_path = (path or POLICY_PATH).expanduser().resolve()
    repo = (
        repository.expanduser().resolve()
        if repository is not None
        else Path(_git(policy_path.parent, "rev-parse", "--show-toplevel")).resolve()
    )
    try:
        relative_policy = policy_path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise ValueError("release_policy_untracked") from exc
    if _git(repo, "ls-files", "--error-unmatch", relative_policy) != relative_policy:
        raise ValueError("release_policy_untracked")
    raw = policy_path.read_bytes()
    try:
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("release_policy_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != _POLICY_KEYS or raw != _canonical(payload):
        raise ValueError("release_policy_invalid")
    if (
        payload.get("schema_version") != "cpe.release-policy.v4"
        or _OID.fullmatch(str(payload.get("trusted_base_commit", ""))) is None
        or _SHA256.fullmatch(str(payload.get("dogfood_task_contract_sha256", ""))) is None
        or payload.get("critical_matrix_attempt_limit") != 2
        or payload.get("dogfood_attempt_limit") != 4
        or payload.get("combined_attempt_limit") != 6
        or payload.get("critical_path_live_label") != "critical-path-live verified"
        or payload.get("full_paid_matrix_deferred_label")
        != "full paid-live certification deferred"
    ):
        raise ValueError("release_policy_invalid")
    contract_path = (repo / str(payload["dogfood_task_contract_path"])).resolve()
    try:
        relative_contract = contract_path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise ValueError("release_policy_contract_untracked") from exc
    if _git(repo, "ls-files", "--error-unmatch", relative_contract) != relative_contract:
        raise ValueError("release_policy_contract_untracked")
    contract_bytes = contract_path.read_bytes()
    if hashlib.sha256(contract_bytes).hexdigest() != payload["dogfood_task_contract_sha256"]:
        raise ValueError("release_policy_contract_drift")
    return {
        **payload,
        "policy_sha256": hashlib.sha256(raw).hexdigest(),
        "policy_path": str(policy_path),
        "dogfood_task_contract_absolute_path": str(contract_path),
    }


def validate_release_checkpoint(
    repository: Path,
    implementation_commit: str,
    *,
    implementation_tree: str | None = None,
    implementation_patch_sha256: str | None = None,
    policy: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Bind one implementation to the tracked base and exact canonical patch."""

    repo = repository.expanduser().resolve()
    loaded = dict(policy or load_release_policy())
    base = str(loaded.get("trusted_base_commit") or "")
    commit = str(implementation_commit)
    if _OID.fullmatch(base) is None or _OID.fullmatch(commit) is None or base == commit:
        raise ValueError("release_checkpoint_invalid")
    if _git(repo, "cat-file", "-t", base) != "commit" or _git(repo, "cat-file", "-t", commit) != "commit":
        raise ValueError("release_checkpoint_invalid")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", base, commit], cwd=repo)
    if ancestor.returncode or _git(repo, "merge-base", base, commit) != base:
        raise ValueError("release_checkpoint_nonancestor")
    tree = _git(repo, "rev-parse", f"{commit}^{{tree}}")
    _files, patch = committed_patch_digest(repo, base, commit)
    if implementation_tree is not None and implementation_tree != tree:
        raise ValueError("release_checkpoint_tree_mismatch")
    if implementation_patch_sha256 is not None and implementation_patch_sha256 != patch:
        raise ValueError("release_checkpoint_patch_mismatch")
    return {
        "implementation_base_commit": base,
        "implementation_commit": commit,
        "implementation_tree": tree,
        "implementation_patch_sha256": patch,
        "release_policy_sha256": str(loaded.get("policy_sha256") or ""),
    }
