#!/usr/bin/env python3
"""Deterministic claude CLI stand-in for CLPE evals."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time


def emit(event):
    print(json.dumps(event), flush=True)


def run_git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def make_commit():
    with open("clpe-fake-change.txt", "a", encoding="utf-8") as handle:
        handle.write("change\n")
    run_git("add", "-A")
    run_git("commit", "-m", "fake: implement plan")
    return run_git("rev-parse", "HEAD").stdout.strip()


def main():
    argv = sys.argv[1:]
    scenario = os.environ.get("CLPE_FAKE_SCENARIO", "completed")
    if "--resume" in argv:
        scenario = os.environ.get("CLPE_FAKE_RESUME_SCENARIO", scenario)
    log_path = os.environ.get("CLPE_FAKE_ARGV_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(json.dumps({
                "argv": argv,
                "cwd": os.getcwd(),
                "env_has_claudecode": "CLAUDECODE" in os.environ,
                "env_has_entrypoint": "CLAUDE_CODE_ENTRYPOINT" in os.environ,
            }) + "\n")
    if "--json-schema" in argv:
        schema_value = argv[argv.index("--json-schema") + 1]
        try:
            json.loads(schema_value)
        except (ValueError, TypeError):
            print(f"Error: --json-schema is not valid JSON: {schema_value[:40]}",
                  file=sys.stderr)
            return 1
    if scenario == "invalid":
        print("this is not stream json")
        return 1
    emit({"type": "system", "subtype": "init", "session_id": "sess-0001"})
    if scenario == "timeout":
        time.sleep(int(os.environ.get("CLPE_FAKE_SLEEP", "30")))
        return 0
    result = {"type": "result", "subtype": "success",
              "session_id": "sess-0001", "total_cost_usd": 0.01}
    head = run_git("rev-parse", "HEAD").stdout.strip()
    if scenario in ("completed", "completed_dirty", "completed_wrong_head"):
        head = make_commit()
        if scenario == "completed_dirty":
            with open("untracked.txt", "w", encoding="utf-8") as handle:
                handle.write("dirty\n")
        reported = ("deadbeef" * 5 if scenario == "completed_wrong_head" else head)
        result["structured_output"] = {
            "status": "completed", "head_commit": reported,
            "summary": "plan executed", "open_findings": [],
        }
    elif scenario == "failed":
        result["structured_output"] = {
            "status": "failed", "head_commit": head,
            "summary": "could not finish", "open_findings": ["tests failing"],
        }
    elif scenario == "blocked":
        result["structured_output"] = {
            "status": "blocked", "head_commit": head,
            "summary": "blocked on environment", "open_findings": [],
            "blocker": {"kind": "env_missing_tool", "detail": "docker unavailable"},
        }
    elif scenario == "max_turns":
        result["subtype"] = "error_max_turns"
    elif scenario == "rate_limit":
        # INFERRED shape: real CLI emits a rate_limit_event; the exact non-"allowed"
        # status string is unverified against a real rate-limit block.
        emit({"type": "rate_limit_event", "session_id": "sess-0001",
              "rate_limit_info": {"status": "rejected"}})
        result["subtype"] = "error_during_execution"
    elif scenario == "auth":
        # INFERRED shape: real CLI surfaces API errors on the result event's
        # api_error_status; exact value + usage-vs-auth distinction unverified.
        result["subtype"] = "error_during_execution"
        result["api_error_status"] = "Unauthorized"
        result["is_error"] = True
    elif scenario == "success_no_structured":
        pass
    else:
        raise SystemExit(f"unknown scenario: {scenario}")
    emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
