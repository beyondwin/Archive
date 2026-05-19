#!/usr/bin/env python3
"""Detect and optionally repair safe executor state drift."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SAFE_REPAIRS = {"missing-context-health-timestamp"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record(drift_type: str, severity: str, message: str, repair: str = "") -> dict:
    return {
        "type": drift_type,
        "severity": severity,
        "detected_at": now_iso(),
        "message": message,
        "repair": repair,
        "repaired_at": None,
    }


def resolve_artifact_path(state_path: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return state_path.parent / path


def detect_missing_context_health_timestamp(state: dict, state_path: Path) -> list[dict]:
    if state.get("lifecycle_outcome") != "finished":
        return []
    health = state.get("context_health")
    timestamps = state.get("timestamps")
    if not isinstance(health, dict) or not isinstance(timestamps, dict):
        return []
    if health.get("last_checked_at"):
        return []
    updated_at = timestamps.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        return []
    return [
        record(
            "missing-context-health-timestamp",
            "repairable",
            "finished state has no context_health.last_checked_at",
            "set context_health.last_checked_at to timestamps.updated_at",
        )
    ]


def detect_finished_with_open_carried_acceptance(state: dict, state_path: Path) -> list[dict]:
    if state.get("lifecycle_outcome") != "finished":
        return []
    records = []
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return []
    for task_id, task in tasks.items():
        if isinstance(task, dict) and isinstance(task.get("carried_acceptance"), dict):
            if task["carried_acceptance"].get("status") == "open":
                records.append(record("finished-with-open-carried-acceptance", "blocking", f"{task_id} has open carried_acceptance"))
    return records


def detect_completed_task_missing_unit_manifest(state: dict, state_path: Path) -> list[dict]:
    if state.get("lifecycle_outcome") != "finished":
        return []
    records = []
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return []
    for task_id, task in tasks.items():
        if isinstance(task, dict) and str(task.get("status", "")).lower() in {"completed", "verified", "done"}:
            if not isinstance(task.get("unit_manifest"), dict):
                records.append(record("completed-task-missing-unit-manifest", "blocking", f"{task_id} is completed but missing unit_manifest"))
    return records


def detect_context_basis_hash_mismatch(state: dict, state_path: Path) -> list[dict]:
    context_path = resolve_artifact_path(state_path, state.get("context_snapshot_path"))
    state_hash = state.get("context_basis_hash")
    if context_path is None or not isinstance(state_hash, str):
        return []
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if context.get("basis_hash") == state_hash:
        return []
    return [record("context-basis-hash-mismatch", "blocking", "state.context_basis_hash differs from context.json basis_hash")]


DETECTORS = [
    detect_missing_context_health_timestamp,
    detect_finished_with_open_carried_acceptance,
    detect_completed_task_missing_unit_manifest,
    detect_context_basis_hash_mismatch,
]


def detect(state: dict, state_path: Path) -> list[dict]:
    records: list[dict] = []
    for detector in DETECTORS:
        records.extend(detector(state, state_path))
    return records


def apply_repairs(state: dict, records: list[dict]) -> list[dict]:
    repaired: list[dict] = []
    for item in records:
        if item.get("type") not in SAFE_REPAIRS:
            continue
        if item["type"] == "missing-context-health-timestamp":
            state["context_health"]["last_checked_at"] = state["timestamps"]["updated_at"]
        item["repaired_at"] = now_iso()
        repaired.append(item)
    return repaired


def reconcile(state_path: Path, repair_safe: bool) -> tuple[dict, int]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    records = detect(state, state_path)
    repaired: list[dict] = []
    if repair_safe:
        repaired = apply_repairs(state, records)
    blockers = [item for item in records if item.get("severity") == "blocking"]
    drift = state.get("drift") if isinstance(state.get("drift"), dict) else {}
    drift["last_checked_at"] = now_iso()
    drift["records"] = records
    drift["unrepaired_blockers"] = blockers
    state["drift"] = drift
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload = {
        "passed": not blockers,
        "state_path": str(state_path),
        "records": records,
        "repaired": repaired,
        "unrepaired_blockers": blockers,
    }
    return payload, 0 if not blockers else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--repair-safe", action="store_true")
    args = parser.parse_args()
    try:
        payload, status = reconcile(Path(args.state).expanduser().resolve(), repair_safe=args.repair_safe)
    except Exception as exc:
        print(json.dumps({"passed": False, "records": [], "unrepaired_blockers": [], "error": str(exc)}))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
