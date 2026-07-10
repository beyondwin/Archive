#!/usr/bin/env python3
"""Aggregate read-only lifecycle, integrity, usage, and quality metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cpe_runtime.inspection import inspect_recent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--recent", type=int, default=5)
    parser.add_argument("--include-finished", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    payload = inspect_recent(Path(args.codex_home), args.recent)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
