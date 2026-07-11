#!/usr/bin/env python3
"""Deterministic contract checks for the paid-live evidence ledger."""

from __future__ import annotations

import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from live_migration.contracts import SlotKey, canonical_json, sha256_bytes
from live_migration.ledger import (
    LedgerError,
    append_event,
    commit_slot,
    create_run,
    replay_run,
)


SLOT_FILES = {
    "invocation.json": b'{"call":1}\n',
    "codex-events.jsonl": b'{"type":"turn.completed"}\n',
    "final-output.json": b'{"status":"completed"}\n',
    "oracle.json": b'{"passed":true}\n',
    "stderr.log": b"",
}
RESULT = {
    "schema_version": "cpe-live-result.v2",
    "task_completed": True,
}


def expect_ledger_error(callable_, message: str) -> None:
    try:
        callable_()
    except LedgerError:
        return
    raise AssertionError(message)


def manifest_for(run_id: str) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "cpe-live-manifest.v2",
        "run_id": run_id,
        "slots": [
            {"treatment_id": "subscription", "case_id": "single-file"},
            {"treatment_id": "subscription", "case_id": "second-case"},
        ],
    }
    return {**body, "manifest_sha256": sha256_bytes(canonical_json(body))}


def manifest_with_slot(
    run_id: str, treatment_id: str, case_id: str
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "cpe-live-manifest.v2",
        "run_id": run_id,
        "slots": [{"treatment_id": treatment_id, "case_id": case_id}],
    }
    return {**body, "manifest_sha256": sha256_bytes(canonical_json(body))}


