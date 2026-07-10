#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Requirement:
    distribution: str
    module: str
    version: str


REQUIREMENTS = (Requirement("PyYAML", "yaml", "6.0.3"),)
SKILL_DIR = Path(__file__).resolve().parents[1]
PREPARATION_COMMAND = (
    f"cd {shlex.quote(str(SKILL_DIR))} && python3 -m pip install -r requirements-eval.txt"
)


def check_requirement(
    requirement: Requirement,
    *,
    finder: Callable[[str], object | None] = importlib.util.find_spec,
    version_getter: Callable[[str], str] = importlib.metadata.version,
) -> dict[str, object]:
    if finder(requirement.module) is None:
        return {
            "passed": False,
            "distribution": requirement.distribution,
            "required_version": requirement.version,
            "reason": "missing_import",
            "preparation_command": PREPARATION_COMMAND,
        }
    try:
        actual = version_getter(requirement.distribution)
    except importlib.metadata.PackageNotFoundError:
        return {
            "passed": False,
            "distribution": requirement.distribution,
            "required_version": requirement.version,
            "reason": "missing_distribution_metadata",
            "preparation_command": PREPARATION_COMMAND,
        }
    return {
        "passed": actual == requirement.version,
        "distribution": requirement.distribution,
        "required_version": requirement.version,
        "actual_version": actual,
        "reason": "ok" if actual == requirement.version else "version_mismatch",
        "preparation_command": PREPARATION_COMMAND,
    }


def check_requirements() -> dict[str, object]:
    results = [check_requirement(item) for item in REQUIREMENTS]
    return {"passed": all(item["passed"] for item in results), "requirements": results}


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    payload = check_requirements()
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
