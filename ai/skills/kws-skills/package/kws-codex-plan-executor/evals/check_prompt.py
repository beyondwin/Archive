#!/usr/bin/env python3
"""Deterministic checks for prompt export fixtures."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


TEXT_BLOCK_RE = re.compile(r"```text\s*\n.*?\n```", re.DOTALL)
TOKEN_RE = re.compile(r"\{\{[^}]+\}\}")
IMPLEMENTATION_STARTED_RE = re.compile(
    r"\b(started implementation|implemented|changed files|tests pass)\b|구현을 시작|수정했습니다|테스트가 통과",
    re.IGNORECASE,
)


def load_fixture(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("fixture must be a YAML object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, help="Fixture YAML path")
    parser.add_argument("--output", required=True, help="Codex final message path")
    args = parser.parse_args()

    fixture_path = Path(args.fixture)
    output_path = Path(args.output)
    fixture = load_fixture(fixture_path)
    expected = fixture.get("expected") or {}
    text = output_path.read_text(encoding="utf-8")

    checks: dict[str, bool] = {}
    failures: list[str] = []

    text_blocks = TEXT_BLOCK_RE.findall(text)
    if expected.get("prompt_only", False):
        checks["one_text_block"] = len(text_blocks) == 1 and text.strip() == text_blocks[0].strip()
    else:
        checks["one_text_block"] = len(text_blocks) == 1
    if not checks["one_text_block"]:
        failures.append("expected exactly one fenced text block")

    checks["no_template_tokens"] = TOKEN_RE.search(text) is None
    if not checks["no_template_tokens"]:
        failures.append("template tokens remain in output")

    missing = [item for item in expected.get("must_include", []) if item not in text]
    checks["must_include"] = not missing
    failures.extend(f"missing required text: {item}" for item in missing)

    present_forbidden = [item for item in expected.get("must_not_include", []) if item in text]
    checks["must_not_include"] = not present_forbidden
    failures.extend(f"forbidden text present: {item}" for item in present_forbidden)

    if "spark" in expected:
        wants_spark = bool(expected["spark"])
        has_spark = "gpt-5.3-codex-spark" in text
        checks["model_routing"] = has_spark if wants_spark else not has_spark
        if not checks["model_routing"]:
            failures.append("Spark routing presence does not match fixture expectation")
    else:
        checks["model_routing"] = True

    checks["no_implementation_started_language"] = IMPLEMENTATION_STARTED_RE.search(text) is None
    if not checks["no_implementation_started_language"]:
        failures.append("output looks like implementation started instead of prompt export")

    payload = {
        "fixture": fixture.get("name") or fixture_path.stem,
        "passed": not failures,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
