#!/usr/bin/env python3
"""Deterministic checks for fixture and real-plan public prompt export."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


TOKEN_RE = re.compile(r"\{\{[^}]+\}\}")
IMPLEMENTATION_STARTED_RE = re.compile(
    r"\b(started implementation|implemented|changed files|tests pass)\b|구현을 시작|수정했습니다|테스트가 통과",
    re.IGNORECASE,
)


def load_fixture(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("fixture must be a YAML object")
    return data


def parse_export(text: str) -> tuple[str, str, str] | None:
    lines = text.splitlines()
    if len(lines) < 4 or not re.fullmatch(r"`{3,}text", lines[0]):
        return None
    fence = lines[0][:-4]
    if lines[-1] != fence or sum(1 for line in lines if line == fence) != 1:
        return None
    match = re.search(r"<<'([^']+)'$", lines[1])
    if not match:
        return None
    delimiter = match.group(1)
    if lines[-2] != delimiter or sum(1 for line in lines if line == delimiter) != 1:
        return None
    body = "\n".join(lines[2:-2])
    return fence, delimiter, body


def _evaluate(text: str, expected: dict[str, object]) -> tuple[dict[str, bool], list[str]]:
    parsed = parse_export(text)
    checks: dict[str, bool] = {"one_dynamic_text_block": parsed is not None}
    failures: list[str] = []
    if parsed is None:
        failures.append("expected one collision-safe fenced text block")
        body = text
    else:
        fence, delimiter, body = parsed
        checks["outer_fence_exceeds_inner_runs"] = len(fence) > max(
            (len(run) for run in re.findall(r"`+", "\n".join(text.splitlines()[1:-1]))),
            default=2,
        )
        checks["heredoc_delimiter_unique"] = text.splitlines().count(delimiter) == 1 and delimiter not in body.splitlines()
    checks["no_template_tokens"] = TOKEN_RE.search(text) is None
    missing = [str(item) for item in expected.get("must_include", []) if str(item) not in text]
    forbidden = [str(item) for item in expected.get("must_not_include", []) if str(item) in text]
    checks["must_include"] = not missing
    checks["must_not_include"] = not forbidden
    checks["fixed_launcher"] = "codex exec --json --model gpt-5.6-sol" in text and 'model_reasoning_effort="high"' in text
    checks["model_not_in_prompt_body"] = "gpt-5.6-" not in body
    checks["no_implementation_started_language"] = IMPLEMENTATION_STARTED_RE.search(text) is None
    failures.extend(f"missing required text: {item}" for item in missing)
    failures.extend(f"forbidden text present: {item}" for item in forbidden)
    failures.extend(name for name, passed in checks.items() if not passed and name not in {"must_include", "must_not_include"})
    return checks, failures


def _real_plan() -> tuple[str, dict[str, object]]:
    skill = Path(__file__).resolve().parents[1]
    repo = skill.parents[1]
    plan = repo / "docs" / "superpowers" / "plans" / "2026-07-10-cpe-v3-integrity-closure.md"
    spec = repo / "docs" / "superpowers" / "specs" / "2026-07-10-cpe-v3-integrity-closure-design.md"
    before: set[str]
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw) / "codex"
        before = {str(item.relative_to(home)) for item in home.rglob("*")} if home.exists() else set()
        env = {**os.environ, "CODEX_HOME": str(home)}
        result = subprocess.run(
            [
                sys.executable,
                str(skill / "scripts" / "cpe.py"),
                "export",
                "--plan",
                str(plan),
                "--spec",
                str(spec),
                "--workspace",
                str(repo),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        after = {str(item.relative_to(home)) for item in home.rglob("*")} if home.exists() else set()
    expected = {"must_include": [str(plan), str(spec)], "must_not_include": ["gpt-5.6-sol\n"]}
    checks, failures = _evaluate(result.stdout, expected)
    checks["public_export_exit_zero"] = result.returncode == 0
    checks["export_creates_no_artifacts"] = before == after
    checks["source_bodies_not_embedded"] = plan.read_text(encoding="utf-8") not in result.stdout and spec.read_text(encoding="utf-8") not in result.stdout
    checks["no_traceback"] = "Traceback" not in result.stderr
    failures.extend(name for name in ("public_export_exit_zero", "export_creates_no_artifacts", "source_bodies_not_embedded", "no_traceback") if not checks[name])
    return plan.stem, {"passed": not failures, "checks": checks, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture")
    parser.add_argument("--output")
    parser.add_argument("--real-plan", action="store_true")
    args = parser.parse_args()
    if args.real_plan:
        name, payload = _real_plan()
    else:
        if not args.fixture or not args.output:
            parser.error("--fixture and --output are required unless --real-plan is used")
        fixture_path = Path(args.fixture)
        fixture = load_fixture(fixture_path)
        name = str(fixture.get("name") or fixture_path.stem)
        checks, failures = _evaluate(Path(args.output).read_text(encoding="utf-8"), fixture.get("expected") or {})
        payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps({"fixture": name, **payload}, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
