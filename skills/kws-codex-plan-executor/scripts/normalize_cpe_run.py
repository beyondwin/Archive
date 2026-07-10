#!/usr/bin/env python3
"""Serialize a stable read-only CPE v3 inspection record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cpe_runtime.inspection import inspect_run


def normalize(run_dir: Path) -> dict[str, object]:
    return inspect_run(run_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state")
    parser.add_argument("--run-dir")
    parser.add_argument("--context")
    parser.add_argument("--final-output")
    parser.add_argument("--output")
    args = parser.parse_args()
    if not args.run_dir and not args.state:
        parser.error("--run-dir or --state is required")
    run_dir = Path(args.run_dir).expanduser() if args.run_dir else Path(args.state).expanduser().parent
    payload = normalize(run_dir)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
