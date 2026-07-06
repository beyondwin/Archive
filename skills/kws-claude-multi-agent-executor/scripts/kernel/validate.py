"""validate.py — minimal stdlib JSON-Schema validator (CME v3.0 T5).

Supported keywords:
  type                 — string, number, integer, boolean, null, object, array
                         (value may be a string OR a list of strings)
  required             — list of required property names
  properties           — object property sub-schemas
  items                — array item sub-schema
  enum                 — list of allowed values
  additionalProperties — only enforced when explicitly false
  $ref                 — local #/$defs/<Name> resolution only
  $defs                — definitions block (resolved by $ref)

Public API:
  check(instance, schema) -> list[str]
    Returns a list of "<json-path>: <reason>" error strings.
    Empty list = valid.
"""

from __future__ import annotations
from typing import Any


# ── type-checking helpers ────────────────────────────────────────────────────

def _matches_type(value: Any, type_name: str) -> bool:
    """Return True if *value* is an instance of the JSON type *type_name*."""
    if type_name == "null":
        return value is None
    if type_name == "boolean":
        # bool must be checked before int (Python bool subclasses int)
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False  # unknown type name — conservative: reject nothing extra


def _check_type(value: Any, type_spec: "str | list[str]", path: str) -> list[str]:
    """Validate *value* against a type keyword (string or list of strings)."""
    if isinstance(type_spec, str):
        names = [type_spec]
    else:
        names = list(type_spec)
    if not any(_matches_type(value, n) for n in names):
        return [f"{path}: expected type {type_spec!r}, got {type(value).__name__}"]
    return []


# ── ref resolution ───────────────────────────────────────────────────────────

def _resolve_ref(ref: str, root_schema: dict) -> dict:
    """Resolve a local JSON-Schema $ref of the form '#/$defs/<Name>'."""
    if not ref.startswith("#/"):
        raise ValueError(f"Only local $ref supported, got: {ref!r}")
    parts = ref.removeprefix("#/").split("/")
    node = root_schema
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"$ref {ref!r} — segment {part!r} not found in schema")
        node = node[part]
    return node


# ── core recursive validator ─────────────────────────────────────────────────

def _validate(instance: Any, schema: dict, path: str, root: dict) -> list[str]:
    """Recursively validate *instance* against *schema*, accumulating errors."""
    errors: list[str] = []

    # Resolve $ref first — the referenced schema replaces this node entirely
    if "$ref" in schema:
        resolved = _resolve_ref(schema["$ref"], root)
        errors.extend(_validate(instance, resolved, path, root))
        # JSON-Schema 2020-12: $ref no longer stops sibling keywords, but
        # for our minimal use-case the schemas only put $ref alone in nodes,
        # so we return early to avoid double-processing.
        return errors

    # Label for errors about *this* node itself (not a child): the path when
    # nested, else "<root>" so no error string starts with ": ".
    here = path if path else "<root>"

    # type
    if "type" in schema:
        type_errors = _check_type(instance, schema["type"], here)
        if type_errors:
            errors.extend(type_errors)
            # Can't meaningfully continue if the type is wrong
            return errors

    # enum
    if "enum" in schema:
        if instance not in schema["enum"]:
            errors.append(
                f"{here}: value {instance!r} not in enum {schema['enum']!r}"
            )

    # Properties + required + additionalProperties (object-specific)
    if isinstance(instance, dict):
        # required
        for req in schema.get("required", []):
            if req not in instance:
                child_path = f"{path}.{req}" if path else req
                errors.append(f"{child_path}: required field missing")

        # properties — recurse into declared properties
        props = schema.get("properties", {})
        for key, val in instance.items():
            child_path = f"{path}.{key}" if path else key
            if key in props:
                errors.extend(_validate(val, props[key], child_path, root))

        # additionalProperties: false
        if schema.get("additionalProperties") is False:
            extra = set(instance.keys()) - set(props.keys())
            for key in sorted(extra):
                child_path = f"{path}.{key}" if path else key
                errors.append(
                    f"{child_path}: additional property not allowed"
                )

    # items — array item validation
    if isinstance(instance, list) and "items" in schema:
        item_schema = schema["items"]
        for idx, item in enumerate(instance):
            child_path = f"{path}[{idx}]"
            errors.extend(_validate(item, item_schema, child_path, root))

    return errors


# ── public API ───────────────────────────────────────────────────────────────

def check(instance: dict, schema: dict) -> list[str]:
    """Validate *instance* against *schema*.

    Returns a list of "<json-path>: <reason>" error strings.
    An empty list means the instance is valid.

    The root schema is passed as *root* for $ref resolution throughout
    recursive calls.
    """
    return _validate(instance, schema, path="", root=schema)
