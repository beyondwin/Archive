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
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _kill_group(child, signal.SIGKILL)
                child.wait()
            return LaunchOutcome("timed_out", None,
                                 f"timed out after {timeout_seconds}s")
