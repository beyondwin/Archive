#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.events import (
    EVENT_TYPES,
    append_event,
    canonical_event_hash,
    read_events,
    validate_chain,
)
from cpe_runtime.kernel import Kernel, Transition, _validate_transition, rebuild_snapshot
from cpe_runtime.manifest import create_manifest, write_manifest
from cpe_runtime.projector import initial_state, project


def _task_manifest() -> dict:
    return {
        "schema_version": "4",
        "run_id": "replay-fixture",
        "runtime": {
            "runtime_commit": "a" * 40,
            "compatibility_epoch": "cpe-v4",
        },
        "source_git": {"head": "a" * 40, "status": []},
        "task_graph": [
            {
                "id": "T1",
                "title": "Replay typed lifecycle",
                "dependencies": [],
                "file_claims": [],
                "spec_refs": [],
                "acceptance_command": "python3 check.py",
                "task_contract_sha256": "c" * 64,
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


def _evidence_ref() -> dict[str, str]:
    return {
        "kind": "verification",
        "path": "artifacts/evidence/check.json",
        "sha256": "e" * 64,
        "media_type": "application/json",
    }


def _checkpoint_payload() -> dict[str, object]:
    return {
        "predecessor": "a" * 40,
        "commit": "b" * 40,
        "tree": "c" * 40,
        "patch_sha256": "d" * 64,
        "changed_files": ["owned.txt"],
    }


def _verified_payload() -> dict[str, str]:
    return {
        "predecessor": "a" * 40,
        "commit": "b" * 40,
        "tree": "c" * 40,
        "contract_sha256": "d" * 64,
        "acceptance_sha256": "e" * 64,
        "review_sha256": "f" * 64,
    }


def check_typed_v4_lifecycle_replay() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-kernel-events-") as raw:
        path = Path(raw) / "events.jsonl"
        sequence = [
            {
                "type": "task.status_changed",
                "task_id": "T1",
                "payload": {"from": "pending", "to": "ready"},
            },
            {
                "type": "attempt.started",
                "task_id": "T1",
                "attempt_id": "A1",
                "payload": {"kind": "implementation"},
            },
            {
                "type": "attempt.completed",
                "task_id": "T1",
                "attempt_id": "A1",
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
                "attempt_id": "A1",
                "payload": {
                    "status": "changes_requested",
                    "findings": [{"severity": "major", "summary": "repair"}],
                    "missing_evidence": [],
                },
            },
            {
                "type": "candidate.checkpoint_recorded",
                "task_id": "T1",
                "payload": _checkpoint_payload(),
            },
            {
                "type": "task.checkpoint_verified",
                "task_id": "T1",
                "payload": _verified_payload(),
            },
            {
                "type": "blocker.opened",
                "task_id": "T1",
                "payload": {
                    "blocker_id": "B1",
                    "category": "runtime_defect",
                    "root_cause_key": "runtime:1",
                    "owner": "cpe",
                    "resume_condition": "upgrade runtime",
                },
            },
            {
                "type": "blocker.resolved",
                "task_id": "T1",
                "payload": {"blocker_id": "B1", "evidence_refs": [_evidence_ref()]},
            },
            {
                "type": "decision.recorded",
                "task_id": "T1",
                "payload": {
                    "selected_action": "upgrade runtime",
                    "basis": "runtime defect at verified checkpoint",
                    "approval_basis": "standing_autonomy_policy",
                },
            },
            {
                "type": "notification.requested",
                "task_id": "T1",
                "payload": {"dedupe_key": "runtime:T1", "kind": "runtime_upgraded"},
            },
            {
                "type": "runtime.upgraded",
                "payload": {
                    "old_runtime_commit": "a" * 40,
                    "new_runtime_commit": "f" * 40,
                    "reason": "resume after a runtime defect",
                    "compatibility_epoch": "cpe-v4",
                    "worktree_clean": True,
                    "verified_checkpoint": "b" * 40,
                },
            },
        ]
        for event in sequence:
            append_event(path, event)

        events = read_events(path)
        assert validate_chain(events) == []
        state = project(_task_manifest(), events)
        assert state["schema_version"] == "4"
        assert state["attempt_budget"] == {"limit": 40, "used": 1}
        assert state["attempts"][0]["status"] == "completed"
        assert state["usage_totals"]["output_tokens"] == 3
        assert state["verdicts"][0]["status"] == "changes_requested"
        assert state["candidate_checkpoints"][0]["commit"] == "b" * 40
        assert state["verified_checkpoints"][0]["commit"] == "b" * 40
        assert state["checkpoint_head"] == "b" * 40
        assert state["active_blockers"] == []
        assert state["blocker_history"][0]["status"] == "resolved"
        assert state["decisions"][0]["approval_basis"] == "standing_autonomy_policy"
        assert state["notifications"][0]["dedupe_key"] == "runtime:T1"
        assert state["runtime"]["runtime_commit"] == "f" * 40


def check_v4_event_boundary() -> None:
    assert "attempt.recorded" not in EVENT_TYPES
    assert "worktree.revision_recorded" not in EVENT_TYPES
    with tempfile.TemporaryDirectory(prefix="cpe-v4-event-boundary-") as raw:
        path = Path(raw) / "events.jsonl"
        _expect_error(
            "unknown event type",
            lambda: append_event(path, {"type": "attempt.recorded", "payload": {}}),
        )

    legacy = {
        "seq": 1,
        "event_id": "legacy-event",
        "type": "attempt.recorded",
        "at": "2026-07-10T00:00:00+00:00",
        "actor": "cpe-runtime",
        "task_id": "T1",
        "attempt_id": "legacy-A1",
        "payload": {},
        "previous_hash": None,
    }
    legacy["hash"] = canonical_event_hash(legacy)
    assert validate_chain([legacy]) == ["invalid event envelope"]


def check_kernel_payload_validation() -> None:
    manifest = _task_manifest()
    state = initial_state(manifest)
    state["lifecycle"] = "running"
    state["tasks"]["T1"]["status"] = "ready"
    run_dir = Path("/nonexistent-event-kernel-fixture")

    _expect_error(
        "unknown event type",
        lambda: _validate_transition(
            run_dir,
            manifest,
            state,
            Transition("attempt.recorded", {}, task_id="T1", attempt_id="A0"),
        ),
    )
    _expect_error(
        "invalid checkpoint payload",
        lambda: _validate_transition(
            run_dir,
            manifest,
            state,
            Transition(
                "candidate.checkpoint_recorded",
                {**_checkpoint_payload(), "commit": "short"},
                task_id="T1",
            ),
        ),
    )
    _validate_transition(
        run_dir,
        manifest,
        state,
        Transition("candidate.checkpoint_recorded", _checkpoint_payload(), task_id="T1"),
    )


def check_two_attempt_completion_and_exact_resume() -> None:
    manifest = _task_manifest()
    state = initial_state(manifest)
    state["lifecycle"] = "running"
    state["tasks"]["T1"]["status"] = "verifying"
    state["attempts"] = [
        {
            "task_id": "T1",
            "attempt_id": "T1.implementation.1",
            "kind": "implementation",
            "status": "completed",
            "attestation": {
                "verified": True,
                "actual_model": "gpt-5.6-sol",
                "actual_reasoning": "high",
            },
        },
        {
            "task_id": "T1",
            "attempt_id": "T1.task_review.1",
            "kind": "task_review",
            "status": "completed",
            "attestation": {
                "verified": True,
                "actual_model": "gpt-5.6-sol",
                "actual_reasoning": "high",
            },
        },
    ]
    state["verified_checkpoints"] = [{"task_id": "T1", **_verified_payload()}]
    state["checkpoint_head"] = "b" * 40
    state["artifact_index"] = [
        {
            "task_id": "T1",
            "kind": "deterministic_verification",
            "ref": _evidence_ref(),
            "candidate_commit": "b" * 40,
            "contract_sha256": "d" * 64,
            "passed": True,
        }
    ]
    run_dir = Path("/nonexistent-event-kernel-fixture")
    _validate_transition(
        run_dir,
        manifest,
        state,
        Transition(
            "task.status_changed",
            {"from": "verifying", "to": "completed"},
            task_id="T1",
        ),
    )

    missing_deterministic = {**state, "artifact_index": []}
    _expect_error(
        "task completion deterministic verification missing",
        lambda: _validate_transition(
            run_dir,
            manifest,
            missing_deterministic,
            Transition(
                "task.status_changed",
                {"from": "verifying", "to": "completed"},
                task_id="T1",
            ),
        ),
    )
    missing_review = {**state, "attempts": state["attempts"][:1]}
    _expect_error(
        "task completion model gate failed",
        lambda: _validate_transition(
            run_dir,
            manifest,
            missing_review,
            Transition(
                "task.status_changed",
                {"from": "verifying", "to": "completed"},
                task_id="T1",
            ),
        ),
    )
    stale_deterministic = {
        **state,
        "artifact_index": [
            {**state["artifact_index"][0], "candidate_commit": "0" * 40}
        ],
    }
    _expect_error(
        "task completion deterministic verification stale",
        lambda: _validate_transition(
            run_dir,
            manifest,
            stale_deterministic,
            Transition(
                "task.status_changed",
                {"from": "verifying", "to": "completed"},
                task_id="T1",
            ),
        ),
    )

    waiting = initial_state(manifest)
    waiting["tasks"]["T1"]["status"] = "reviewing"
    _validate_transition(
        run_dir,
        manifest,
        waiting,
        Transition(
            "task.status_changed",
            {
                "from": "reviewing",
                "to": "waiting_external",
                "wait_reason": "quota_transient",
                "resume_phase": "task_review",
                "active_attempt_id": "T1.task_review.1",
            },
            task_id="T1",
            attempt_id="T1.task_review.1",
        ),
    )
    waiting["tasks"]["T1"].update(
        {
            "status": "waiting_external",
            "wait_reason": "quota_transient",
            "resume_phase": "task_review",
            "active_attempt_id": "T1.task_review.1",
        }
    )
    _expect_error(
        "task resume phase mismatch",
        lambda: _validate_transition(
            run_dir,
            manifest,
            waiting,
            Transition(
                "task.status_changed",
                {
                    "from": "waiting_external",
                    "to": "repairing",
                    "resume_phase": "repair",
                },
                task_id="T1",
            ),
        ),
    )
    _expect_error(
        "invalid checkpoint payload",
        lambda: _validate_transition(
            run_dir,
            manifest,
            state,
            Transition(
                "task.checkpoint_verified",
                {"commit": "b" * 40, "contract_sha256": "d" * 64},
                task_id="T1",
            ),
        ),
    )
    _validate_transition(
        run_dir,
        manifest,
        state,
        Transition("task.checkpoint_verified", _verified_payload(), task_id="T1"),
    )
    _expect_error(
        "invalid decision payload",
        lambda: _validate_transition(
            run_dir,
            manifest,
            state,
            Transition("decision.recorded", {"selected_action": "continue"}, task_id="T1"),
        ),
    )
    _validate_transition(
        run_dir,
        manifest,
        state,
        Transition(
            "decision.recorded",
            {
                "selected_action": "continue",
                "basis": "approved plan",
                "approval_basis": "standing_autonomy_policy",
            },
            task_id="T1",
        ),
    )


def check_kernel_replay_recovery() -> None:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-kernel-replay-") as raw:
        root = Path(raw)
        run = root / "run"
        for name in ("plan.md", "pricing.json"):
            (root / name).write_text("{}\n", encoding="utf-8")
        manifest = create_manifest(
            "fixture",
            "interactive",
            root,
            root / "worktree",
            root / "plan.md",
            None,
            [],
            root / "pricing.json",
            source_head="a" * 40,
        )
        write_manifest(run / "run_manifest.json", manifest)

        path = run / "events.jsonl"
        append_event(
            path,
            {"type": "run.status_changed", "payload": {"from": "created", "to": "ready"}},
        )
        events = read_events(path)
        assert validate_chain(events) == []
        events[0]["payload"]["to"] = "running"
        assert validate_chain(events) == ["event hash mismatch"]

        path.unlink()
        kernel = Kernel(run)
        kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        kernel._snapshot_writer = lambda *_: (_ for _ in ()).throw(OSError("fixture crash"))
        try:
            kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
        except OSError:
            pass
        recovered = rebuild_snapshot(run)
        assert recovered["schema_version"] == "4"
        assert recovered["lifecycle"] == "running"
        assert recovered["last_event"]["seq"] == 2


def main() -> int:
    check_typed_v4_lifecycle_replay()
    check_v4_event_boundary()
    check_kernel_payload_validation()
    check_two_attempt_completion_and_exact_resume()
    check_kernel_replay_recovery()
    print(json.dumps({"passed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
