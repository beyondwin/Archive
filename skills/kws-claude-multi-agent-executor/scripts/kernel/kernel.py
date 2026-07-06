#!/usr/bin/env python3
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import initcmd as _initcmd


def handle_init(args):
    home = os.environ.get("CME_HOME", os.path.expanduser("~"))
    repo_root = args.repo_root or os.getcwd()
    raw_args = args.args or ""
    dry_run = bool(args.dry_run)
    result = _initcmd.run_init(
        raw_args=raw_args,
        home=home,
        repo_root=repo_root,
        dry_run=dry_run,
    )
    return result

def handle_next(args):
    return {"error": "not_implemented"}

def handle_submit(args):
    return {"error": "not_implemented"}

def handle_check_stop(args):
    return {"error": "not_implemented"}

def handle_finalize(args):
    return {"error": "not_implemented"}

def handle_inspect(args):
    return {"error": "not_implemented"}

def main():
    parser = argparse.ArgumentParser(description="CME v3.0 Deterministic Kernel")
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # init: no --state required
    parser_init = subparsers.add_parser("init", help="Initialize kernel")
    parser_init.add_argument("--args", default="", help="CME args string (plan=... spec=...)")
    parser_init.add_argument("--dry-run", action="store_true",
                             help="Plan only; no filesystem changes")
    parser_init.add_argument("--repo-root", default=None,
                             help="Source repo root (defaults to cwd)")

    # next: requires --state
    parser_next = subparsers.add_parser("next", help="Next transition")
    parser_next.add_argument("--state", required=True, help="State file path")

    # submit: requires --state
    parser_submit = subparsers.add_parser("submit", help="Submit result")
    parser_submit.add_argument("--state", required=True, help="State file path")

    # check-stop: requires --state
    parser_check_stop = subparsers.add_parser("check-stop", help="Check stop condition")
    parser_check_stop.add_argument("--state", required=True, help="State file path")

    # finalize: requires --state
    parser_finalize = subparsers.add_parser("finalize", help="Finalize execution")
    parser_finalize.add_argument("--state", required=True, help="State file path")

    # inspect: requires --state
    parser_inspect = subparsers.add_parser("inspect", help="Inspect state")
    parser_inspect.add_argument("--state", required=True, help="State file path")

    args = parser.parse_args()

    handlers = {
        "init": handle_init,
        "next": handle_next,
        "submit": handle_submit,
        "check-stop": handle_check_stop,
        "finalize": handle_finalize,
        "inspect": handle_inspect,
    }

    if args.command not in handlers:
        result = {"error": "not_implemented"}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(3)

    result = handlers[args.command](args)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Exit with code 3 if result contains an error (not a halt)
    if "error" in result:
        sys.exit(3)
    # Exit code 2 for a halt (e.g. dirty_worktree)
    if "halt" in result:
        sys.exit(2)

if __name__ == "__main__":
    main()
