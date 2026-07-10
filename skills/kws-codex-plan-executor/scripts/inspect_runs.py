#!/usr/bin/env python3
"""Read-only inspection for CPE v3 runs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cpe_runtime.inspection import inspect_recent, inspect_run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--run-dir")
    parser.add_argument("--recent", type=int, default=20)
    parser.add_argument("--plan")
    parser.add_argument("--all-plans", action="store_true")
    parser.add_argument("--include-finished", action="store_true")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.run_dir:
        payload = inspect_run(Path(args.run_dir))
    else:
        payload = inspect_recent(Path(args.codex_home), args.recent)
    if args.jsonl and isinstance(payload.get("runs"), list):
        text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in payload["runs"])
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
