#!/usr/bin/env python3
"""Validate a CPE v3 run from its immutable manifest, events, and evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cpe_runtime.validation import validate_completion, validate_integrity, validate_run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="run directory or state/manifest path")
    parser.add_argument(
        "--profile",
        choices=("auto", "integrity", "completion"),
        default="auto",
        help="validation profile; auto selects completion only for completed lifecycle",
    )
    args = parser.parse_args()
    path = Path(args.path).expanduser().resolve()
    run_dir = path if path.is_dir() else path.parent
    validator = {
        "auto": validate_run,
        "integrity": validate_integrity,
        "completion": validate_completion,
    }[args.profile]
    report = validator(run_dir)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if report.classification == "unsupported_schema":
        return 2
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
