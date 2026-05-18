"""Schema drift checker.

Run via ``python -m agentlens.schema.check_drift``. For every bundled
schema, ensures a corresponding fixture exists at
``tests/fixtures/schemas/valid/<entity>.json`` and validates against the
schema. Exits non-zero on any miss/failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agentlens.schema.validate import SchemaError, load_schema, validate_doc

SCHEMA_NAMES = ("run", "event", "final", "eval", "manifest")


def _find_fixtures_dir() -> Path:
    """Locate ``tests/fixtures/schemas/valid`` relative to CWD.

    Walks parents of the CWD looking for a checkout that contains the
    fixtures directory. Falls back to ``CWD / tests/fixtures/schemas/valid``.
    """
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        guess = candidate / "tests" / "fixtures" / "schemas" / "valid"
        if guess.is_dir():
            return guess
    return cwd / "tests" / "fixtures" / "schemas" / "valid"


def main(argv: list[str] | None = None) -> int:
    fixtures_dir = _find_fixtures_dir()
    errors: list[str] = []

    for name in SCHEMA_NAMES:
        # Schema must load cleanly.
        try:
            load_schema(name)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover - shouldn't happen
            errors.append(f"[{name}] failed to load schema: {exc}")
            continue

        fixture_path = fixtures_dir / f"{name}.json"
        if not fixture_path.is_file():
            errors.append(f"[{name}] missing fixture: {fixture_path}")
            continue

        try:
            with fixture_path.open("r", encoding="utf-8") as f:
                doc = json.load(f)
        except json.JSONDecodeError as exc:
            errors.append(f"[{name}] fixture not valid JSON: {exc}")
            continue

        try:
            validate_doc(doc, schema_name=name)
        except SchemaError as exc:
            joined = "; ".join(exc.errors)
            errors.append(f"[{name}] fixture failed validation: {joined}")
            continue

        print(f"[{name}] OK ({fixture_path})")

    if errors:
        print("", file=sys.stderr)
        print("Schema drift detected:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print("All schemas + fixtures OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
