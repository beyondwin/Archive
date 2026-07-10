#!/usr/bin/env python3
"""Validate a CPE v3 run from its immutable manifest, events, and evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cpe_runtime.validation import validate_run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="run directory or state/manifest path")
    args = parser.parse_args()
    path = Path(args.path).expanduser().resolve()
    run_dir = path if path.is_dir() else path.parent
    report = validate_run(run_dir)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if report.classification == "unsupported_schema":
        return 2
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
