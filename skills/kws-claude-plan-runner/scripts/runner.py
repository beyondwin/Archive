#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from plan_runner.contracts import ExitCode  # noqa: E402
from plan_runner.engine import PlanRunner, RuntimePaths  # noqa: E402
from plan_runner.helper import helper_client  # noqa: E402
from plan_runner.runtime import RuntimeUnavailable, require_compatible_runtime  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runner")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--spec", action="append", required=True, type=Path)
    run.add_argument("--plan", action="append", required=True, type=Path)
    run.add_argument("--workspace", required=True, type=Path)
    run.add_argument("--stall-seconds", type=float, default=3600)
    run.add_argument("--model")
    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    retry = resume.add_mutually_exclusive_group()
    retry.add_argument("--retry-blocked", action="store_true")
    retry.add_argument("--retry-failed", action="store_true")
    resume.add_argument("--strategy-note")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--run-id", required=True)
    return parser


def _paths() -> RuntimePaths:
    return RuntimePaths(
        state_home=Path.home() / ".claude" / "plan-runner",
        worktree_home=Path.home() / ".claude" / "worktrees" / "plan-runner",
        runner_script=Path(__file__).resolve(),
        skill_root=SKILL_ROOT,
    )


def _helper() -> int:
    socket_path = os.environ.get("KWS_PLAN_RUNNER_HELPER_SOCKET")
    nonce = os.environ.get("KWS_PLAN_RUNNER_HELPER_NONCE")
    if not socket_path or not nonce:
        raise ValueError("helper environment is incomplete")
    request = json.load(sys.stdin)
    if not isinstance(request, dict):
        raise ValueError("helper request must be one object")
    response = helper_client(Path(socket_path), nonce, request)
    print(json.dumps(response, sort_keys=True))
    return 0


def _invalid(detail: str) -> int:
    print(
        json.dumps(
            {
                "status": "failed",
                "reason_code": "invalid_invocation",
                "detail": detail,
            },
            sort_keys=True,
        )
    )
    return int(ExitCode.INVALID)


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    if raw_arguments == ["_helper"]:
        try:
            return _helper()
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "reason_code": "helper_request_failed",
                        "detail": str(error)[:512],
                    },
                    sort_keys=True,
                )
            )
            return int(ExitCode.INTEGRITY)
    arguments = _parser().parse_args(raw_arguments)
    try:
        runtime = require_compatible_runtime()
    except RuntimeUnavailable as error:
        reason = str(error)
        if reason not in {"runtime_missing", "runtime_incompatible"}:
            reason = "runtime_incompatible"
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason_code": reason,
                    "detail": "required uv-managed CPython 3.13 runtime is unavailable",
                },
                sort_keys=True,
            )
        )
        return int(ExitCode.BLOCKED)
    runner = PlanRunner(_paths(), runtime_checker=lambda: runtime)
    if arguments.command == "run":
        return runner.create_run(
            specs=arguments.spec,
            plans=arguments.plan,
            workspace=arguments.workspace,
            stall_seconds=arguments.stall_seconds,
            model=arguments.model,
        )
    if arguments.command == "resume":
        if arguments.strategy_note is not None and not arguments.retry_failed:
            return _invalid("--strategy-note requires --retry-failed")
        if arguments.retry_failed and not (
            arguments.strategy_note and arguments.strategy_note.strip()
        ):
            return _invalid("--retry-failed requires --strategy-note")
        return runner.resume(
            arguments.run_id,
            retry_blocked=arguments.retry_blocked,
            retry_failed=arguments.retry_failed,
            strategy_note=arguments.strategy_note,
        )
    return runner.inspect(arguments.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
