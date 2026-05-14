#!/usr/bin/env python3
"""Per-run sharded learning event helper for kws-claude-multi-agent-executor.

Subcommands: init-run / append / close-run / append-session-id.

Layout:
    ~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/
    ├── meta.json
    └── events.jsonl

The orchestrator is the only intended caller. Sub-agents prepare candidate
JSON files under <worktree>/.orchestrator/learning_events/<task_id>-<role>.json;
the orchestrator reads them and invokes `append`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_LOG_ROOT = Path("~/.claude/learning/kws-claude-multi-agent-executor").expanduser()

VALID_PHASES = {"phase_0", "phase_1", "phase_transition", "phase_2"}
VALID_RISK_TIERS = {"LOW", "MID", "HIGH", None}
VALID_EVENT_TYPES = {
    "blocker",
    "error",
    "verification_failure",
    "reviewer_warn_or_fail",
    "escalation",
    "recurring_issue",
    "user_correction",
    "parallel_dispatch_failure",
    "successful_workaround",
    "completion_learning",
    "context_health",
}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_OUTCOMES = {"success", "blocked", "aborted", "unknown"}
VALID_SUBAGENT_ROLES = {
    "implementer", "reviewer", "verifier", "documenter",
    "plan_reviewer", "orchestrator",
}
VALID_SUBAGENT_DISPATCH = {"agent_tool", "claude_p", "orchestrator"}

REQUIRED_FIELDS = {
    "schema_version", "run_id", "skill", "skill_version", "phase",
    "event_type", "severity", "execution", "subagent", "summary",
    "context", "improvement", "privacy",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|cookie|private[_-]?key)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
]

MAX_SUMMARY_CHARS = 500
MAX_EXCERPT_CHARS = 400


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_micro_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def utc_compact_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def build_run_id(session_id: str | None, pid: int) -> str:
    short = (session_id or "nosession").replace("-", "")[:8] or "nosession"
    return f"{utc_compact_now()}-{short}-{pid}"


def parse_run_date(run_id: str) -> str:
    if "T" not in run_id:
        die(f"malformed run_id: {run_id}")
    date_part = run_id.split("T", 1)[0]
    if len(date_part) != 8 or not date_part.isdigit():
        die(f"malformed run_id date: {run_id}")
    return f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}"


def run_dir_for(log_root: Path, run_id: str) -> Path:
    return log_root / "runs" / parse_run_date(run_id) / run_id


def contains_secret_like(value: str) -> bool:
    return any(p.search(value) for p in SECRET_PATTERNS)


def relativize(value: str, repo_root: Path | None) -> str:
    if not isinstance(value, str) or not value:
        return value
    home = str(Path.home())
    if value == home or value.startswith(home + os.sep):
        die(f"absolute home path is not allowed: {value}")
    if repo_root is not None:
        try:
            candidate = Path(value).expanduser()
        except (OSError, ValueError):
            return value
        if candidate.is_absolute():
            try:
                resolved = candidate.resolve(strict=False)
                rel = resolved.relative_to(repo_root.resolve(strict=False))
                return rel.as_posix()
            except ValueError:
                return value
    return value


def sanitize(value: Any, repo_root: Path | None) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize(v, repo_root) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, repo_root) for v in value]
    if isinstance(value, str):
        if contains_secret_like(value):
            die(f"secret-like value rejected: {value[:60]}...")
        return relativize(value, repo_root)
    return value


def require_object(data: Any, field: str) -> dict:
    item = data.get(field)
    if not isinstance(item, dict):
        die(f"{field} must be an object")
    return item


def validate_event(event: dict, expected_run_id: str) -> None:
    missing = sorted(REQUIRED_FIELDS - set(event))
    if missing:
        die("missing required field(s): " + ", ".join(missing))
    if event.get("schema_version") != "1":
        die("schema_version must be '1'")
    if event.get("skill") != "kws-claude-multi-agent-executor":
        die("skill must be kws-claude-multi-agent-executor")
    if event.get("run_id") != expected_run_id:
        die(f"event.run_id {event.get('run_id')!r} != --run-id {expected_run_id!r}")
    if event.get("phase") not in VALID_PHASES:
        die("phase must be one of: " + ", ".join(sorted(VALID_PHASES)))
    if "risk_tier" in event and event["risk_tier"] not in VALID_RISK_TIERS:
        die("risk_tier must be one of LOW/MID/HIGH/null")
    if event.get("event_type") not in VALID_EVENT_TYPES:
        die("event_type must be one of: " + ", ".join(sorted(VALID_EVENT_TYPES)))
    if event.get("severity") not in VALID_SEVERITIES:
        die("severity must be one of: " + ", ".join(sorted(VALID_SEVERITIES)))
    if not isinstance(event.get("summary"), str) or not event["summary"].strip():
        die("summary must be a non-empty string")
    if len(event["summary"]) > MAX_SUMMARY_CHARS:
        die(f"summary exceeds {MAX_SUMMARY_CHARS} chars")
    require_object(event, "execution")
    subagent = require_object(event, "subagent")
    if subagent.get("role") not in VALID_SUBAGENT_ROLES:
        die("subagent.role must be one of: " + ", ".join(sorted(VALID_SUBAGENT_ROLES)))
    if subagent.get("dispatch") not in VALID_SUBAGENT_DISPATCH:
        die("subagent.dispatch must be one of: " + ", ".join(sorted(VALID_SUBAGENT_DISPATCH)))
    require_object(event, "context")
    require_object(event, "improvement")
    privacy = require_object(event, "privacy")
    if privacy.get("redacted") is not True:
        die("privacy.redacted must be true")
    # excerpt length cap
    for evidence in event.get("context", {}).get("evidence", []) or []:
        if isinstance(evidence, dict) and isinstance(evidence.get("value"), str):
            if len(evidence["value"]) > MAX_EXCERPT_CHARS:
                die(f"evidence value exceeds {MAX_EXCERPT_CHARS} chars; summarize")


def compute_event_id(event: dict) -> str:
    basis = "|".join([
        str(event.get("timestamp", "")),
        str(event.get("run_id", "")),
        str(event.get("event_type", "")),
        str((event.get("execution") or {}).get("task_id", "")),
        str(event.get("summary", "")),
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def load_meta(rd: Path) -> dict:
    meta_path = rd / "meta.json"
    if not meta_path.is_file():
        die(f"meta.json not found at {meta_path}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def save_meta(rd: Path, meta: dict) -> None:
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def ensure_run_dir_with_meta(log_root: Path, run_id: str, session_id: str | None) -> Path:
    """Used by `append` self-heal: create directory + minimal meta.json if missing."""
    rd = run_dir_for(log_root, run_id)
    if not (rd / "meta.json").is_file():
        rd.mkdir(parents=True, exist_ok=True)
        meta = {
            "schema_version": "1",
            "run_id": run_id,
            "skill": "kws-claude-multi-agent-executor",
            "skill_version": SKILL_VERSION,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "session_id": session_id,
            "session_ids": [session_id] if session_id else [],
            "repo": {"name": None, "branch": None, "remote_hash": None},
            "plan_path": None,
            "spec_path": None,
            "worktree_path": None,
            "started_at": utc_now_iso(),
            "ended_at": None,
            "outcome": "unknown",
            "event_count": 0,
            "self_healed": True,
        }
        save_meta(rd, meta)
    return rd


SKILL_VERSION = "2.10.2"


# ---------- subcommands ----------


def find_open_run(log_root: Path, repo_name: str, plan_path: str,
                  session_id: str | None) -> Path | None:
    """Idempotency probe: is there an existing un-closed run for the same
    (session_id, repo_name, plan_path) tuple? If so, reuse it."""
    runs_root = log_root / "runs"
    if not runs_root.is_dir():
        return None
    for date_dir in runs_root.iterdir():
        if not date_dir.is_dir():
            continue
        for run_dir in date_dir.iterdir():
            meta_path = run_dir / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("outcome") != "unknown":
                continue
            if meta.get("session_id") != session_id:
                continue
            if (meta.get("repo") or {}).get("name") != repo_name:
                continue
            if meta.get("plan_path") != plan_path:
                continue
            return run_dir
    return None


def cmd_init_run(args: argparse.Namespace) -> int:
    log_root: Path = Path(args.log_root).expanduser()
    repo_root: Path = Path(args.repo_root).expanduser().resolve(strict=False)
    session_id = args.session_id or os.environ.get("CLAUDE_SESSION_ID") or None
    pid = os.getpid()

    # Idempotent: if an open run already exists for this (session_id, repo_name,
    # plan_path), reuse it.
    existing = find_open_run(log_root, args.repo_name, args.plan_path, session_id)
    if existing is not None:
        meta = json.loads((existing / "meta.json").read_text(encoding="utf-8"))
        print(meta["run_id"])
        return 0

    run_id = build_run_id(session_id, pid)
    rd = run_dir_for(log_root, run_id)
    if (rd / "meta.json").is_file():
        # Same run_id collision (very rare; same session+pid+second).
        existing_meta = load_meta(rd)
        print(existing_meta["run_id"])
        return 0
    rd.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema_version": "1",
        "run_id": run_id,
        "skill": "kws-claude-multi-agent-executor",
        "skill_version": SKILL_VERSION,
        "host": socket.gethostname(),
        "pid": pid,
        "session_id": session_id,
        "session_ids": [session_id] if session_id else [],
        "repo": {
            "name": args.repo_name,
            "branch": args.branch,
            "remote_hash": None,
        },
        "plan_path": args.plan_path,
        "spec_path": args.spec_path,
        "worktree_path": str(repo_root),
        "started_at": utc_now_iso(),
        "ended_at": None,
        "outcome": "unknown",
        "event_count": 0,
    }
    save_meta(rd, meta)
    print(run_id)
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    log_root: Path = Path(args.log_root).expanduser()
    repo_root: Path | None = (
        Path(args.repo_root).expanduser().resolve(strict=False) if args.repo_root else None
    )
    run_id = args.run_id

    try:
        candidate = json.loads(Path(args.event_json).expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"event candidate not found: {args.event_json}")
    except json.JSONDecodeError as exc:
        die(f"event JSON is invalid: {exc}")

    if not isinstance(candidate, dict):
        die("event JSON root must be an object")

    # Reject run_id mismatch BEFORE sanitize/overwrite — protects against
    # cross-run event leakage if the orchestrator misroutes a candidate file.
    candidate_run_id = candidate.get("run_id")
    if candidate_run_id is not None and candidate_run_id != run_id:
        die(f"event.run_id {candidate_run_id!r} does not match --run-id {run_id!r}")

    event = sanitize(candidate, repo_root)
    event.setdefault("timestamp", utc_now_micro_iso())
    event["skill"] = "kws-claude-multi-agent-executor"
    event["skill_version"] = SKILL_VERSION
    event["run_id"] = run_id
    validate_event(event, run_id)
    event["event_id"] = compute_event_id(event)

    line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    if args.dry_run:
        print(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    # Self-heal does not know the session id. The orchestrator's init-run
    # is the authoritative source; this fallback only runs when init-run
    # was skipped entirely.
    rd = ensure_run_dir_with_meta(log_root, run_id, None)
    events_path = rd / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(f"event_id {event['event_id']}")
    return 0


def _rewrite_index_outcome(log_root: Path, run_id: str, outcome: str) -> bool:
    """Atomic rewrite of index.jsonl: update the matching run_id row's outcome.

    Returns True on rewrite, False if no matching row was found.
    """
    index_path = log_root / "index.jsonl"
    if not index_path.is_file():
        return False

    # Hold a lock on the index across read + write to avoid interleaving with
    # concurrent init-run / append calls from other skills (e.g., parallel
    # codex-plan-executor runs).
    with index_path.open("r+", encoding="utf-8") as src:
        fcntl.flock(src.fileno(), fcntl.LOCK_EX)
        rows = []
        rewritten = False
        for line in src:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                rows.append(line)
                continue
            if row.get("run_id") == run_id:
                row["outcome"] = outcome
                rewritten = True
            rows.append(json.dumps(row, sort_keys=True, separators=(",", ":")))

        if not rewritten:
            return False

        tmp = tempfile.NamedTemporaryFile("w", delete=False,
                                          dir=index_path.parent,
                                          prefix=".index.", suffix=".tmp")
        try:
            tmp.write("\n".join(rows) + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, index_path)
        except Exception:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise
        return True


def cmd_close_run(args: argparse.Namespace) -> int:
    log_root: Path = Path(args.log_root).expanduser()
    if args.outcome not in VALID_OUTCOMES:
        die("outcome must be one of: " + ", ".join(sorted(VALID_OUTCOMES)))
    rd = run_dir_for(log_root, args.run_id)
    if not (rd / "meta.json").is_file():
        rd = ensure_run_dir_with_meta(log_root, args.run_id, None)
    meta = load_meta(rd)
    events_path = rd / "events.jsonl"
    if events_path.is_file():
        event_count = sum(1 for _ in events_path.open("r", encoding="utf-8"))
    else:
        event_count = 0
    meta["ended_at"] = utc_now_iso()
    meta["outcome"] = args.outcome
    meta["event_count"] = event_count
    save_meta(rd, meta)
    try:
        _rewrite_index_outcome(log_root, args.run_id, args.outcome)
    except OSError as exc:
        # Index rewrite is best-effort; surface to stderr but don't abort.
        # The resolver will still find the outcome via final.json.
        print(f"warning: failed to rewrite index outcome for {args.run_id}: {exc}",
              file=sys.stderr)
    print(f"closed {args.run_id} outcome={args.outcome} events={event_count}")
    return 0


def cmd_append_session_id(args: argparse.Namespace) -> int:
    log_root: Path = Path(args.log_root).expanduser()
    rd = run_dir_for(log_root, args.run_id)
    if not (rd / "meta.json").is_file():
        rd = ensure_run_dir_with_meta(log_root, args.run_id, args.session_id)
    meta = load_meta(rd)
    sids = meta.get("session_ids") or []
    if args.session_id and args.session_id not in sids:
        sids.append(args.session_id)
    meta["session_ids"] = sids
    save_meta(rd, meta)
    print(f"session_ids[]={sids}")
    return 0


def cmd_resolve_outcome(args) -> int:
    log_root = Path(args.log_root or DEFAULT_LOG_ROOT).expanduser()
    run_id = args.run_id
    date_dir = log_root / "runs" / f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]}"
    run_dir = date_dir / run_id

    sources_checked = []
    outcome = None
    source = None

    final_path = run_dir / "final.json"
    if final_path.is_file():
        sources_checked.append(str(final_path))
        try:
            data = json.loads(final_path.read_text(encoding="utf-8"))
            outcome = data.get("outcome")
            source = "final.json"
        except (json.JSONDecodeError, OSError):
            pass

    if outcome is None:
        meta_path = run_dir / "meta.json"
        if meta_path.is_file():
            sources_checked.append(str(meta_path))
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                outcome = data.get("outcome")
                source = "meta.json" if outcome and outcome != "unknown" else source
                if outcome == "unknown":
                    outcome = None
            except (json.JSONDecodeError, OSError):
                pass

    if outcome is None:
        index_path = log_root / "index.jsonl"
        if index_path.is_file():
            sources_checked.append(str(index_path))
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("run_id") == run_id:
                    outcome = row.get("outcome")
                    source = "index.jsonl"
                    break

    payload = {
        "run_id": run_id,
        "outcome": outcome or "unknown",
        "source": source,
        "sources_checked": sources_checked,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(outcome or "unknown")
    return 0


# ---------- argparser ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-run", help="create run dir + meta.json; echo run_id")
    p_init.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    p_init.add_argument("--repo-root", required=True)
    p_init.add_argument("--repo-name", required=True)
    p_init.add_argument("--branch", required=True)
    p_init.add_argument("--plan-path", required=True)
    p_init.add_argument("--spec-path", default=None)
    p_init.add_argument("--session-id", default=None)
    p_init.set_defaults(func=cmd_init_run)

    p_app = sub.add_parser("append", help="validate, sanitize, and append one event")
    p_app.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    p_app.add_argument("--run-id", required=True)
    p_app.add_argument("--event-json", required=True)
    p_app.add_argument("--repo-root", default=None)
    p_app.add_argument("--dry-run", action="store_true")
    p_app.set_defaults(func=cmd_append)

    p_close = sub.add_parser("close-run", help="finalize meta.json")
    p_close.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    p_close.add_argument("--run-id", required=True)
    p_close.add_argument("--outcome", required=True)
    p_close.set_defaults(func=cmd_close_run)

    p_sid = sub.add_parser("append-session-id", help="add a session UUID to session_ids[]")
    p_sid.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    p_sid.add_argument("--run-id", required=True)
    p_sid.add_argument("--session-id", required=True)
    p_sid.set_defaults(func=cmd_append_session_id)

    sub_resolve = sub.add_parser("resolve-outcome",
        help="Resolve terminal outcome for a run (final.json > meta.json > index.jsonl)")
    sub_resolve.add_argument("--run-id", required=True)
    sub_resolve.add_argument("--log-root", default=None,
                             help="Default: ~/.claude/learning/kws-claude-multi-agent-executor")
    sub_resolve.add_argument("--json", action="store_true",
                             help="Print full resolution metadata as JSON")
    sub_resolve.set_defaults(func=cmd_resolve_outcome)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
