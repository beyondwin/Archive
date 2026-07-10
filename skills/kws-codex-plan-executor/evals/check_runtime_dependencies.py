#!/usr/bin/env python3
from __future__ import annotations

import importlib.metadata
import json
import shlex
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from preflight_dependencies import PREPARATION_COMMAND, Requirement, check_requirement


def missing_distribution_metadata(_: str) -> str:
    raise importlib.metadata.PackageNotFoundError("MissingMetadataFixture")


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    preparation_tokens = shlex.split(PREPARATION_COMMAND)
    preparation_path = (
        Path(preparation_tokens[1]) / preparation_tokens[-1]
        if len(preparation_tokens) >= 9
        and preparation_tokens[0] == "cd"
        and preparation_tokens[2:8] == ["&&", "python3", "-m", "pip", "install", "-r"]
        else Path()
    )
    actual = check_requirement(Requirement("PyYAML", "yaml", "6.0.3"))
    missing = check_requirement(
        Requirement("AbsentFixture", "absent_fixture_module", "1.0.0"),
        finder=lambda _: None,
        version_getter=lambda _: "1.0.0",
    )
    metadata_missing = check_requirement(
        Requirement("MissingMetadataFixture", "yaml", "1.0.0"),
        finder=lambda _: object(),
        version_getter=missing_distribution_metadata,
    )
    checks = {
        "pyyaml_pin_is_available": actual["passed"] is True,
        "preparation_command_locates_real_pin": (
            preparation_path.is_absolute()
            and preparation_path == skill_dir / "requirements-eval.txt"
            and preparation_path.read_text(encoding="utf-8") == "PyYAML==6.0.3\n"
        ),
        "missing_import_is_actionable": (
            missing["passed"] is False
            and missing["reason"] == "missing_import"
            and "python3 -m pip install -r requirements-eval.txt" in missing["preparation_command"]
        ),
        "missing_metadata_is_actionable": (
            metadata_missing["passed"] is False
            and metadata_missing["reason"] == "missing_distribution_metadata"
            and metadata_missing["required_version"] == "1.0.0"
            and "python3 -m pip install -r requirements-eval.txt"
            in metadata_missing["preparation_command"]
        ),
    }
    payload = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
