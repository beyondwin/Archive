from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from agentlens.schema import SchemaError, load_schema, validate_doc


V2_SCHEMA_NAMES = [
    "run_v2",
    "event_v2",
    "final_v2",
    "eval_v2",
    "manifest_v2",
    "waygent_projection",
    "trust_report",
]

ROOT = Path(__file__).resolve().parents[2]
VALID = ROOT / "tests" / "fixtures" / "schemas" / "v2" / "valid"
INVALID = ROOT / "tests" / "fixtures" / "schemas" / "v2" / "invalid"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", V2_SCHEMA_NAMES)
def test_v2_schema_loads_and_is_draft_2020_12(name: str) -> None:
    schema = load_schema(name)  # type: ignore[arg-type]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    ("fixture", "schema_name"),
    [
        ("run.json", "run_v2"),
        ("event.json", "event_v2"),
        ("final.json", "final_v2"),
        ("eval.json", "eval_v2"),
        ("manifest.json", "manifest_v2"),
        ("waygent_projection.json", "waygent_projection"),
        ("trust_report.json", "trust_report"),
    ],
)
def test_v2_valid_fixtures_validate(fixture: str, schema_name: str) -> None:
    validate_doc(_load(VALID / fixture), schema_name=schema_name)


def test_v2_schema_inference_uses_namespace_mapping() -> None:
    validate_doc(_load(VALID / "event.json"))
    validate_doc(_load(VALID / "trust_report.json"))


@pytest.mark.parametrize(
    ("fixture", "schema_name", "expected"),
    [
        ("event_legacy_kws_cpe.json", "event_v2", "kws-cpe"),
        ("event_missing_trust_impact.json", "event_v2", "trust_impact"),
        ("trust_report_missing_verdict.json", "trust_report", "trust_verdict"),
    ],
)
def test_v2_invalid_fixtures_raise(
    fixture: str, schema_name: str, expected: str
) -> None:
    with pytest.raises(SchemaError) as exc_info:
        validate_doc(_load(INVALID / fixture), schema_name=schema_name)
    assert expected in "\n".join(exc_info.value.errors)