def event_body(event: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in event.items() if key != "event_sha256"}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-live-ledger-") as temp_dir:
        # Dot segments must be rejected before they can alter the slot hierarchy.
        for position, (treatment_id, case_id) in enumerate(
            ((".", "case"), ("..", "case"), ("treatment", "."), ("treatment", ".."))
        ):
            invalid_slot_root = Path(temp_dir) / f"dot-segment-{position}"
            expect_ledger_error(
                lambda root=invalid_slot_root, treatment=treatment_id, case=case_id: create_run(
                    root,
                    manifest_with_slot(root.name, treatment, case),
                ),
                f"dot-segment slot key must be rejected: {treatment_id!r}/{case_id!r}",
            )
            assert not invalid_slot_root.exists()

        root = Path(temp_dir) / "run-001"
        manifest = manifest_for("run-001")
        run = create_run(root, manifest)
        assert run.run_dir == root
        assert run.manifest == manifest
        assert run.manifest_sha256 == manifest["manifest_sha256"]
        assert json.loads((root / "manifest.json").read_text()) == manifest
        expect_ledger_error(
            lambda: create_run(root, manifest),
            "manifest creation must be single-shot",
        )

        first = append_event(run, "run_started", {"slot_count": 2})
        assert json.loads((root / "state.json").read_text())["event_count"] == 1
        second = append_event(
            run,
            "slot_started",
            {"treatment_id": "subscription", "case_id": "single-file"},
        )
        assert set(first) == {
            "schema_version",
            "sequence",
            "timestamp",
            "type",
            "payload",
            "previous_sha256",
            "event_sha256",
        }
        assert first["schema_version"] == "cpe-live-event.v1"
        assert first["sequence"] == 1 and first["previous_sha256"] is None
        assert second["sequence"] == 2
        assert second["previous_sha256"] == first["event_sha256"]
        assert first["event_sha256"] == sha256_bytes(canonical_json(event_body(first)))
        assert second["event_sha256"] == sha256_bytes(canonical_json(event_body(second)))

        key = SlotKey("subscription", "single-file")
        commit_slot(run, key, SLOT_FILES, RESULT)
        events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
        completed_event = events[-1]
        assert completed_event["type"] == "slot_completed"
        assert completed_event["sequence"] == 3
        assert completed_event["previous_sha256"] == second["event_sha256"]

        slot_dir = root / "slots" / "subscription" / "single-file"
        index = json.loads((slot_dir / "index.json").read_text())
        assert index["schema_version"] == "cpe-live-slot-index.v1"
        assert index["result_sha256"] == sha256_bytes(canonical_json(RESULT))
        assert completed_event["payload"]["slot_sha256"] == index["slot_sha256"]
        assert completed_event["payload"]["result_sha256"] == index["result_sha256"]
        assert index["files"] == {
            name: sha256_bytes(contents) for name, contents in sorted(SLOT_FILES.items())
        }
        expect_ledger_error(
            lambda: commit_slot(run, key, SLOT_FILES, RESULT),
            "published slot evidence must be immutable",
        )

        projection = replay_run(root)
        assert projection["manifest_sha256"] == manifest["manifest_sha256"]
        assert projection["pending_slots"] == [
            {"treatment_id": "subscription", "case_id": "second-case"}
        ]
        assert projection["completed_slots"] == [
            {"treatment_id": "subscription", "case_id": "single-file"}
        ]
        assert projection["failed_slots"] == []
        assert projection["active_slot"] is None
        assert projection["lifecycle_outcome"] is None
        assert json.loads((root / "state.json").read_text()) == projection

        # state.json is a rebuildable projection, not an authority.
        (root / "state.json").write_text('{"status":"tampered"}\n')
        assert replay_run(root) == projection
        assert json.loads((root / "state.json").read_text()) == projection

        # An interrupted partial directory is ignored and its slot remains pending.
        partial_root = Path(temp_dir) / "partial-run"
        partial_manifest = manifest_for("partial-run")
        create_run(partial_root, partial_manifest)
        partial = partial_root / "slots" / ".partial-interrupted"
        partial.mkdir()
        (partial / "invocation.json").write_bytes(b"partial")
        partial_projection = replay_run(partial_root)
        assert partial_projection["completed_slots"] == []
        assert partial_projection["pending_slots"] == [
            {"treatment_id": "subscription", "case_id": "single-file"},
            {"treatment_id": "subscription", "case_id": "second-case"},
        ]

        append_event(partial_root_run := create_run(
            Path(temp_dir) / "lifecycle-run", manifest_for("lifecycle-run")
        ), "run_started", {"slot_count": 2})
        append_event(
            partial_root_run,
            "slot_started",
            {"treatment_id": "subscription", "case_id": "single-file"},
        )
        active_projection = replay_run(partial_root_run.run_dir)
        assert active_projection["active_slot"] == {
            "treatment_id": "subscription",
            "case_id": "single-file",
        }
        append_event(
            partial_root_run,
            "slot_failed",
            {"treatment_id": "subscription", "case_id": "single-file"},
        )
        append_event(partial_root_run, "run_blocked", {"reason": "retry required"})
        failed_projection = replay_run(partial_root_run.run_dir)
        assert failed_projection["failed_slots"] == [
            {"treatment_id": "subscription", "case_id": "single-file"}
        ]
        assert failed_projection["active_slot"] is None
        assert failed_projection["lifecycle_outcome"] == "blocked"

        concurrent_root = Path(temp_dir) / "concurrent-run"
        concurrent_run = create_run(concurrent_root, manifest_for("concurrent-run"))
        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_events = list(
                executor.map(
                    lambda marker: append_event(
                        concurrent_run, "audit_recorded", {"marker": marker}
                    ),
                    (1, 2),
                )
            )
        assert sorted(event["sequence"] for event in concurrent_events) == [1, 2]
        concurrent_projection = json.loads(
            (concurrent_root / "state.json").read_text()
        )
        assert concurrent_projection["event_count"] == 2
        assert concurrent_projection == replay_run(concurrent_root)

        invalid_root = Path(temp_dir) / "invalid-event-run"
        invalid_run = create_run(invalid_root, manifest_for("invalid-event-run"))
        expect_ledger_error(
            lambda: append_event(
                invalid_run,
                "slot_started",
                {"treatment_id": "subscription", "case_id": "not-in-manifest"},
            ),
            "an event outside the manifest must be rejected",
        )
        assert not (invalid_root / "events.jsonl").exists() or not (
            invalid_root / "events.jsonl"
        ).read_bytes()
        assert replay_run(invalid_root)["event_count"] == 0

        # Authoritative evidence mutations fail closed.
        events_path = root / "events.jsonl"
        original_events = events_path.read_bytes()
        mutated_events = original_events.replace(b"slot_completed", b"slot_corrupted", 1)
        events_path.write_bytes(mutated_events)
        expect_ledger_error(lambda: replay_run(root), "event mutation must be rejected")
        events_path.write_bytes(original_events)

        artifact_path = slot_dir / "final-output.json"
        original_artifact = artifact_path.read_bytes()
        artifact_path.write_bytes(original_artifact + b"tampered")
        expect_ledger_error(lambda: replay_run(root), "slot mutation must be rejected")
        artifact_path.write_bytes(original_artifact)

        result_path = slot_dir / "result.json"
        original_result = result_path.read_bytes()
        result_path.write_bytes(original_result + b"tampered")
        expect_ledger_error(lambda: replay_run(root), "result mutation must be rejected")
        result_path.write_bytes(original_result)

        manifest_path = root / "manifest.json"
        original_manifest = manifest_path.read_bytes()
        mutated_manifest = dict(manifest)
        mutated_manifest["run_id"] = "tampered"
        manifest_path.write_bytes(canonical_json(mutated_manifest))
        expect_ledger_error(lambda: replay_run(root), "manifest mutation must be rejected")
        manifest_path.write_bytes(original_manifest)
        assert replay_run(root) == projection

        # A drifted manifest must be rejected before any slot evidence is published.
        drift_root = Path(temp_dir) / "commit-after-drift"
        drift_manifest = manifest_for("commit-after-drift")
        drift_run = create_run(drift_root, drift_manifest)
        drifted = dict(drift_manifest)
        drifted["run_id"] = "tampered"
        (drift_root / "manifest.json").write_bytes(canonical_json(drifted))
        expect_ledger_error(
            lambda: commit_slot(
                drift_run,
                SlotKey("subscription", "single-file"),
                SLOT_FILES,
                RESULT,
            ),
            "commit must fail when the immutable manifest has drifted",
        )
        assert not (drift_root / "slots" / "subscription" / "single-file").exists()

    print("live matrix ledger checks passed")


if __name__ == "__main__":
    sys.exit(main())
