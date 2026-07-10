#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.events import (
    READ_COMPAT_EVENT_TYPES,
    WRITABLE_EVENT_TYPES,
    append_event,
    canonical_event_hash,
    read_events,
    validate_chain,
)
from cpe_runtime.kernel import Kernel, Transition, _validate_transition, rebuild_snapshot
from cpe_runtime.projector import apply_event, initial_state, project
from cpe_runtime.manifest import create_manifest, write_manifest


def _task_manifest() -> dict:
    return {
        "schema_version": "3",
        "run_id": "replay-fixture",
        "task_graph": [
            {
                "id": "T1",
                "title": "Replay typed lifecycle",
                "dependencies": [],
                "file_claims": [],
                "spec_refs": [],
                "acceptance_command": None,
            }
        ],
    }


def _expect_error(message: str, operation) -> None:
    try:
        operation()
    except ValueError as exc:
        assert str(exc) == message, (str(exc), message)
    else:
        raise AssertionError(f"expected ValueError: {message}")


def check_typed_lifecycle_replay() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "events.jsonl"
        evidence_ref = {
            "kind": "verification",
            "path": "artifacts/evidence/blocker.json",
            "sha256": "b" * 64,
            "media_type": "application/json",
        }
        sequence = [
            {
                "type": "task.status_changed",
                "task_id": "T1",
                "payload": {"from": "pending", "to": "blocked"},
            },
            {
                "type": "attempt.started",
                "task_id": "T1",
                "attempt_id": "A0",
                "payload": {"kind": "implementation", "worktree_revision": 0},
            },
            {
                "type": "attempt.completed",
                "task_id": "T1",
                "attempt_id": "A0",
                "payload": {
                    "status": "completed",
                    "attestation": {"verified": True},
                    "usage": {"output_tokens": 3},
                    "latency_ms": 5,
                },
            },
            {
                "type": "verdict.recorded",
                "task_id": "T1",
                "attempt_id": "A0",
                "payload": {
                    "status": "changes_requested",
                    "findings": [{"severity": "major", "summary": "repair"}],
                    "missing_evidence": [],
                    "worktree_revision": 0,
                },
            },
            {
                "type": "blocker.opened",
                "task_id": "T1",
                "payload": {
                    "blocker_id": "B1",
                    "category": "verification",
                    "root_cause_key": "acceptance:1",
                    "owner": "cpe",
                    "resume_condition": "acceptance passes",
                },
            },
            {
                "type": "blocker.updated",
                "task_id": "T1",
                "payload": {"blocker_id": "B1", "owner": "operator"},
            },
            {
                "type": "blocker.resolved",
                "task_id": "T1",
                "payload": {"blocker_id": "B1", "evidence_refs": [evidence_ref]},
            },
            {
                "type": "task.retry_scheduled",
                "task_id": "T1",
                "payload": {
                    "phase": "acceptance",
                    "root_cause_key": "acceptance:1",
                    "worktree_revision": 0,
                    "evidence_refs": [evidence_ref],
                },
            },
            {
                "type": "worktree.revision_recorded",
                "task_id": "T1",
                "attempt_id": "A1",
                "payload": {
                    "from": 0,
                    "to": 1,
                    "patch_sha256": "a" * 64,
                    "changed_files": ["owned.txt"],
                    "attempt_id": "A1",
                },
            },
        ]
        for event in sequence:
            append_event(path, event)

        events = read_events(path)
        assert validate_chain(events) == []
        state = project(_task_manifest(), events)
        assert state["active_blockers"] == []
        assert state["blocker_history"][0]["status"] == "resolved"
        assert state["blocker_history"][0]["owner"] == "operator"
        assert state["tasks"]["T1"]["status"] == "verifying"
        assert state["retry_queue"][0]["phase"] == "acceptance"
        assert state["worktree_revision"] == 1
        assert state["worktree_patch_sha256"] == "a" * 64
        assert state["attempts"][0]["status"] == "completed"
        assert state["usage_totals"]["output_tokens"] == 3
        assert state["verdicts"][0]["status"] == "changes_requested"


