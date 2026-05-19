#!/usr/bin/env python3
"""Append, supersede, and render kws-cpe decisions_register entries."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


DECISION_ID_RE = re.compile(r"^dec_(\d{4})$")


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        die(f"state is not readable: {path}: {exc}")
    except json.JSONDecodeError as exc:
        die(f"state is invalid JSON: {path}: {exc}")
    if not isinstance(state, dict):
        die("state must be a JSON object")
    if not isinstance(state.get("decisions_register", []), list):
        die("state.decisions_register must be a list")
    state.setdefault("decisions_register", [])
    return state


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def next_decision_id(decisions: list[dict]) -> str:
    highest = 0
    for decision in decisions:
        match = DECISION_ID_RE.match(str(decision.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"dec_{highest + 1:04d}"


def parse_files(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def append_decision(state: dict, task: str, decision: str, files: list[str], supersedes: str | None = None, reason: str | None = None) -> dict:
    decisions = state["decisions_register"]
    entry = {
        "id": next_decision_id(decisions),
        "task": task,
        "decision": decision,
        "files": files,
        "made_at": now_iso(),
        "supersedes": supersedes,
        "superseded_by": None,
        "reason": reason,
    }
    decisions.append(entry)
    return entry


def find_decision(decisions: list[dict], decision_id: str) -> dict:
    for decision in decisions:
        if decision.get("id") == decision_id:
            return decision
    die(f"unknown decision id: {decision_id}")


def escape_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_table(decisions: list[dict]) -> str:
    header = "| ID | Task | Decision | Files | Made at | Superseded by | Reason |\n"
    divider = "| --- | --- | --- | --- | --- | --- | --- |\n"
    rows = []
    for decision in decisions:
        rows.append(
            "| {id} | {task} | {decision} | {files} | {made_at} | {superseded_by} | {reason} |".format(
                id=escape_cell(decision.get("id")),
                task=escape_cell(decision.get("task")),
                decision=escape_cell(decision.get("decision")),
                files=escape_cell(", ".join(decision.get("files") or [])),
                made_at=escape_cell(decision.get("made_at")),
                superseded_by=escape_cell(decision.get("superseded_by")),
                reason=escape_cell(decision.get("reason")),
            )
        )
    return header + divider + "\n".join(rows) + ("\n" if rows else "")


def render_decisions(path: Path, decisions: list[dict]) -> None:
    if not decisions:
        path.write_text("# Decisions register (empty)\n", encoding="utf-8")
        return

    active = [decision for decision in decisions if not decision.get("superseded_by")]
    superseded = [decision for decision in decisions if decision.get("superseded_by")]
    parts = ["# Decisions register\n\n"]
    parts.append(render_table(active))
    if superseded:
        parts.append("\n## Superseded\n\n")
        parts.append(render_table(superseded))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state", required=True)
    parser.add_argument("--render", required=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append")
    add_common(append_parser)
    append_parser.add_argument("--task", required=True)
    append_parser.add_argument("--decision", required=True)
    append_parser.add_argument("--files", default="")

    supersede_parser = subparsers.add_parser("supersede")
    add_common(supersede_parser)
    supersede_parser.add_argument("--decision-id", required=True)
    supersede_parser.add_argument("--by-task", required=True)
    supersede_parser.add_argument("--reason", required=True)

    args = parser.parse_args()
    state_path = Path(args.state).expanduser()
    state = load_state(state_path)
    decisions = state["decisions_register"]

    if args.command == "append":
        entry = append_decision(state, args.task, args.decision, parse_files(args.files))
    else:
        prior = find_decision(decisions, args.decision_id)
        if prior.get("superseded_by"):
            die(f"decision already superseded: {args.decision_id}")
        entry = append_decision(
            state,
            args.by_task,
            args.reason,
            list(prior.get("files") or []),
            supersedes=args.decision_id,
            reason=args.reason,
        )
        prior["superseded_by"] = entry["id"]
        prior["reason"] = args.reason

    save_state(state_path, state)
    render_decisions(Path(args.render).expanduser(), decisions)
    print(entry["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
