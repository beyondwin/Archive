#!/usr/bin/env python3
"""CLPE - thin Claude plan executor: run / resume / inspect.

CLPE maintains one execution environment and verifies submitted facts.
The child Claude session's Superpowers owns all workflow semantics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = SKILL_ROOT / "templates" / "plan-result.schema.json"

SCRUB_EXACT = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT")
SCRUB_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
DENY_TOOLS = (
    "Bash(git push*)",
    "Bash(git merge*)",
    "Bash(rm -rf /*)",
    "Bash(git reset --hard origin*)",
)
DEFAULT_TIMEOUT_SECONDS = 3600
TIMEOUT_CEILING = 7200
MAX_LAUNCHES = 5

EXIT_COMPLETED = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2
EXIT_RESUMABLE = 3

PROVIDER_BLOCKED = {
    "rate_limit": "provider_usage_blocked",
    "overloaded": "provider_unavailable",
    "server_error": "provider_unavailable",
    "authentication_failed": "provider_auth_blocked",
    "oauth_org_not_allowed": "provider_auth_blocked",
    "billing_error": "provider_auth_blocked",
}

_SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}")


def validate_result_shape(obj):
    """Fail-closed shape check for the child's structured_output."""
    if not isinstance(obj, dict):
        return ["structured_output is not an object"]
    errors = []
    for key in ("status", "head_commit", "summary", "open_findings"):
        if key not in obj:
            errors.append(f"missing field: {key}")
    status = obj.get("status")
    if status not in ("completed", "blocked", "failed"):
        errors.append(f"invalid status: {status!r}")
    head = obj.get("head_commit")
    if not isinstance(head, str) or not _SHA_PATTERN.fullmatch(head):
        errors.append("head_commit is not a git sha")
    summary = obj.get("summary")
    if not isinstance(summary, str) or not summary:
        errors.append("summary is empty")
    findings = obj.get("open_findings")
    if not isinstance(findings, list) or any(
        not isinstance(item, str) for item in (findings or [])
    ):
        errors.append("open_findings is not a list of strings")
    if status == "blocked":
        blocker = obj.get("blocker")
        if (
            not isinstance(blocker, dict)
            or not blocker.get("kind")
            or not blocker.get("detail")
        ):
            errors.append("blocked result requires blocker.kind and blocker.detail")
    return errors


