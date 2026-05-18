"""Tests for AgentLens M0 JSON schemas and validate.py.

Covers S1.5, S1.5.1–S1.5.6, S1.6.11.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from agentlens.schema import (
    EventLineError,
    SchemaError,
    load_schema,
    validate_doc,
    validate_event_line,
)

SCHEMA_NAMES = ["run", "event", "final", "eval", "manifest"]

REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_DIR = REPO_ROOT / "tests" / "fixtures" / "schemas" / "valid"
INVALID_DIR = REPO_ROOT / "tests" / "fixtures" / "schemas" / "invalid"
SCHEMA_DIR = REPO_ROOT / "src" / "agentlens" / "schema" / "jsonschema"


def _load_fixture(directory: Path, name: str) -> dict:
    with (directory / f"{name}.json").open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Schema loading & well-formedness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_load_schema_returns_dict(name: str) -> None:
    schema = load_schema(name)
    assert isinstance(schema, dict)
    assert "$schema" in schema
    assert schema["$schema"].startswith("https://json-schema.org/draft/2020-12")


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_each_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = load_schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_each_schema_has_version_comment(name: str) -> None:
    schema = load_schema(name)
    assert "$comment" in schema
    assert "v1 is locked" in schema["$comment"]


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_each_schema_disallows_additional_properties(name: str) -> None:
    schema = load_schema(name)
    assert schema.get("additionalProperties") is False


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_each_schema_const_namespace(name: str) -> None:
    schema = load_schema(name)
    props = schema.get("properties", {})
    assert props.get("schema", {}).get("const") == f"agentlens.{name}.v1"


# ---------------------------------------------------------------------------
# Valid fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_valid_fixture_passes(name: str) -> None:
    doc = _load_fixture(VALID_DIR, name)
    validate_doc(doc)  # should not raise


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_valid_fixture_passes_with_explicit_schema_name(name: str) -> None:
    doc = _load_fixture(VALID_DIR, name)
    validate_doc(doc, schema_name=name)  # should not raise


# ---------------------------------------------------------------------------
# Invalid fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_invalid_fixture_raises_schema_error(name: str) -> None:
    doc = _load_fixture(INVALID_DIR, name)
    with pytest.raises(SchemaError) as exc_info:
        validate_doc(doc)
    assert isinstance(exc_info.value.errors, list)
    assert len(exc_info.value.errors) >= 1


# ---------------------------------------------------------------------------
# additionalProperties enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_additional_property_rejected(name: str) -> None:
    doc = _load_fixture(VALID_DIR, name)
    doc["__unexpected_key__"] = "nope"
    with pytest.raises(SchemaError):
        validate_doc(doc)


# ---------------------------------------------------------------------------
# Timestamp regex enforcement
# ---------------------------------------------------------------------------


def test_timestamp_regex_rejects_non_utc_run() -> None:
    doc = _load_fixture(VALID_DIR, "run")
    doc["started_at"] = "2026-05-18 21:13:28"  # missing T and Z
    with pytest.raises(SchemaError):
        validate_doc(doc)


def test_timestamp_regex_rejects_offset() -> None:
    doc = _load_fixture(VALID_DIR, "event")
    doc["ts"] = "2026-05-18T21:13:29+09:00"
    with pytest.raises(SchemaError):
        validate_doc(doc)


# ---------------------------------------------------------------------------
# sha256 regex enforcement
# ---------------------------------------------------------------------------


def test_sha256_regex_rejects_non_sha256_in_manifest() -> None:
    doc = _load_fixture(VALID_DIR, "manifest")
    doc["files"][0]["sha256"] = "sha256:zzz"
    with pytest.raises(SchemaError):
        validate_doc(doc)


def test_sha256_regex_rejects_missing_prefix_in_run() -> None:
    doc = _load_fixture(VALID_DIR, "run")
    doc["workspace"]["root_hash"] = (
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )
    with pytest.raises(SchemaError):
        validate_doc(doc)


# ---------------------------------------------------------------------------
# Enum constraints
# ---------------------------------------------------------------------------


def test_agent_name_enum_rejects_invalid() -> None:
    doc = _load_fixture(VALID_DIR, "run")
    doc["agent"]["name"] = "bogus_agent"
    with pytest.raises(SchemaError):
        validate_doc(doc)


def test_event_type_enum_rejects_invalid() -> None:
    doc = _load_fixture(VALID_DIR, "event")
    doc["type"] = "not.a.real.event"
    with pytest.raises(SchemaError):
        validate_doc(doc)


def test_final_agent_outcome_enum_rejects_invalid() -> None:
    doc = _load_fixture(VALID_DIR, "final")
    doc["agent_outcome"] = "maybe"
    with pytest.raises(SchemaError):
        validate_doc(doc)


def test_manifest_sealed_phase_enum_includes_recording_incomplete() -> None:
    doc = _load_fixture(VALID_DIR, "manifest")
    doc["sealed_phase"] = "recording_incomplete"
    validate_doc(doc)  # should pass


def test_manifest_sealed_phase_rejects_unknown() -> None:
    doc = _load_fixture(VALID_DIR, "manifest")
    doc["sealed_phase"] = "early"
    with pytest.raises(SchemaError):
        validate_doc(doc)


def test_eval_failure_category_enum_rejects_unknown() -> None:
    doc = _load_fixture(VALID_DIR, "eval")
    doc["failures"] = [
        {
            "category": "NOT_REAL",
            "severity": "low",
            "source": "evaluator",
            "blame_scope": "agent",
            "recoverability": "informational",
            "confidence": 0.5,
            "summary": "Hi",
            "evidence": [],
        }
    ]
    with pytest.raises(SchemaError):
        validate_doc(doc)


def test_eval_failure_category_enum_accepts_known() -> None:
    doc = _load_fixture(VALID_DIR, "eval")
    doc["failures"] = [
        {
            "category": "MISSING_FINAL",
            "severity": "high",
            "source": "evaluator",
            "blame_scope": "agent",
            "recoverability": "rerun_or_fix",
            "confidence": 0.95,
            "summary": "no final",
            "evidence": ["final.json missing"],
        }
    ]
    validate_doc(doc)


# ---------------------------------------------------------------------------
# Schema const enforcement
# ---------------------------------------------------------------------------


def test_schema_const_rejects_wrong_namespace() -> None:
    doc = _load_fixture(VALID_DIR, "run")
    doc["schema"] = "agentlens.run.v2"
    with pytest.raises(SchemaError):
        validate_doc(doc)


# ---------------------------------------------------------------------------
# Schema inference
# ---------------------------------------------------------------------------


def test_validate_doc_infers_schema_from_field() -> None:
    doc = _load_fixture(VALID_DIR, "event")
    validate_doc(doc)  # schema_name=None: infers from doc["schema"]


def test_validate_doc_missing_schema_field_raises() -> None:
    doc = _load_fixture(VALID_DIR, "event")
    doc_copy = copy.deepcopy(doc)
    del doc_copy["schema"]
    with pytest.raises(SchemaError):
        validate_doc(doc_copy)


def test_validate_doc_unknown_schema_namespace_raises() -> None:
    doc = {"schema": "agentlens.foo.v1"}
    with pytest.raises(SchemaError):
        validate_doc(doc)


# ---------------------------------------------------------------------------
# Event line validation
# ---------------------------------------------------------------------------


def test_validate_event_line_accepts_valid_line() -> None:
    doc = _load_fixture(VALID_DIR, "event")
    line = json.dumps(doc)
    out = validate_event_line(line)
    assert out["event_id"] == doc["event_id"]


def test_validate_event_line_rejects_bad_json() -> None:
    with pytest.raises(EventLineError):
        validate_event_line("{not json")


def test_validate_event_line_rejects_schema_violation() -> None:
    bad = {
        "schema": "agentlens.event.v1",
        "event_id": "evt_short",  # too short to match ^evt_[a-z0-9]{12}$
        "run_id": "run_20260518_211328_abc123",
        "ts": "2026-05-18T21:13:29Z",
        "type": "run.started",
        "payload": {},
    }
    with pytest.raises(EventLineError):
        validate_event_line(json.dumps(bad))


# ---------------------------------------------------------------------------
# load_schema unknown name
# ---------------------------------------------------------------------------


def test_load_schema_unknown_raises() -> None:
    with pytest.raises(Exception):
        load_schema("does_not_exist")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Multiple errors aggregated
# ---------------------------------------------------------------------------


def test_schema_error_aggregates_multiple_failures() -> None:
    doc = _load_fixture(VALID_DIR, "run")
    doc["agent"]["name"] = "nope"
    doc["agent"]["mode"] = "nope"
    doc["recording"]["mode"] = "nope"
    with pytest.raises(SchemaError) as exc_info:
        validate_doc(doc)
    assert len(exc_info.value.errors) >= 2


# ---------------------------------------------------------------------------
# Event payload variants smoke test (schema is permissive: payload: object)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_type,payload",
    [
        ("run.started", {}),
        ("checkpoint.marked", {"name": "build"}),
        (
            "command.finished",
            {
                "command_hash": "sha256:"
                + "a" * 64,
                "exit_code": 0,
                "duration_ms": 42,
            },
        ),
        ("run.cancelled", {"signal": "SIGINT"}),
    ],
)
def test_event_payload_variants(event_type: str, payload: dict) -> None:
    doc = _load_fixture(VALID_DIR, "event")
    doc["type"] = event_type
    doc["payload"] = payload
    validate_doc(doc)
