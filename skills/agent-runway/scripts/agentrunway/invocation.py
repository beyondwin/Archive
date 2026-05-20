from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from . import __version__
from .resolver import ResolutionError, resolve_run_alias, resolve_run_inputs, write_last_run


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
    run.add_argument("--plan", type=Path)
    run.add_argument("--spec", type=Path)
    run.add_argument("--topic")
    run.add_argument("--latest", action="store_true")
    run.add_argument("--model-profile")
    run.add_argument("--base-ref", default="HEAD")
    run.add_argument("--allow-dirty-source", action="store_true")
    run.add_argument("--detach", action="store_true")
    run.add_argument("--run-id", help=argparse.SUPPRESS)
    run.add_argument("--apply-to-source", action="store_true")
    run.add_argument("--planning-only", action="store_true")
    run.add_argument("--adapter", default="local")
    run.add_argument("--fake-success", action="store_true")

    for command in ("status", "inspect", "events", "resume", "cancel"):
        cmd = sub.add_parser(command, help=f"{command} a AgentRunway run")
        cmd.add_argument("--run")
        cmd.add_argument("--last", action="store_true")
        if command in {"status", "inspect", "events", "resume"}:
            cmd.add_argument("--json", action="store_true")
        if command == "events":
            cmd.add_argument("--type")
        if command == "resume":
            cmd.add_argument("--dry-run", action="store_true")
    apply_parser = sub.add_parser("apply", help="apply a AgentRunway run")
    apply_parser.add_argument("--run")
    apply_parser.add_argument("--last", action="store_true")
    apply_parser.add_argument("--strategy", default="cherry-pick", choices=("cherry-pick",))
    clean = sub.add_parser("clean", help="clean retained AgentRunway artifacts")
    clean.add_argument("--older-than", default="7d")
    clean.add_argument("--successful", action="store_true")
    clean.add_argument("--dry-run", action="store_true", default=True)
    clean.add_argument("--apply", action="store_true")
    return parser


def parse_run_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    input_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(input_argv)
    if args.command is None:
        parser.print_help()
        return 0
    from . import runner

    try:
        repo_root = Path.cwd().resolve()
        if args.command == "run":
            resolved = resolve_run_inputs(
                repo_root=repo_root,
                plan=args.plan,
                spec=args.spec,
                topic=args.topic,
                latest=bool(args.latest),
                adapter=args.adapter,
            )
            args.plan = resolved.plan_path
            args.spec = resolved.spec_path
            args.adapter = resolved.adapter
            if args.detach:
                from .detach import build_detached_argv, launch_detached, python_executable, script_path

                run_id = args.run_id or runner.allocate_run_id(repo_root, args.plan)
                wsid = runner.workspace_id(repo_root)
                run_dir, _ = runner._state_paths(run_id, wsid)
                reentry = [
                    "run",
                    "--plan",
                    str(args.plan),
                    "--adapter",
                    str(args.adapter),
                    "--base-ref",
                    str(args.base_ref),
                ]
                if args.spec:
                    reentry.extend(["--spec", str(args.spec)])
                if args.model_profile:
                    reentry.extend(["--model-profile", str(args.model_profile)])
                if args.allow_dirty_source:
                    reentry.append("--allow-dirty-source")
                if args.apply_to_source:
                    reentry.append("--apply-to-source")
                if args.planning_only:
                    reentry.append("--planning-only")
                if args.fake_success:
                    reentry.append("--fake-success")
                detached_argv = build_detached_argv(
                    executable=python_executable(),
                    script=script_path(),
                    original_argv=reentry,
                    invocation_cwd=repo_root,
                    run_id=run_id,
                )
                launch = launch_detached(argv=detached_argv, cwd=repo_root, run_id=run_id, run_dir=run_dir)
                payload = {
                    "run_id": launch.run_id,
                    "status": "detached",
                    "pid": launch.pid,
                    "pidfile": launch.pidfile,
                    "stdout_path": launch.stdout_path,
                    "stderr_path": launch.stderr_path,
                }
                write_last_run(repo_root, run_id)
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                return 0
            payload = runner.run(args)
            if isinstance(payload, dict) and payload.get("run_id"):
                write_last_run(repo_root, str(payload["run_id"]))
        elif args.command == "status":
            payload = runner.status(resolve_run_alias(repo_root, args.run, bool(args.last)))
        elif args.command == "inspect":
            payload = runner.inspect(resolve_run_alias(repo_root, args.run, bool(args.last)))
        elif args.command == "events":
            payload = runner.events(resolve_run_alias(repo_root, args.run, bool(args.last)), event_type=args.type)
        elif args.command == "resume":
            payload = runner.resume(resolve_run_alias(repo_root, args.run, bool(args.last)), dry_run=bool(args.dry_run))
        elif args.command == "cancel":
            payload = runner.cancel(resolve_run_alias(repo_root, args.run, bool(args.last)))
        elif args.command == "apply":
            payload = runner.apply(resolve_run_alias(repo_root, args.run, bool(args.last)), strategy=args.strategy)
        elif args.command == "clean":
            payload = runner.clean(args.older_than, successful=args.successful, dry_run=not bool(args.apply))
        else:
            parser.error(f"unknown command: {args.command}")
    except ResolutionError as exc:
        error_payload = {"error": str(exc)}
        error_payload.update(exc.payload)
        print(json.dumps(error_payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc), "command": args.command}), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if isinstance(payload, dict) and payload.get("status") == "missing":
        return 1
    return 0
