"""Fixed-path vNext release policy loaded only from exact Git objects."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import TypedDict, cast

from .git_objects import GitObjectSource, TrustRoot


POLICY_PATH = "skills/kws-codex-plan-executor/evals/live-migration/release-policy-vnext.json"
DOGFOOD_CONTRACT_PATH = (
    "skills/kws-codex-plan-executor/evals/dogfood/waygent-p0-task1-contract.json"
)

_OID = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KEYS = frozenset(
    {
        "schema_version",
        "trusted_base_commit",
        "dogfood_contract_sha256",
        "release_labels",
        "attempt_ceilings",
    }
)
_LABELS = (
    "critical-path-live verified",
    "full paid-live certification deferred",
)
_CEILINGS = {"critical_matrix": 2, "dogfood": 4, "combined": 6}


class PolicyPayload(TypedDict):
    schema_version: str
    trusted_base_commit: str
    dogfood_contract_sha256: str
    release_labels: list[str]
    attempt_ceilings: dict[str, int]


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def validate_trusted_base_commit(value: object) -> str:
    commit = str(value)
    if _OID.fullmatch(commit) is None:
        raise ValueError("release_policy_vnext_invalid")
    return commit


def validate_policy_bytes(content: bytes) -> PolicyPayload:
    try:
        payload = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("release_policy_vnext_invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != _KEYS
        or content != _canonical_json(payload)
        or payload.get("schema_version") != "cpe.release-policy.vnext"
        or _OID.fullmatch(str(payload.get("trusted_base_commit", ""))) is None
        or _SHA256.fullmatch(str(payload.get("dogfood_contract_sha256", ""))) is None
        or payload.get("release_labels") != list(_LABELS)
        or payload.get("attempt_ceilings") != _CEILINGS
    ):
        raise ValueError("release_policy_vnext_invalid")
    return cast(PolicyPayload, payload)


def _reject_fixed_path_mutation(repository: Path) -> None:
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            POLICY_PATH,
            DOGFOOD_CONTRACT_PATH,
        ],
        cwd=repository,
        capture_output=True,
    )
    if result.returncode or result.stdout:
        raise ValueError("release_trust_worktree_dirty")


def load_trust_root(repository: Path, reviewed_commit: str) -> TrustRoot:
    repo = repository.expanduser().resolve()
    _reject_fixed_path_mutation(repo)
    source = GitObjectSource(repo)
    policy = source.read_blob(reviewed_commit, POLICY_PATH)
    payload = validate_policy_bytes(policy.content)
    contract = source.read_blob(reviewed_commit, DOGFOOD_CONTRACT_PATH)
    trusted_base_commit = validate_trusted_base_commit(payload["trusted_base_commit"])
    trusted_base_tree = source.tree(trusted_base_commit)
    return TrustRoot.build(
        repo,
        reviewed_commit,
        source.tree(reviewed_commit),
        trusted_base_commit,
        trusted_base_tree,
        policy,
        contract,
        payload,
    )
