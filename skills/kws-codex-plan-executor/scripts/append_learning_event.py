#!/usr/bin/env python3
"""Per-run learning event helper for kws-codex-plan-executor.

Subcommands:
  init-run   Create a user-local run directory and echo run_id.
  append     Validate, redact, and append one learning event to that run.
  close-run  Finalize run metadata and write final.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import socket
import sys
from pathlib import Path
from typing import Any


DEFAULT_LOG_ROOT = Path("~/.codex/learning/kws-codex-plan-executor").expanduser()
SKILL_VERSION = "1.8.0"
VALID_MODES = {"interactive", "headless"}
VALID_EVENT_TYPES = {
    "blocker",
    "error",
    "verification_failure",
    "recurring_issue",
    "user_correction",
    "successful_workaround",
    "completion_learning",
}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_OUTCOMES = {"success", "blocked", "error", "unknown"}
REQUIRED_FIELDS = {
    "schema_version",
    "run_id",
    "skill",
    "skill_version",
    "mode",
    "event_type",
    "severity",
    "repo",
    "execution",
    "summary",
    "context",
    "improvement",
    "privacy",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|cookie|private[_-]?key)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
]


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_micro() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def utc_compact_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned[:40] or fallback


def build_run_id(repo_name: str, branch: str, head: str) -> str:
    repo_slug = slug(repo_name, "repo")
    branch_slug = slug(branch, "branch")
    head_slug = slug(head, "nohead")[:12]
    suffix = secrets.token_hex(3)
    return f"{utc_compact_now()}-{repo_slug}-{branch_slug}-{head_slug}-{suffix}"


def parse_run_date(run_id: str) -> str:
    if "T" not in run_id:
        die(f"malformed run_id: {run_id}")
    date_part = run_id.split("T", 1)[0]
    if len(date_part) != 8 or not date_part.isdigit():
        die(f"malformed run_id date: {run_id}")
    return f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}"


def run_dir_for(log_root: Path, run_id: str) -> Path:
    return log_root / "runs" / parse_run_date(run_id) / run_id


def project_run_dir(run_id: str) -> str:
    return f".codex-orchestrator/runs/{run_id}"


def project_state_path(run_id: str) -> str:
    return f"{project_run_dir(run_id)}/state.json"


def contains_secret_like_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def relativize_path_string(value: str, repo_root: Path | None) -> str:
    if not value:
        return value
    expanded_home = str(Path.home())
    if value == expanded_home or value.startswith(expanded_home + os.sep):
        die("home path is not allowed in learning events")
    if repo_root is not None:
        try:
            candidate = Path(value).expanduser()
            if candidate.is_absolute():
                resolved = candidate.resolve(strict=False)
                rel = resolved.relative_to(repo_root)
                return rel.as_posix()
        except ValueError:
            return value
    return value


def sanitize(value: Any, repo_root: Path | None) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize(item, repo_root) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, repo_root) for item in value]
    if isinstance(value, str):
        if contains_secret_like_value(value):
            die("secret-like value is not allowed in learning events")
        return relativize_path_string(value, repo_root)
    return value


def require_object(data: Any, field: str) -> dict:
    item = data.get(field)
    if not isinstance(item, dict):
        die(f"{field} must be an object")
    return item


def validate_event(data: dict, expected_run_id: str) -> None:
    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        die("missing required field(s): " + ", ".join(missing))
    if data.get("schema_version") != "1":
        die("schema_version must be 1")
    if data.get("run_id") != expected_run_id:
        die(f"event.run_id {data.get('run_id')!r} != --run-id {expected_run_id!r}")
    if data.get("skill") != "kws-codex-plan-executor":
        die("skill must be kws-codex-plan-executor")
    if data.get("mode") not in VALID_MODES:
        die("mode must be one of: " + ", ".join(sorted(VALID_MODES)))
    if data.get("event_type") not in VALID_EVENT_TYPES:
        die("event_type must be one of: " + ", ".join(sorted(VALID_EVENT_TYPES)))
    if data.get("severity") not in VALID_SEVERITIES:
        die("severity must be one of: " + ", ".join(sorted(VALID_SEVERITIES)))
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        die("summary must be a non-empty string")
    if len(data["summary"]) > 500:
        die("summary must be 500 characters or less")
    require_object(data, "repo")
    execution = require_object(data, "execution")
    if execution.get("run_dir") != project_run_dir(expected_run_id):
        die(f"execution.run_dir must be {project_run_dir(expected_run_id)}")
    if execution.get("state_path") != project_state_path(expected_run_id):
        die(f"execution.state_path must be {project_state_path(expected_run_id)}")
    require_object(data, "context")
    require_object(data, "improvement")
    privacy = require_object(data, "privacy")
    if privacy.get("redacted") is not True:
        die("privacy.redacted must be true")


def add_event_id(data: dict) -> dict:
    basis = "|".join(
        [
            str(data.get("timestamp", "")),
            str(data.get("run_id", "")),
            str(data.get("event_type", "")),
            str((data.get("execution") or {}).get("task_id", "")),
            str(data.get("summary", "")),
        ]
    )
    data["event_id"] = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return data


def load_json_file(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"{label} not found: {path}")
    except json.JSONDecodeError as exc:
        die(f"{label} JSON is invalid: {exc}")
    if not isinstance(data, dict):
        die(f"{label} JSON root must be an object")
    return data


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_meta(run_dir: Path) -> dict:
    return load_json_file(run_dir / "meta.json", "meta")


def event_count(run_dir: Path) -> int:
    events = run_dir / "events.jsonl"
    if not events.is_file():
        return 0
    return sum(1 for _ in events.open("r", encoding="utf-8"))


def append_jsonl(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def ensure_run_dir_with_meta(log_root: Path, run_id: str) -> Path:
    run_dir = run_dir_for(log_root, run_id)
    if not (run_dir / "meta.json").is_file():
        meta = {
            "schema_version": "1",
            "run_id": run_id,
            "skill": "kws-codex-plan-executor",
            "skill_version": SKILL_VERSION,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "repo": {"name": None, "branch": None, "remote_hash": None},
            "mode": None,
            "plan_path": None,
            "spec_path": None,
            "worktree_path": None,
            "project_run_dir": project_run_dir(run_id),
            "state_path": project_state_path(run_id),
            "started_at": utc_now(),
            "ended_at": None,
            "outcome": "unknown",
            "event_count": 0,
            "self_healed": True,
        }
        save_json(run_dir / "meta.json", meta)
    return run_dir


def cmd_init_run(args: argparse.Namespace) -> int:
    log_root = Path(args.log_root).expanduser()
    repo_root = Path(args.repo_root).expanduser().resolve(strict=False)
    run_id = build_run_id(args.repo_name, args.branch, args.head)
    run_dir = run_dir_for(log_root, run_id)
    if (run_dir / "meta.json").is_file():
        print(run_id)
        return 0

    meta = {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-codex-plan-executor",
        "skill_version": SKILL_VERSION,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "repo": {
            "name": args.repo_name,
            "branch": args.branch,
            "remote_hash": args.head,
        },
        "mode": args.mode,
        "plan_path": args.plan_path,
        "spec_path": args.spec_path,
        "worktree_path": str(repo_root),
        "project_run_dir": project_run_dir(run_id),
        "state_path": project_state_path(run_id),
        "started_at": utc_now(),
        "ended_at": None,
        "outcome": "unknown",
        "event_count": 0,
    }
    save_json(run_dir / "meta.json", meta)
    append_jsonl(
        log_root / "index.jsonl",
        {
            "schema_version": "1",
            "run_id": run_id,
            "skill": "kws-codex-plan-executor",
            "skill_version": SKILL_VERSION,
            "repo": meta["repo"],
            "mode": args.mode,
            "plan_path": args.plan_path,
            "project_run_dir": meta["project_run_dir"],
            "state_path": meta["state_path"],
            "started_at": meta["started_at"],
            "outcome": "unknown",
        },
    )
    print(run_id)
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    log_root = Path(args.log_root).expanduser()
    repo_root = Path(args.repo_root).expanduser().resolve(strict=False) if args.repo_root else None
    candidate = load_json_file(Path(args.event_json).expanduser(), "event")
    if candidate.get("run_id") is not None and candidate.get("run_id") != args.run_id:
        die(f"event.run_id {candidate.get('run_id')!r} does not match --run-id {args.run_id!r}")

    event = sanitize(candidate, repo_root)
    event.setdefault("timestamp", utc_now_micro())
    event["skill"] = "kws-codex-plan-executor"
    event["skill_version"] = SKILL_VERSION
    event["run_id"] = args.run_id
    validate_event(event, args.run_id)
    add_event_id(event)

    if args.dry_run:
        print(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    run_dir = ensure_run_dir_with_meta(log_root, args.run_id)
    append_jsonl(run_dir / "events.jsonl", event)
    meta = load_meta(run_dir)
    meta["event_count"] = event_count(run_dir)
    save_json(run_dir / "meta.json", meta)
    print(f"event_id {event['event_id']}")
    return 0


def cmd_close_run(args: argparse.Namespace) -> int:
    if args.outcome not in VALID_OUTCOMES:
        die("outcome must be one of: " + ", ".join(sorted(VALID_OUTCOMES)))
    log_root = Path(args.log_root).expanduser()
    run_dir = ensure_run_dir_with_meta(log_root, args.run_id)
    meta = load_meta(run_dir)
    count = event_count(run_dir)
    meta["ended_at"] = utc_now()
    meta["outcome"] = args.outcome
    meta["event_count"] = count
    save_json(run_dir / "meta.json", meta)
    final = {
        "schema_version": "1",
        "run_id": args.run_id,
        "outcome": args.outcome,
        "event_count": count,
        "ended_at": meta["ended_at"],
    }
    save_json(run_dir / "final.json", final)
    print(f"closed {args.run_id} outcome={args.outcome} events={count}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    p_init = subcommands.add_parser("init-run", help="create run dir + meta.json; echo run_id")
    p_init.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    p_init.add_argument("--repo-root", required=True)
    p_init.add_argument("--repo-name", required=True)
    p_init.add_argument("--branch", required=True)
    p_init.add_argument("--head", required=True)
    p_init.add_argument("--plan-path", required=True)
    p_init.add_argument("--spec-path", default=None)
    p_init.add_argument("--mode", choices=sorted(VALID_MODES), required=True)
    p_init.set_defaults(func=cmd_init_run)

    p_append = subcommands.add_parser("append", help="validate, sanitize, and append one event")
    p_append.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    p_append.add_argument("--run-id", required=True)
    p_append.add_argument("--event-json", required=True)
    p_append.add_argument("--repo-root")
    p_append.add_argument("--dry-run", action="store_true")
    p_append.set_defaults(func=cmd_append)

    p_close = subcommands.add_parser("close-run", help="finalize run metadata and final.json")
    p_close.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    p_close.add_argument("--run-id", required=True)
    p_close.add_argument("--outcome", choices=sorted(VALID_OUTCOMES), required=True)
    p_close.set_defaults(func=cmd_close_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
