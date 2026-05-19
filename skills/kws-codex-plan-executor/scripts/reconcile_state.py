#!/usr/bin/env python3
"""Detect and optionally repair safe executor state drift."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SAFE_REPAIRS = {
    "stale-root-state-pointer",
    "missing-event-journal-path",
    "stale-last-event-seq",
    "missing-context-health-timestamp",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def expected_event_journal_path(run_id: str) -> str:
    return f".codex-orchestrator/runs/{run_id}/events.jsonl"


def repo_root_for_state(state_path: Path) -> Path:
    return state_path.resolve().parents[3]


def read_last_seq(journal_path: Path, run_id: str) -> int:
    last_seq = 0
    for line_no, line in enumerate(journal_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("run_id") != run_id:
            raise ValueError(f"events.jsonl line {line_no} run_id mismatch")
        seq = event.get("seq")
        if not isinstance(seq, int) or seq <= last_seq:
            raise ValueError(f"events.jsonl line {line_no} has non-monotonic seq")
        last_seq = seq
    return last_seq


def record(drift_type: str, severity: str, message: str, repair: str = "") -> dict:
    return {
        "type": drift_type,
        "severity": severity,
        "detected_at": now_iso(),
        "message": message,
        "repair": repair,
        "repaired_at": None,
    }


def detect_stale_root_state_pointer(state: dict, state_path: Path) -> list[dict]:
    root_state_path = repo_root_for_state(state_path) / ".codex-orchestrator" / "state.json"
    expected_state_path = state.get("state_path")
    if not isinstance(expected_state_path, str) or not expected_state_path:
        return []
    try:
        root_state = json.loads(root_state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [
            record(
                "stale-root-state-pointer",
                "repairable",
                "root compatibility state is missing",
                "write latest_run_id, run_dir, and state_path from per-run state",
            )
        ]
    except json.JSONDecodeError:
        return [
            record(
                "stale-root-state-pointer",
                "repairable",
                "root compatibility state is not valid JSON",
                "rewrite root compatibility state from per-run state",
            )
        ]
    if root_state.get("state_path") == expected_state_path and root_state.get("latest_run_id") == state.get("run_id"):
        return []
    return [
        record(
            "stale-root-state-pointer",
            "repairable",
            "root compatibility state does not point at this run",
            "write latest_run_id, run_dir, and state_path from per-run state",
        )
    ]


def detect_missing_event_journal_path(state: dict, state_path: Path) -> list[dict]:
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return []
    journal_path = state_path.parent / "events.jsonl"
    if not journal_path.is_file() or state.get("event_journal_path") == expected_event_journal_path(run_id):
        return []
    return [
        record(
            "missing-event-journal-path",
            "repairable",
            "events.jsonl exists but state.event_journal_path is missing or stale",
            f"set event_journal_path to {expected_event_journal_path(run_id)}",
        )
    ]


def detect_stale_last_event_seq(state: dict, state_path: Path) -> list[dict]:
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return []
    journal_path = state_path.parent / "events.jsonl"
    if not journal_path.is_file():
        return []
    try:
        last_seq = read_last_seq(journal_path, run_id)
    except ValueError as exc:
        return [record("journal-run-id-mismatch", "blocking", str(exc))]
    if state.get("last_event_seq") == last_seq:
        return []
    return [
        record(
            "stale-last-event-seq",
            "repairable",
            f"state.last_event_seq is {state.get('last_event_seq')} but events.jsonl ends at {last_seq}",
            f"set state.last_event_seq to {last_seq}",
        )
    ]


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
                records.append(
                    record(
                        "finished-with-open-carried-acceptance",
                        "blocking",
                        f"{task_id} has open carried_acceptance",
                    )
                )
    return records


def detect_completed_task_missing_unit_manifest(state: dict, state_path: Path) -> list[dict]:
    if state.get("lifecycle_outcome") != "finished":
        return []
    records = []
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return []
    for task_id, task in tasks.items():
        if isinstance(task, dict) and task.get("status") in {"completed", "verified", "done"}:
            if not isinstance(task.get("unit_manifest"), dict):
                records.append(
                    record(
                        "completed-task-missing-unit-manifest",
                        "blocking",
                        f"{task_id} is completed but missing unit_manifest",
                    )
                )
    return records


def detect_context_basis_hash_mismatch(state: dict, state_path: Path) -> list[dict]:
    context_path_value = state.get("context_snapshot_path")
    state_hash = state.get("context_basis_hash")
    if not isinstance(context_path_value, str) or not isinstance(state_hash, str):
        return []
    context_path = repo_root_for_state(state_path) / context_path_value
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if context.get("basis_hash") == state_hash:
        return []
    return [
        record(
            "context-basis-hash-mismatch",
            "blocking",
            "state.context_basis_hash differs from context.json basis_hash",
        )
    ]


DETECTORS = [
    detect_stale_root_state_pointer,
    detect_missing_context_health_timestamp,
    detect_missing_event_journal_path,
    detect_stale_last_event_seq,
    detect_finished_with_open_carried_acceptance,
    detect_completed_task_missing_unit_manifest,
    detect_context_basis_hash_mismatch,
]


def detect(state: dict, state_path: Path) -> list[dict]:
    records: list[dict] = []
    for detector in DETECTORS:
        records.extend(detector(state, state_path))
    return records


def apply_repairs(state: dict, state_path: Path, records: list[dict]) -> list[dict]:
    repaired: list[dict] = []
    root_state_path = repo_root_for_state(state_path) / ".codex-orchestrator" / "state.json"
    run_id = state.get("run_id")
    for item in records:
        drift_type = item.get("type")
        if drift_type not in SAFE_REPAIRS:
            continue
        if drift_type == "stale-root-state-pointer":
            root_state_path.parent.mkdir(parents=True, exist_ok=True)
            root_state_path.write_text(
                json.dumps(
                    {
                        "latest_run_id": state.get("run_id"),
                        "run_dir": state.get("run_dir"),
                        "state_path": state.get("state_path"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        elif drift_type == "missing-context-health-timestamp":
            state["context_health"]["last_checked_at"] = state["timestamps"]["updated_at"]
        elif drift_type == "missing-event-journal-path" and isinstance(run_id, str):
            state["event_journal_path"] = expected_event_journal_path(run_id)
        elif drift_type == "stale-last-event-seq" and isinstance(run_id, str):
            state["last_event_seq"] = read_last_seq(state_path.parent / "events.jsonl", run_id)
        item["repaired_at"] = now_iso()
        repaired.append(item)
    return repaired


def reconcile(state_path: Path, repair_safe: bool) -> tuple[dict, int]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    records = detect(state, state_path)
    repaired: list[dict] = []
    if repair_safe:
        repaired = apply_repairs(state, state_path, records)

    blockers = [item for item in records if item.get("severity") == "blocking"]
    drift = state.get("drift") if isinstance(state.get("drift"), dict) else {}
    drift["last_checked_at"] = now_iso()
    drift["records"] = records
    drift["unrepaired_blockers"] = blockers
    state["drift"] = drift
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if repair_safe and repaired:
        # v2.18 cutover: legacy events.jsonl journal + scripts/append_run_event.py
        # were removed. drift_repaired evidence now lives only in state.drift.records.
        # AgentLens emits a `kws-cpe.drift_repaired`-style event from the
        # orchestrator boundary, not from this reconciliation script.
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("lifecycle_outcome") == "finished":
            health = state.get("context_health")
            timestamps = state.get("timestamps")
            if isinstance(health, dict) and isinstance(timestamps, dict) and timestamps.get("updated_at"):
                health["last_checked_at"] = timestamps["updated_at"]
                drift = state.get("drift")
                if isinstance(drift, dict):
                    drift["last_checked_at"] = timestamps["updated_at"]
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
        payload, status = reconcile(Path(args.state).resolve(), repair_safe=args.repair_safe)
    except Exception as exc:
        print(json.dumps({"passed": False, "records": [], "unrepaired_blockers": [], "error": str(exc)}))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
