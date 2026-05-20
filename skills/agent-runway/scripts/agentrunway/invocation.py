from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from . import __version__


COMMANDS = ("run", "status", "inspect", "events", "resume", "cancel", "apply", "clean")


def parse_key_value_invocation(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in shlex.split(text):
        if "=" not in token:
            raise ValueError(f"expected key=value token, got {token!r}")
        key, value = token.split("=", 1)
        if not key or not value:
            raise ValueError(f"empty key or value in token {token!r}")
        values[key] = value
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentrunway", description="AgentRunway deterministic runner")
    parser.add_argument("--version", action="version", version=f"agentrunway {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="start a AgentRunway run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--spec", type=Path)
    run.add_argument("--model-profile", default="codex-default")
    run.add_argument("--base-ref", default="HEAD")
    run.add_argument("--allow-dirty-source", action="store_true")
    run.add_argument("--detach", action="store_true")
    run.add_argument("--apply-to-source", action="store_true")
    run.add_argument("--planning-only", action="store_true")
    run.add_argument("--adapter", default="local")
    run.add_argument("--fake-success", action="store_true")
    run.add_argument("--skip-review", action="store_true")
    run.add_argument("--skip-verify", action="store_true")

    for command in ("status", "inspect", "events", "resume", "cancel"):
        cmd = sub.add_parser(command, help=f"{command} a AgentRunway run")
        cmd.add_argument("--run", required=True)
    apply_parser = sub.add_parser("apply", help="apply a AgentRunway run")
    apply_parser.add_argument("--run", required=True)
    apply_parser.add_argument("--strategy", default="cherry-pick", choices=("cherry-pick",))
    clean = sub.add_parser("clean", help="clean retained AgentRunway artifacts")
    clean.add_argument("--older-than", default="7d")
    clean.add_argument("--successful", action="store_true")
    return parser


def parse_run_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    from . import runner

    try:
        if args.command == "run":
            payload = runner.run(args)
        elif args.command == "status":
            payload = runner.status(args.run)
        elif args.command == "inspect":
            payload = runner.inspect(args.run)
        elif args.command == "events":
            payload = runner.events(args.run)
        elif args.command == "resume":
            payload = runner.resume(args.run)
        elif args.command == "cancel":
            payload = runner.cancel(args.run)
        elif args.command == "apply":
            payload = runner.apply(args.run, strategy=args.strategy)
        elif args.command == "clean":
            payload = runner.clean(args.older_than, successful=args.successful)
        else:
            parser.error(f"unknown command: {args.command}")
    except Exception as exc:
        print(json.dumps({"error": str(exc), "command": args.command}), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if isinstance(payload, dict) and payload.get("status") == "missing":
        return 1
    return 0
