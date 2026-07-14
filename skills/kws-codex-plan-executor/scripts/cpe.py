#!/usr/bin/env python3
"""Run, resume, or inspect ordered Superpowers implementation plans."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Sequence

from cpe_runtime.runner import SequentialRunner


EXIT_CODES = {"completed": 0, "failed": 1, "blocked": 2, "interrupted": 3}


class CliUsageError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


def absolute_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("path must be absolute")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run")
    run.add_argument("--spec", action="append", type=absolute_path, default=[])
    run.add_argument("--plan", action="append", type=absolute_path, required=True)
    run.add_argument("--workspace", type=absolute_path, required=True)

    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--retry-failed", action="store_true")

    inspect = commands.add_parser("inspect")
    inspect.add_argument("--run-id", required=True)
    return parser


def _bounded_error(exc: BaseException) -> str:
    return (str(exc).strip() or type(exc).__name__)[:2000]


def _emit(payload: dict[str, object], exit_code: int | None = None) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if exit_code is not None:
        return exit_code
    return EXIT_CODES.get(str(payload.get("status")), 1)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        runner = SequentialRunner()
        if args.command == "run":
            result = runner.run(workspace=args.workspace, specs=args.spec, plans=args.plan)
            return _emit(result)
        if args.command == "resume":
            result = runner.resume(run_id=args.run_id, retry_failed=args.retry_failed)
            return _emit(result)
        result = runner.inspect(run_id=args.run_id)
        return _emit(result, 0)
    except KeyboardInterrupt:
        return _emit({"status": "interrupted", "error": "invocation interrupted"})
    except (CliUsageError, OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        return _emit({"status": "failed", "error": _bounded_error(exc)}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
