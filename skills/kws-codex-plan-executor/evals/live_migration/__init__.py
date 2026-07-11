"""Deterministic building blocks for the CPE v3 subscription live matrix."""

from .compiler import compile_manifest, load_registry
from .contracts import (
    CaseRef,
    LiveMigrationContractError,
    SlotKey,
    Treatment,
    canonical_json,
    sha256_bytes,
)

__all__ = [
    "CaseRef",
    "LiveMigrationContractError",
    "SlotKey",
    "Treatment",
    "canonical_json",
    "compile_manifest",
    "load_registry",
    "sha256_bytes",
]
