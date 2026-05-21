"""AgentLens schema loader and validator.

Loads bundled Draft 2020-12 schemas, validates documents and events.jsonl
lines, and aggregates every jsonschema error into a single
`SchemaError`/`EventLineError`.

Public API:
    load_schema(name)
    validate_doc(doc, *, schema_name=None)
    validate_event_line(line)

The v1 runtime schemas keep their historical short names: "run", "event",
"final", "eval", and "manifest". The AgentRunway Trust Console adds explicit
v2 names plus derived artifacts.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import jsonschema
from jsonschema import Draft202012Validator

SchemaName = Literal[
    "run",
    "event",
    "final",
    "eval",
    "manifest",
    "run_v2",
    "event_v2",
    "final_v2",
    "eval_v2",
    "manifest_v2",
    "agentrunway_projection",
    "trust_report",
]

_SCHEMA_FILES: dict[str, str] = {
    "run": "run.schema.json",
    "event": "event.schema.json",
    "final": "final.schema.json",
    "eval": "eval.schema.json",
    "manifest": "manifest.schema.json",
    "run_v2": "run.v2.schema.json",
    "event_v2": "event.v2.schema.json",
    "final_v2": "final.v2.schema.json",
    "eval_v2": "eval.v2.schema.json",
    "manifest_v2": "manifest.v2.schema.json",
    "agentrunway_projection": "agentrunway_projection.v1.schema.json",
    "trust_report": "trust_report.v1.schema.json",
}
_SCHEMA_NAMES: tuple[str, ...] = tuple(_SCHEMA_FILES)
_NAMESPACE_TO_NAME: dict[str, str] = {
    "agentlens.run.v1": "run",
    "agentlens.event.v1": "event",
    "agentlens.final.v1": "final",
    "agentlens.eval.v1": "eval",
    "agentlens.manifest.v1": "manifest",
    "agentlens.run.v2": "run_v2",
    "agentlens.event.v2": "event_v2",
    "agentlens.final.v2": "final_v2",
    "agentlens.eval.v2": "eval_v2",
    "agentlens.manifest.v2": "manifest_v2",
    "agentlens.agentrunway_projection.v1": "agentrunway_projection",
    "agentlens.trust_report.v1": "trust_report",
}
_SCHEMA_DIR = Path(__file__).resolve().parent / "jsonschema"


class SchemaError(ValueError):
    """Raised when a document fails JSON Schema validation.

    Attributes:
        errors: list of human-readable jsonschema error messages.
        schema_name: which schema was used (or None if not resolvable).
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        schema_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.errors: list[str] = list(errors or [])
        self.schema_name: str | None = schema_name


class EventLineError(ValueError):
    """Raised when an events.jsonl line is malformed or schema-invalid.

    Attributes:
        errors: list of error messages (json decode or schema).
        line: the offending line (truncated for safety).
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        line: str | None = None,
    ) -> None:
        super().__init__(message)
        self.errors: list[str] = list(errors or [])
        self.line: str | None = line


@lru_cache(maxsize=None)
def load_schema(name: SchemaName) -> dict[str, Any]:
    """Load and cache a bundled Draft 2020-12 JSON Schema by short name.

    Args:
        name: one of the keys in the AgentLens schema registry.

    Returns:
        Parsed schema as a dict.

    Raises:
        ValueError: if `name` is not a known schema name.
        FileNotFoundError: if the bundled schema file is missing.
    """
    if name not in _SCHEMA_NAMES:
        raise ValueError(
            f"unknown schema name: {name!r}; expected one of {_SCHEMA_NAMES!r}"
        )
    path = _SCHEMA_DIR / _SCHEMA_FILES[str(name)]
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _infer_schema_name(doc: dict[str, Any]) -> str:
    namespace = doc.get("schema")
    if not isinstance(namespace, str):
        raise SchemaError(
            "document missing 'schema' field; cannot infer schema_name",
            errors=["missing required field: schema"],
        )
    name = _NAMESPACE_TO_NAME.get(namespace)
    if name is None:
        raise SchemaError(
            f"unknown schema namespace: {namespace!r}",
            errors=[f"unknown schema namespace: {namespace!r}"],
            schema_name=None,
        )
    return name


def _format_error(err: jsonschema.ValidationError) -> str:
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{path}: {err.message}"


def validate_doc(
    doc: Any,
    *,
    schema_name: str | None = None,
) -> None:
    """Validate `doc` against the named (or inferred) schema.

    If `schema_name` is None, the schema is inferred from `doc["schema"]`
    (e.g. ``"agentlens.run.v1"`` -> ``"run"``).

    All jsonschema errors are aggregated via
    ``Draft202012Validator.iter_errors`` and raised together in a single
    ``SchemaError``. The exception's ``errors`` attribute is a list of
    formatted messages.

    Raises:
        SchemaError: if `doc` does not satisfy the schema, the schema field
            is missing/unknown, or `schema_name` is unknown.
    """
    if not isinstance(doc, dict):
        raise SchemaError(
            "document must be a JSON object",
            errors=["document is not an object"],
            schema_name=schema_name,
        )

    if schema_name is None:
        schema_name = _infer_schema_name(doc)
    elif schema_name not in _SCHEMA_NAMES:
        raise SchemaError(
            f"unknown schema_name: {schema_name!r}",
            errors=[f"unknown schema_name: {schema_name!r}"],
        )

    schema = load_schema(schema_name)  # type: ignore[arg-type]
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        messages = [_format_error(e) for e in errors]
        raise SchemaError(
            f"{schema_name} schema validation failed: {len(messages)} error(s)",
            errors=messages,
            schema_name=schema_name,
        )


def validate_event_line(line: str) -> dict[str, Any]:
    """Parse and validate one events.jsonl line.

    Returns the parsed event dict on success.

    Raises:
        EventLineError: when the line is not valid JSON, not an object, or
            does not satisfy the event schema.
    """
    truncated = line if len(line) <= 512 else line[:509] + "..."
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EventLineError(
            f"invalid JSON in event line: {exc.msg}",
            errors=[f"json decode error: {exc.msg}"],
            line=truncated,
        ) from exc

    if not isinstance(parsed, dict):
        raise EventLineError(
            "event line is not a JSON object",
            errors=["event line is not a JSON object"],
            line=truncated,
        )

    try:
        validate_doc(parsed)
    except SchemaError as exc:
        raise EventLineError(
            str(exc),
            errors=list(exc.errors),
            line=truncated,
        ) from exc

    return parsed


__all__ = [
    "EventLineError",
    "SchemaError",
    "SchemaName",
    "load_schema",
    "validate_doc",
    "validate_event_line",
]
