from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


COMPATIBILITY_EPOCH = "cpe-v4"


def _commit(value: object, error: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(error)
    return value


@dataclass(frozen=True)
class RuntimeIdentity:
    runtime_commit: str
    compatibility_epoch: str

    def __post_init__(self) -> None:
        _commit(self.runtime_commit, "runtime_identity_invalid")
        if self.compatibility_epoch != COMPATIBILITY_EPOCH:
            raise ValueError("runtime_compatibility_epoch_invalid")

    def as_dict(self) -> dict[str, str]:
        return {
            "runtime_commit": self.runtime_commit,
            "compatibility_epoch": self.compatibility_epoch,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "RuntimeIdentity":
        if not isinstance(value, Mapping):
            raise ValueError("runtime_identity_invalid")
        return cls(
            runtime_commit=str(value.get("runtime_commit") or ""),
            compatibility_epoch=str(value.get("compatibility_epoch") or ""),
        )


def validate_runtime_upgrade(
    current: RuntimeIdentity,
    payload: Mapping[str, object],
    *,
    checkpoint_head: str | None,
) -> RuntimeIdentity:
    """Validate a same-run, same-epoch runtime replacement at a safe checkpoint."""

    old_commit = _commit(payload.get("old_runtime_commit"), "runtime_identity_invalid")
    new_commit = _commit(payload.get("new_runtime_commit"), "runtime_identity_invalid")
    if old_commit != current.runtime_commit or new_commit == old_commit:
        raise ValueError("runtime_identity_invalid")
    if payload.get("compatibility_epoch") != COMPATIBILITY_EPOCH:
        raise ValueError("runtime_compatibility_epoch_invalid")
    if payload.get("worktree_clean") is not True:
        raise ValueError("runtime_upgrade_requires_clean_tree")
    if (
        not isinstance(checkpoint_head, str)
        or payload.get("verified_checkpoint") != checkpoint_head
    ):
        raise ValueError("runtime_upgrade_requires_verified_checkpoint")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("runtime_upgrade_reason_missing")
    return RuntimeIdentity(new_commit, COMPATIBILITY_EPOCH)