def check_write_and_read_event_boundaries() -> None:
    assert "attempt.recorded" not in WRITABLE_EVENT_TYPES
    assert READ_COMPAT_EVENT_TYPES == WRITABLE_EVENT_TYPES | {"attempt.recorded"}
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "events.jsonl"
        _expect_error(
            "unknown event type",
            lambda: append_event(
                path,
                {
                    "type": "attempt.recorded",
                    "attempt_id": "legacy-A1",
                    "payload": {
                        "kind": "implementation",
                        "status": "completed",
                        "attestation": {},
                        "usage": {},
                        "latency_ms": 1,
                    },
                },
            ),
        )

    legacy = {
        "seq": 1,
        "event_id": "legacy-event",
        "type": "attempt.recorded",
        "at": "2026-07-10T00:00:00+00:00",
        "actor": "cpe-runtime",
        "task_id": "T1",
        "attempt_id": "legacy-A1",
        "payload": {
            "kind": "implementation",
            "status": "failed",
            "attestation": {},
            "usage": {"input_tokens": 7},
            "latency_ms": 1,
        },
        "previous_hash": None,
    }
    legacy["hash"] = canonical_event_hash(legacy)
    assert validate_chain([legacy]) == []
    state = project(_task_manifest(), [legacy])
    assert state["attempts"][0]["attempt_id"] == "legacy-A1"
    assert state["usage_totals"]["input_tokens"] == 7


def check_kernel_payload_validation() -> None:
    manifest = _task_manifest()
    state = initial_state(manifest)
    state["lifecycle"] = "running"
    state["tasks"]["T1"]["status"] = "blocked"
    run_dir = Path("/nonexistent-event-kernel-fixture")

    _expect_error(
        "unknown event type",
        lambda: _validate_transition(
            run_dir,
            manifest,
            state,
            Transition(
                "attempt.recorded",
                {
                    "kind": "implementation",
                    "status": "completed",
                    "attestation": {},
                    "usage": {},
                    "latency_ms": 1,
                },
                task_id="T1",
                attempt_id="A0",
            ),
        ),
    )
    _expect_error(
        "invalid worktree revision payload",
        lambda: _validate_transition(
            run_dir,
            manifest,
            state,
            Transition(
                "worktree.revision_recorded",
                {"from": 0, "to": 1, "patch_sha256": "short"},
                task_id="T1",
            ),
        ),
    )
    _expect_error(
        "invalid blocker resolution payload",
        lambda: _validate_transition(
            run_dir,
            manifest,
            {
                **state,
                "active_blockers": [{"blocker_id": "B1", "task_id": "T1"}],
            },
            Transition("blocker.resolved", {"blocker_id": "B1"}, task_id="T1"),
        ),
    )
    _expect_error(
        "invalid retry phase",
        lambda: _validate_transition(
            run_dir,
            manifest,
            state,
            Transition(
                "task.retry_scheduled",
                {"phase": "guess", "root_cause_key": "acceptance:1", "worktree_revision": 0},
                task_id="T1",
            ),
        ),
    )

    _validate_transition(
        run_dir,
        manifest,
        state,
        Transition(
            "blocker.opened",
            {
                "blocker_id": "B2",
                "category": "policy_violation",
                "root_cause_key": "task_scope:T1:owned.txt",
                "owner": "cpe",
                "resume_condition": "repair the task scope",
            },
            task_id="T1",
        ),
    )
    evidence_ref = {
        "kind": "verification",
        "path": "artifacts/evidence/retry.json",
        "sha256": "d" * 64,
        "media_type": "application/json",
    }
    _validate_transition(
        run_dir,
        manifest,
        state,
        Transition(
            "task.retry_scheduled",
            {
                "phase": "acceptance",
                "root_cause_key": "acceptance:1",
                "worktree_revision": 0,
                "evidence_refs": [evidence_ref],
            },
            task_id="T1",
        ),
    )
    _validate_transition(
        run_dir,
        manifest,
        state,
        Transition(
            "worktree.revision_recorded",
            {
                "from": 0,
                "to": 1,
                "patch_sha256": "a" * 64,
                "changed_files": ["owned.txt"],
                "attempt_id": "A1",
            },
            task_id="T1",
            attempt_id="A1",
        ),
    )


