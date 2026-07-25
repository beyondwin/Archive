#!/usr/bin/env python3
"""Run, resume, or inspect one durable Superpowers execution contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from cpe_runtime.runtime import CpeRuntime
from cpe_runtime.state import DocumentSource

EXIT_CODES = {
    "handed_off": 0,
    "failed": 1,
    "blocked": 2,
    "interrupted": 3,
}


class CliUsageError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)

    def parse_args(
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        parsed = super().parse_args(args, namespace)
        if parsed.command == "run" and (
            (parsed.adopt_worktree is None) != (parsed.base is None)
        ):
            self.error("--adopt-worktree and --base must be supplied together")
        return parsed


def absolute_path(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("path must be absolute")
    return str(path)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--document", action="append", type=absolute_path, required=True)
    run.add_argument("--workspace", type=absolute_path, required=True)
    run.add_argument(
        "--superpowers-skill",
        choices=("subagent-driven-development", "executing-plans"),
        required=True,
    )
    run.add_argument(
        "--sandbox",
        choices=("workspace-write", "danger-full-access"),
        default="workspace-write",
    )
    run.add_argument("--adopt-worktree", type=absolute_path)
    run.add_argument("--base")
    for name in ("resume", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
    return parser


def _bounded_error(exc: BaseException) -> str:
    return (str(exc).strip() or type(exc).__name__)[:2000]


def _emit(payload: dict[str, object], exit_code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


def _emit_terminal(payload: dict[str, object]) -> int:
    status = str(payload.get("status"))
    if status not in EXIT_CODES:
        raise ValueError(f"invalid CPE terminal status: {status}")
    return _emit(payload, EXIT_CODES[status])


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
        runtime = CpeRuntime()
        if args.command == "run":
            documents = tuple(
                DocumentSource(Path(path)) for path in args.document
            )
            result = runtime.run(
                workspace=Path(args.workspace),
                documents=documents,
                superpowers_skill=args.superpowers_skill,
                sandbox=args.sandbox,
                adopt_worktree_path=(
                    Path(args.adopt_worktree) if args.adopt_worktree else None
                ),
                base=args.base,
            )
            return _emit_terminal(result)
        if args.command == "resume":
            return _emit_terminal(runtime.resume(run_id=args.run_id))
        return _emit(runtime.inspect(run_id=args.run_id), 0)
    except KeyboardInterrupt:
        return _emit(
            {"status": "interrupted", "error": "invocation interrupted"},
            EXIT_CODES["interrupted"],
        )
    except Exception as exc:
        return _emit({"status": "failed", "error": _bounded_error(exc)}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