def parse_stream(stream_path):
    """Extract (session_id, last result event, error categories) from stream-json."""
    session_id = None
    result_event = None
    categories = []
    try:
        text = Path(stream_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if session_id is None and isinstance(event.get("session_id"), str):
            session_id = event["session_id"]
        if event.get("type") == "system" and isinstance(event.get("error"), str):
            categories.append(event["error"])
        if event.get("type") == "result":
            result_event = event
    return session_id, result_event, categories


@dataclass
class Observation:
    launch_kind: str  # "exited" | "timed_out" | "spawn_failed"
    result_event: dict | None
    session_id: str | None
    error_categories: list
    gate_failures: list
    shape_errors: list


@dataclass
class Verdict:
    status: str  # completed | failed | blocked | resumable
    exit_code: int
    detail: str
    resumable: bool


def classify(obs):
    """Spec §7 classification table. Fail closed on anything unexpected."""
    if obs.launch_kind == "spawn_failed":
        return Verdict("failed", EXIT_FAILED, "controller_spawn_failed", False)
    if obs.launch_kind == "timed_out":
        if obs.session_id:
            return Verdict("resumable", EXIT_RESUMABLE, "timed_out", True)
        return Verdict("failed", EXIT_FAILED, "timed_out_without_session", False)
    provider = next(
        (PROVIDER_BLOCKED[c] for c in obs.error_categories if c in PROVIDER_BLOCKED),
        None,
    )
    resumable = obs.session_id is not None
    event = obs.result_event
    if event is None:
        if provider:
            return Verdict("blocked", EXIT_BLOCKED, provider, False)
        return Verdict("failed", EXIT_FAILED,
                       "result_invalid: no result event", resumable)
    subtype = event.get("subtype")
    if subtype in ("error_max_turns", "error_max_budget_usd"):
        return Verdict("resumable", EXIT_RESUMABLE, str(subtype), resumable)
    if subtype != "success":
        if provider:
            return Verdict("blocked", EXIT_BLOCKED, provider, False)
        return Verdict("failed", EXIT_FAILED,
                       f"result_invalid: subtype={subtype!r}", resumable)
    structured = event.get("structured_output")
    if not structured:
        return Verdict("failed", EXIT_FAILED,
                       "result_invalid: success without structured_output", resumable)
    if obs.shape_errors:
        return Verdict("failed", EXIT_FAILED,
                       "result_invalid: " + "; ".join(obs.shape_errors), resumable)
    status = structured.get("status")
    if status == "blocked":
        return Verdict("blocked", EXIT_BLOCKED,
                       structured["blocker"]["kind"], False)
    if status == "failed":
        return Verdict("failed", EXIT_FAILED, "child_reported_failed", resumable)
    if obs.gate_failures:
        return Verdict("failed", EXIT_FAILED,
                       "completion_gate_failed: " + "; ".join(obs.gate_failures),
                       resumable)
    return Verdict("completed", EXIT_COMPLETED, "completed", False)


def scrub_env(env):
    """Remove nesting markers and secret-like vars; keep ANTHROPIC_* auth."""
    clean = {}
    for key, value in env.items():
        if key in SCRUB_EXACT:
            continue
        if not key.startswith("ANTHROPIC_") and key.endswith(SCRUB_SUFFIXES):
            continue
        clean[key] = value
    return clean


_PROHIBITIONS = (
    "Do not merge, push, deploy, or modify files outside WORKTREE.\n"
    "Do not ask the user questions; if blocked, return status \"blocked\" "
    "with a blocker object."
)

_SCHEMA_CONTRACT = (
    "Your FINAL response must be only the JSON object matching the enforced "
    "schema (status / head_commit / summary / open_findings / blocker?)."
)


def build_prompt(worktree, plan_snapshot, spec_snapshots, starting_commit, branch):
    spec_lines = "\n".join(f"- {path}" for path in spec_snapshots)
    return (
        f"WORKTREE: {worktree}\n"
        f"PLAN: {plan_snapshot}\n"
        f"SPECIFICATIONS:\n{spec_lines}\n"
        f"STARTING_COMMIT: {starting_commit}\n"
        f"BRANCH: {branch}\n"
        "\n"
        "Execute the approved implementation plan with Superpowers\n"
        "(superpowers:executing-plans). You may dispatch subagents for\n"
        "independent tasks (superpowers:subagent-driven-development) - that\n"
        "choice is yours. Commit work to the current branch.\n"
        "\n"
        f"{_SCHEMA_CONTRACT}\n"
        "\n"
        f"{_PROHIBITIONS}\n"
    )


RESUME_PROMPT = (
    "Continue executing the plan from where the session left off.\n"
    f"{_SCHEMA_CONTRACT}\n\n{_PROHIBITIONS}\n"
)


def build_argv(prompt, model=None, max_turns=None, resume_session=None):
    argv = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--json-schema", str(SCHEMA_PATH),
        "--permission-mode", "bypassPermissions",
    ]
    for rule in DENY_TOOLS:
        argv.extend(["--disallowedTools", rule])
    if resume_session:
        argv.extend(["--resume", resume_session])
    if model:
        argv.extend(["--model", model])
    if max_turns:
        argv.extend(["--max-turns", str(max_turns)])
    return argv


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)


def completion_gates(structured, worktree, starting_commit):
    """Spec §6 gates 3-6. Returns [] when the completion may be accepted."""
    status = git(["status", "--porcelain"], worktree)
    if status.returncode != 0:
        return [f"git status failed: {status.stderr.strip()}"]
    failures = []
    if status.stdout.strip():
        failures.append("worktree not clean")
    head = git(["rev-parse", "HEAD"], worktree)
    if head.returncode != 0:
        failures.append("git rev-parse HEAD failed")
        return failures
    observed = head.stdout.strip()
    reported = structured.get("head_commit") or ""
    if not observed.startswith(reported):
        failures.append(f"head mismatch: reported {reported}, observed {observed}")
    ancestor = git(["merge-base", "--is-ancestor", starting_commit, "HEAD"],
                   worktree)
    if ancestor.returncode != 0:
        failures.append("starting commit is not an ancestor of HEAD")
    if structured.get("open_findings"):
        failures.append("open_findings not empty")
    return failures