def check_integrity_rejections() -> None:
    manifest = _task_manifest()
    run_dir = Path("/nonexistent-event-kernel-fixture")
    evidence_ref = {
        "kind": "verification",
        "path": "artifacts/evidence/failure.json",
        "sha256": "c" * 64,
        "media_type": "application/json",
    }

    blocked = initial_state(manifest)
    blocked["lifecycle"] = "running"
    blocked["tasks"]["T1"]["status"] = "blocked"
    blocked["active_blockers"] = [
        {"blocker_id": "B1", "task_id": "T1", "status": "open"}
    ]
    _expect_error(
        "invalid retry payload",
        lambda: _validate_transition(
            run_dir,
            manifest,
            blocked,
            Transition(
                "task.retry_scheduled",
                {
                    "phase": "acceptance",
                    "root_cause_key": "acceptance:1",
                    "worktree_revision": 0,
                    "evidence_refs": [evidence_ref],
                },
                task_id="T1",
            ),
        ),
    )
    resolved = {**blocked, "active_blockers": []}
    _expect_error(
        "invalid retry payload",
        lambda: _validate_transition(
            run_dir,
            manifest,
            resolved,
            Transition(
                "task.retry_scheduled",
                {
                    "phase": "acceptance",
                    "root_cause_key": "acceptance:1",
                    "worktree_revision": 0,
                    "evidence_refs": [],
                },
                task_id="T1",
            ),
        ),
    )

    for event_type, payload, message in (
        ("blocker.updated", {"blocker_id": "B1", "owner": "operator"}, "invalid blocker update payload"),
        ("blocker.resolved", {"blocker_id": "B1", "evidence_refs": [evidence_ref]}, "invalid blocker resolution payload"),
        ("blocker.updated", {"blocker_id": "B1", "status": "resolved"}, "invalid blocker update payload"),
        ("blocker.updated", {"blocker_id": "B1", "task_id": "T2"}, "invalid blocker update payload"),
        ("blocker.resolved", {"blocker_id": "B1", "status": "resolved", "evidence_refs": [evidence_ref]}, "invalid blocker resolution payload"),
    ):
        _expect_error(
            message,
            lambda event_type=event_type, payload=payload: _validate_transition(
                run_dir,
                manifest,
                blocked,
                Transition(event_type, payload, task_id=None),
            ),
        )

    attempts = initial_state(manifest)
    attempts["lifecycle"] = "running"
    attempts["attempts"] = [
        {"task_id": "T1", "attempt_id": "A1", "kind": "task_review", "status": "started"}
    ]
    valid_completion = {
        "status": "completed",
        "attestation": {"verified": False},
        "usage": {"input_tokens": 1},
        "latency_ms": 1,
    }
    for payload in (
        {**valid_completion, "attestation": []},
        {**valid_completion, "usage": {"input_tokens": True}},
        {**valid_completion, "latency_ms": True},
        {**valid_completion, "status": "failed"},
    ):
        _expect_error(
            "invalid attempt payload",
            lambda payload=payload: _validate_transition(
                run_dir,
                manifest,
                attempts,
                Transition("attempt.completed", payload, task_id="T1", attempt_id="A1"),
            ),
        )
    completed = {**attempts, "attempts": [{**attempts["attempts"][0], **valid_completion}]}
    _expect_error(
        "invalid attempt payload",
        lambda: _validate_transition(
            run_dir,
            manifest,
            completed,
            Transition("attempt.completed", valid_completion, task_id="T1", attempt_id="A1"),
        ),
    )

    verdict = {
        "status": "passed",
        "findings": [],
        "missing_evidence": [],
        "worktree_revision": 0,
    }
    for attempt_id, payload in (
        ("unknown", verdict),
        ("A1", {**verdict, "worktree_revision": 1}),
        ("A1", {**verdict, "findings": {}}),
        ("A1", {**verdict, "missing_evidence": None}),
    ):
        _expect_error(
            "invalid verdict payload",
            lambda attempt_id=attempt_id, payload=payload: _validate_transition(
                run_dir,
                manifest,
                attempts,
                Transition("verdict.recorded", payload, task_id="T1", attempt_id=attempt_id),
            ),
        )

    projection = apply_event(
        attempts,
        {
            "seq": 1,
            "hash": "event-1",
            "type": "attempt.completed",
            "task_id": "T1",
            "attempt_id": "A1",
            "payload": valid_completion,
        },
    )
    _expect_error(
        "invalid attempt payload",
        lambda: apply_event(
            projection,
            {
                "seq": 2,
                "hash": "event-2",
                "type": "attempt.completed",
                "task_id": "T1",
                "attempt_id": "A1",
                "payload": valid_completion,
            },
        ),
    )


def main() -> int:
    check_typed_lifecycle_replay()
    check_write_and_read_event_boundaries()
    check_kernel_payload_validation()
    check_integrity_rejections()
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); run = root / "run"
        for name in ("plan.md", "pricing.json"):
            (root / name).write_text("{}\n", encoding="utf-8")
        manifest = create_manifest("fixture", "interactive", root, root / "worktree", root / "plan.md", None, [], root / "pricing.json")
        write_manifest(run / "run_manifest.json", manifest)
        path = run / "events.jsonl"
        append_event(path, {"type": "run.status_changed", "payload": {"from": "created", "to": "ready"}})
        events = read_events(path)
        assert validate_chain(events) == []
        events[0]["payload"]["to"] = "running"
        assert validate_chain(events) == ["event hash mismatch"]
        (run / "events.jsonl").unlink(); (run / "state.json").unlink(missing_ok=True)
        kernel = Kernel(run)
        kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        kernel._snapshot_writer = lambda *_: (_ for _ in ()).throw(OSError("fixture crash"))
        try:
            kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
        except OSError:
            pass
        recovered = rebuild_snapshot(run)
        assert recovered["lifecycle"] == "running"
        assert recovered["last_event"]["seq"] == 2
    print('{"passed": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
