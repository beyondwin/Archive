"""Binary-safe sealed launch and hidden-oracle bindings for CPE quality v4."""

from __future__ import annotations

import base64
import binascii
import hmac
import re
from typing import Mapping

from .contracts import LiveMigrationContractError, canonical_json, sha256_bytes


LAUNCH_ENVELOPE_SCHEMA = "cpe.launch-envelope.v4"
LAUNCH_ENVELOPE_DOMAIN = b"cpe.launch-envelope.v4\0"
ORACLE_BINDING_SCHEMA = "cpe.oracle-binding.v4"
ORACLE_BINDING_DOMAIN = b"cpe.oracle-binding.v4\0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _domain_digest(domain: bytes, payload: Mapping[str, object]) -> str:
    return sha256_bytes(domain + canonical_json(dict(payload)))


def _encoded(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decoded(value: object, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise LiveMigrationContractError(f"{label} must be non-empty base64")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LiveMigrationContractError(f"{label} is not canonical base64") from exc


def seal_launch_envelope(
    metadata: Mapping[str, object], prompt_bytes: bytes, output_schema_bytes: bytes
) -> dict[str, object]:
    """Seal exact launch bytes with canonical metadata and a domain digest."""

    body = {
        "schema_version": LAUNCH_ENVELOPE_SCHEMA,
        **dict(metadata),
        "prompt_bytes_b64": _encoded(prompt_bytes),
        "output_schema_bytes_b64": _encoded(output_schema_bytes),
        "prompt_sha256": sha256_bytes(prompt_bytes),
        "output_schema_sha256": sha256_bytes(output_schema_bytes),
    }
    digest = _domain_digest(LAUNCH_ENVELOPE_DOMAIN, body)
    return {**body, "envelope_sha256": digest}


def open_launch_envelope(
    artifact: Mapping[str, object], expected_sha256: str
) -> tuple[dict[str, object], bytes, bytes]:
    """Verify and reopen one sealed envelope without reconstructing its bytes."""

    if not isinstance(artifact, Mapping):
        raise LiveMigrationContractError("launch envelope must be an object")
    value = dict(artifact)
    supplied = value.pop("envelope_sha256", None)
    if (
        value.get("schema_version") != LAUNCH_ENVELOPE_SCHEMA
        or not isinstance(expected_sha256, str)
        or _SHA256.fullmatch(expected_sha256) is None
        or not isinstance(supplied, str)
        or not hmac.compare_digest(supplied, expected_sha256)
        or not hmac.compare_digest(
            _domain_digest(LAUNCH_ENVELOPE_DOMAIN, value), expected_sha256
        )
    ):
        raise LiveMigrationContractError("launch envelope digest mismatch")
    prompt = _decoded(value.get("prompt_bytes_b64"), "prompt_bytes_b64")
    schema = _decoded(value.get("output_schema_bytes_b64"), "output_schema_bytes_b64")
    if value.get("prompt_sha256") != sha256_bytes(prompt):
        raise LiveMigrationContractError("launch envelope prompt bytes drifted")
    if value.get("output_schema_sha256") != sha256_bytes(schema):
        raise LiveMigrationContractError("launch envelope schema bytes drifted")
    return {**value, "envelope_sha256": supplied}, prompt, schema


def seal_oracle_binding(binding: Mapping[str, object]) -> dict[str, object]:
    body = {"schema_version": ORACLE_BINDING_SCHEMA, **dict(binding)}
    digest = _domain_digest(ORACLE_BINDING_DOMAIN, body)
    return {**body, "oracle_binding_sha256": digest}


def open_oracle_binding(
    artifact: Mapping[str, object], expected_sha256: str
) -> dict[str, object]:
    if not isinstance(artifact, Mapping):
        raise LiveMigrationContractError("oracle binding must be an object")
    value = dict(artifact)
    supplied = value.pop("oracle_binding_sha256", None)
    if (
        value.get("schema_version") != ORACLE_BINDING_SCHEMA
        or not isinstance(expected_sha256, str)
        or _SHA256.fullmatch(expected_sha256) is None
        or not isinstance(supplied, str)
        or not hmac.compare_digest(supplied, expected_sha256)
        or not hmac.compare_digest(
            _domain_digest(ORACLE_BINDING_DOMAIN, value), expected_sha256
        )
    ):
        raise LiveMigrationContractError("oracle binding digest mismatch")
    return {**value, "oracle_binding_sha256": supplied}
