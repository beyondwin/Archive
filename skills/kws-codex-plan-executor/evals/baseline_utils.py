#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"baseline JSON parse failed: {exc}") from exc


def comparable(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("date", None)
    return result


def fixture_names(payload: dict[str, Any]) -> list[Any]:
    return [item.get("fixture") for item in payload.get("fixtures", [])]


def compare_baseline(expected_path: Path, actual_path: Path, mode: str) -> None:
    if not expected_path.is_file():
        raise ValueError(f"baseline missing: {expected_path}")

    expected_compare = comparable(load_json(expected_path))
    actual_compare = comparable(load_json(actual_path))
    expected_by_fixture = {item.get("fixture"): item for item in expected_compare.get("fixtures", [])}
    actual_fixtures = actual_compare.get("fixtures", [])

    if mode == "full":
        expected_names = fixture_names(expected_compare)
        actual_names = fixture_names(actual_compare)
        if expected_names != actual_names:
            raise ValueError(f"baseline fixture list mismatch: expected {expected_names}, actual {actual_names}")
    elif mode == "subset":
        subset_expected = []
        for item in actual_fixtures:
            fixture = item.get("fixture")
            if fixture not in expected_by_fixture:
                raise ValueError(f"baseline missing fixture: {fixture}")
            subset_expected.append(expected_by_fixture[fixture])
        expected_compare["fixtures"] = subset_expected
    else:
        raise ValueError(f"unknown compare mode: {mode}")

    if expected_compare != actual_compare:
        raise ValueError(f"baseline mismatch: {expected_path}")


def merge_subset_baseline(existing_path: Path, generated_path: Path, target_path: Path) -> None:
    existing = load_json(existing_path) if existing_path.is_file() else {}
    generated = load_json(generated_path)
    existing_fixtures = existing.get("fixtures", [])
    generated_fixtures = generated.get("fixtures", [])
    existing_by_fixture = {
        item.get("fixture"): item
        for item in existing_fixtures
        if isinstance(item, dict) and item.get("fixture")
    }
    generated_by_fixture = {
        item.get("fixture"): item
        for item in generated_fixtures
        if isinstance(item, dict) and item.get("fixture")
    }

    merged_fixtures = []
    for item in existing_fixtures:
        fixture = item.get("fixture") if isinstance(item, dict) else None
        merged_fixtures.append(generated_by_fixture.get(fixture, item))

    for fixture in generated_by_fixture:
        if fixture not in existing_by_fixture:
            raise ValueError(f"refusing subset baseline update for unknown fixture: {fixture}")

    payload = {
        "version": existing.get("version") or generated.get("version"),
        "date": generated.get("date"),
        "fixtures": merged_fixtures,
    }
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="CPE eval baseline compare and merge helpers.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    compare = subcommands.add_parser("compare")
    compare.add_argument("--expected", required=True)
    compare.add_argument("--actual", required=True)
    compare.add_argument("--mode", choices=["full", "subset"], required=True)

    merge = subcommands.add_parser("merge-subset")
    merge.add_argument("--existing", required=True)
    merge.add_argument("--generated", required=True)
    merge.add_argument("--target", required=True)

    args = parser.parse_args()
    try:
        if args.command == "compare":
            compare_baseline(Path(args.expected), Path(args.actual), args.mode)
        elif args.command == "merge-subset":
            merge_subset_baseline(Path(args.existing), Path(args.generated), Path(args.target))
        else:
            parser.error(f"unknown command: {args.command}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
