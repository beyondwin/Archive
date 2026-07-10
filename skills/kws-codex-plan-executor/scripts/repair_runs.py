#!/usr/bin/env python3
"""Plan or explicitly apply safe CPE v3 repairs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cpe_runtime.repair import SAFE_ACTIONS, apply_repair, plan_repairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--run-id")
    parser.add_argument("--action", choices=sorted(SAFE_ACTIONS))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--recent", type=int, default=20)
    parser.add_argument("--stale-hours", type=float, default=24.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    home = Path(args.codex_home).expanduser().resolve()
    if args.apply:
        if not args.run_id or not args.action:
            parser.error("--apply requires exact --run-id and --action")
        payload = apply_repair(home / "orchestrator" / args.run_id, args.action)
    elif args.run_id:
        payload = plan_repairs(home / "orchestrator" / args.run_id).as_dict()
    else:
        paths = sorted((home / "orchestrator").glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)[: args.recent] if (home / "orchestrator").exists() else []
        payload = {"dry_run": True, "runs": {path.name: plan_repairs(path).as_dict() for path in paths if path.is_dir()}}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
