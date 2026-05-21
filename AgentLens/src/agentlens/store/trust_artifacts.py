"""Atomic helpers for AgentRunway Trust Console artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentlens.schema.validate import SchemaError, validate_doc

from .writer import WriteError, atomic_write_json


class TrustArtifactError(ValueError):
    """Raised when a trust artifact is missing or malformed."""


def _artifacts_dir(run_dir: Path) -> Path:
    return Path(run_dir) / "artifacts"


def write_projection(run_dir: Path, projection: dict[str, Any]) -> Path:
    path = _artifacts_dir(run_dir) / "agentrunway_projection.json"
    atomic_write_json(path, projection, redact=False)
    return path


def write_trust_report(run_dir: Path, report: dict[str, Any]) -> Path:
    path = _artifacts_dir(run_dir) / "trust_report.json"
    atomic_write_json(path, report, redact=False)
    return path


def read_trust_report(run_dir: Path) -> dict[str, Any]:
    path = _artifacts_dir(run_dir) / "trust_report.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_doc(payload, schema_name="trust_report")
    except (OSError, json.JSONDecodeError, SchemaError, WriteError) as exc:
        raise TrustArtifactError(f"invalid trust report at {path}: {exc}") from exc
    return payload


__all__ = [
    "TrustArtifactError",
    "read_trust_report",
    "write_projection",
    "write_trust_report",
]
