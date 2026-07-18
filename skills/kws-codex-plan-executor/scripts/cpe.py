#!/usr/bin/env python3
"""Run, resume, or inspect ordered Superpowers implementation plans."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from cpe_runtime.runner import SequentialRunner


EXIT_CODES = {"completed": 0, "failed": 1, "blocked": 2, "checkpointed": 3}


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
    run.add_argument(
        "--sandbox",
        choices=("danger-full-access", "workspace-write"),
        default="danger-full-access",
    )
    run.add_argument(
        "--controller-slice-seconds",
        type=int,
        default=1200,
    )

    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    retry = resume.add_mutually_exclusive_group()
    retry.add_argument("--retry-blocked", action="store_true")
    retry.add_argument("--retry-failed", action="store_true")

    inspect = commands.add_parser("inspect")
    inspect.add_argument("--run-id", required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--command-id", required=True)
    verify.add_argument("--phase", choices=("task", "affected", "branch_final"), required=True)
    verify.add_argument("--input-digest", required=True)
    verify.add_argument(
        "--mutable-input-policy",
        choices=("immutable", "digest_complete", "always_execute"),
        required=True,
    )
    verify.add_argument("--cwd", type=absolute_path, required=True)
    verify.add_argument("argv", nargs=argparse.REMAINDER)
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
        raw_argv = list(sys.argv[1:] if argv is None else argv)
        args = build_parser().parse_args(raw_argv)
        runner = SequentialRunner()
        if args.command == "run":
            result = runner.run(
                workspace=args.workspace,
                specs=args.spec,
                plans=args.plan,
                sandbox_mode=args.sandbox,
                controller_slice_seconds=args.controller_slice_seconds,
            )
            return _emit(result)
        if args.command == "resume":
            result = runner.resume(
                run_id=args.run_id,
                retry_blocked=args.retry_blocked,
                retry_failed=args.retry_failed,
            )
            return _emit(result)
        if args.command == "verify":
            command_argv = list(args.argv)
            if command_argv[:1] != ["--"]:
                raise CliUsageError("verify requires -- before command argv")
            command_argv = command_argv[1:]
            if not command_argv:
                raise CliUsageError("verify command argv must not be empty")
            result = runner.verify(
                run_id=args.run_id,
                command_id=args.command_id,
                phase=args.phase,
                input_digest=args.input_digest,
                mutable_input_policy=args.mutable_input_policy,
                cwd=args.cwd,
                argv=command_argv,
            )
            if result.get("status") == "uncached_command_required":
                return _emit(result, 1)
            return _emit(result, 0 if result.get("status") == "passed" else 1)
        result = runner.inspect(run_id=args.run_id)
        return _emit(result, 0)
    except KeyboardInterrupt:
        return _emit({"status": "checkpointed", "error": "invocation interrupted"})
    except (CliUsageError, OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        return _emit({"status": "failed", "error": _bounded_error(exc)}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