def state_home():
    return Path(os.environ.get("CLPE_HOME", str(Path.home() / ".claude"))).expanduser()


def run_dir(run_id):
    return state_home() / "clpe" / run_id


def worktree_dir(run_id):
    return state_home() / "worktrees" / run_id


def derive_run_id(plan_path):
    slug = re.sub(r"[^a-z0-9]+", "-", Path(plan_path).stem.lower()).strip("-")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{slug or 'plan'}-{stamp}"


def write_json(path, payload):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def save_run(record):
    write_json(run_dir(record["run_id"]) / "run.json", record)


def load_run(run_id):
    try:
        return json.loads((run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def snapshot_inputs(rdir, plan, specs):
    inputs = Path(rdir) / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    plan_copy = inputs / f"plan-{Path(plan).name}"
    shutil.copy2(plan, plan_copy)
    spec_copies = []
    for index, spec in enumerate(specs):
        copy = inputs / f"spec-{index}-{Path(spec).name}"
        shutil.copy2(spec, copy)
        spec_copies.append(copy)
    return plan_copy, spec_copies


@dataclass
class LaunchOutcome:
    kind: str  # "exited" | "timed_out" | "spawn_failed"
    exit_code: int | None
    detail: str


def _kill_group(child, signum):
    try:
        os.killpg(os.getpgid(child.pid), signum)
    except (ProcessLookupError, PermissionError):
        pass


def launch(argv, cwd, env, timeout_seconds, stream_path):
    try:
        stream = open(stream_path, "w", encoding="utf-8")
    except OSError as error:
        return LaunchOutcome("spawn_failed", None, str(error))
    with stream:
        try:
            child = subprocess.Popen(
                argv, cwd=str(cwd), env=env, stdout=stream,
                stderr=subprocess.PIPE, text=True, start_new_session=True,
            )
        except OSError as error:
            return LaunchOutcome("spawn_failed", None, str(error))
        try:
            _, stderr = child.communicate(timeout=timeout_seconds)
            return LaunchOutcome("exited", child.returncode,
                                 (stderr or "").strip()[-2000:])
        except subprocess.TimeoutExpired:
            _kill_group(child, signal.SIGTERM)
            try:
                child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_group(child, signal.SIGKILL)
                child.communicate()
            return LaunchOutcome("timed_out", None,
                                 f"timed out after {timeout_seconds}s")


def _timeout_floor():
    return int(os.environ.get("CLPE_TIMEOUT_FLOOR", "1200"))


def _halt(reason, detail, exit_code):
    print(json.dumps({"halt": reason, "detail": detail}))
    return exit_code


def execute_cycle(record, resume):
    record["launches"] += 1
    if resume:
        prompt = RESUME_PROMPT
        resume_session = record["session_id"]
    else:
        prompt = build_prompt(record["worktree"], record["plan"],
                              record["specs"], record["starting_commit"],
                              record["branch"])
        resume_session = None
    argv = build_argv(prompt, model=record.get("model"),
                      max_turns=record.get("max_turns"),
                      resume_session=resume_session)
    stream_path = run_dir(record["run_id"]) / f"stream-{record['launches']:02d}.jsonl"
    outcome = launch(argv, cwd=record["worktree"],
                     env=scrub_env(dict(os.environ)),
                     timeout_seconds=record["timeout_seconds"],
                     stream_path=stream_path)
    session_id, result_event, categories = parse_stream(stream_path)
    if session_id:
        record["session_id"] = session_id
    structured = (result_event or {}).get("structured_output")
    shape_errors = validate_result_shape(structured) if structured else []
    gate_failures = []
    if (result_event and result_event.get("subtype") == "success"
            and structured and not shape_errors
            and structured.get("status") == "completed"):
        gate_failures = completion_gates(structured, Path(record["worktree"]),
                                         record["starting_commit"])
    verdict = classify(Observation(
        launch_kind=outcome.kind,
        result_event=result_event,
        session_id=record["session_id"],
        error_categories=categories,
        gate_failures=gate_failures,
        shape_errors=shape_errors,
    ))
    if result_event and isinstance(result_event.get("total_cost_usd"),
                                   (int, float)):
        record["total_cost_usd"] = round(
            record["total_cost_usd"] + result_event["total_cost_usd"], 6)
    record.update({"status": verdict.status, "exit_code": verdict.exit_code,
                   "detail": verdict.detail, "resumable": verdict.resumable})
    save_run(record)
    if verdict.status == "completed":
        head = git(["rev-parse", "HEAD"], record["worktree"]).stdout.strip()
        write_json(run_dir(record["run_id"]) / "handoff.json", {
            "run_id": record["run_id"], "branch": record["branch"],
            "worktree": record["worktree"], "head": head,
            "integration": "not_observed",
        })
    print(json.dumps({
        "run_id": record["run_id"], "status": verdict.status,
        "detail": verdict.detail, "session_id": record["session_id"],
        "worktree": record["worktree"], "branch": record["branch"],
        "launches": record["launches"],
        "total_cost_usd": record["total_cost_usd"],
    }, indent=2))
    return verdict.exit_code


def cmd_run(args):
    workspace = Path(args.workspace).resolve()
    plan = Path(args.plan).resolve()
    specs = [Path(item).resolve() for item in args.spec]
    timeout_seconds = args.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    if not _timeout_floor() <= timeout_seconds <= TIMEOUT_CEILING:
        return _halt("invalid_timeout",
                     f"{timeout_seconds} not in [{_timeout_floor()}, {TIMEOUT_CEILING}]",
                     EXIT_FAILED)
    for path in [plan, *specs]:
        try:
            path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            return _halt("unreadable_input", f"{path}: {error}", EXIT_FAILED)
    status = git(["status", "--porcelain"], workspace)
    if status.returncode != 0:
        return _halt("not_a_git_workspace", status.stderr.strip(), EXIT_FAILED)
    if status.stdout.strip():
        return _halt("dirty_workspace", "commit or stash changes first",
                     EXIT_BLOCKED)
    run_id = derive_run_id(plan)
    rdir = run_dir(run_id)
    rdir.mkdir(parents=True, exist_ok=False)
    plan_copy, spec_copies = snapshot_inputs(rdir, plan, specs)
    worktree = worktree_dir(run_id)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    added = git(["worktree", "add", "-b", f"clpe/{run_id}", str(worktree)],
                workspace)
    if added.returncode != 0:
        return _halt("worktree_add_failed", added.stderr.strip(), EXIT_FAILED)
    starting = git(["rev-parse", "HEAD"], worktree).stdout.strip()
    record = {
        "run_id": run_id,
        "workspace": str(workspace),
        "worktree": str(worktree),
        "branch": f"clpe/{run_id}",
        "starting_commit": starting,
        "plan": str(plan_copy),
        "specs": [str(copy) for copy in spec_copies],
        "model": args.model,
        "max_turns": args.max_turns,
        "timeout_seconds": timeout_seconds,
        "launches": 0,
        "session_id": None,
        "status": "running",
        "exit_code": None,
        "detail": None,
        "resumable": False,
        "total_cost_usd": 0.0,
    }
    save_run(record)
    return execute_cycle(record, resume=False)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="clpe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="launch a new plan run")
    run_parser.add_argument("--spec", action="append", required=True)
    run_parser.add_argument("--plan", required=True)
    run_parser.add_argument("--workspace", required=True)
    run_parser.add_argument("--model")
    run_parser.add_argument("--max-turns", type=int, dest="max_turns")
    run_parser.add_argument("--timeout-seconds", type=int,
                            dest="timeout_seconds")
    args = parser.parse_args(argv)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
