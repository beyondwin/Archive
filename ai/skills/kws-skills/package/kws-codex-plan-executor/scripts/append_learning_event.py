#!/usr/bin/env python3
"""Append a redacted kws-codex-plan-executor learning event to user-local JSONL."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path("~/.codex/learning/kws-codex-plan-executor/events.jsonl").expanduser()
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
REQUIRED_FIELDS = {
    "schema_version",
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


def validate_event(data: dict) -> None:
    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        die("missing required field(s): " + ", ".join(missing))
    if data.get("schema_version") != "1":
        die("schema_version must be 1")
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
    require_object(data, "execution")
    require_object(data, "context")
    require_object(data, "improvement")
    privacy = require_object(data, "privacy")
    if privacy.get("redacted") is not True:
        die("privacy.redacted must be true")


def add_event_id(data: dict) -> dict:
    basis = "|".join(
        [
            str(data.get("timestamp", "")),
            str((data.get("repo") or {}).get("name", "")),
            str(data.get("event_type", "")),
            str((data.get("execution") or {}).get("task_id", "")),
            str(data.get("summary", "")),
        ]
    )
    data["event_id"] = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return data


def load_event(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"event file not found: {path}")
    except json.JSONDecodeError as exc:
        die(f"event JSON is invalid: {exc}")
    if not isinstance(data, dict):
        die("event JSON root must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-json", required=True, help="Path to candidate learning event JSON")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help="JSONL log path")
    parser.add_argument("--repo-root", help="Repository root used to relativize absolute paths")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print sanitized event without appending")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve(strict=False) if args.repo_root else None
    event = sanitize(load_event(Path(args.event_json).expanduser()), repo_root)
    event.setdefault("timestamp", utc_now())
    validate_event(event)
    event = add_event_id(event)

    line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if args.dry_run:
        print(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    log_path = Path(args.log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(f"appended learning event {event['event_id']} to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
