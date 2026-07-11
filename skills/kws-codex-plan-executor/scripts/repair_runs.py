#!/usr/bin/env python3
"""Plan or explicitly apply safe CPE v3 repairs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cpe_runtime.repair import SAFE_ACTIONS, apply_repair, plan_repairs


def _target(args: argparse.Namespace, home: Path) -> Path | None:
    if args.run_dir:
        path = Path(args.run_dir).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("run_dir_missing")
        return path
    if args.state:
        path = Path(args.state).expanduser().resolve()
        if path.name != "state.json" or not path.is_file():
            raise ValueError("state_path_invalid")
        return path.parent
    return home / "orchestrator" / args.run_id if args.run_id else None


def _json_object(raw: str | None, name: str) -> dict[str, object] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name}_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name}_invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--run-dir")
    target.add_argument("--state", help="compatibility alias for an exact v3 state.json path")
    target.add_argument("--run-id")
    parser.add_argument("--action", choices=sorted(SAFE_ACTIONS))
    parser.add_argument("--details", help="JSON object with action-specific evidence and identifiers")
    parser.add_argument("--expected-projection-delta", help="JSON object declaring fields replay must produce")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recent", type=int, default=20)
    parser.add_argument("--stale-hours", type=float, default=24.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        home = Path(args.codex_home).expanduser().resolve()
        run_dir = _target(args, home)
        if args.apply:
            if run_dir is None or not args.action:
                parser.error("--apply requires one exact run target and --action")
            payload = apply_repair(
                run_dir,
                args.action,
                details=_json_object(args.details, "details"),
                expected_projection_delta=_json_object(args.expected_projection_delta, "expected_projection_delta"),
            )
        elif run_dir is not None:
            payload = plan_repairs(run_dir).as_dict()
        else:
            paths = sorted(
                (home / "orchestrator").glob("*"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[: args.recent] if (home / "orchestrator").exists() else []
            payload = {"dry_run": True, "runs": {path.name: plan_repairs(path).as_dict() for path in paths if path.is_dir()}}
    except (OSError, ValueError) as exc:
        code = str(exc) or "repair_failed"
        print(json.dumps({"classification": code, "passed": False, "errors": [code]}, ensure_ascii=False, indent=2))
        return 2
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
