#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.events import EVENT_TYPES, append_event, read_events, validate_chain
from cpe_runtime.manifest import create_manifest, load_manifest
from cpe_runtime.projector import project
from cpe_runtime.task_contracts import TaskContractV4, compile_task_contract
from cpe_runtime.validation import validate_integrity


EXPECTED_EVENT_TYPES = frozenset(
    {
        "run.status_changed",
        "task.status_changed",
        "attempt.started",
        "attempt.completed",
        "verdict.recorded",
        "evidence.attached",
        "candidate.checkpoint_recorded",
        "task.checkpoint_verified",
        "blocker.opened",
        "blocker.resolved",
        "decision.recorded",
        "notification.requested",
        "runtime.upgraded",
        "completion.recorded",
    }
)


def fixture_contract() -> TaskContractV4:
    return compile_task_contract(
        {
            "id": "T1",
            "title": "Install the v4 state contract",
            "task_type": "tdd_implementation",
            "risk_class": "high",
            "task_source": "### Task 1: Install the v4 state contract\n",
            "acceptance_commands": ["python3 check_v4_state_contract.py"],
        },
        source_hashes={"plan": "f" * 64, "spec_sections": {}},
    )


def create_v4_manifest(*, task_contracts: list[TaskContractV4]) -> dict:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-manifest-") as raw:
        root = Path(raw)
        plan = root / "plan.md"
        pricing = root / "pricing.json"
        plan.write_text("# fixture\n", encoding="utf-8")
        pricing.write_text("{}\n", encoding="utf-8")
        task_graph = [
            {
                "id": contract.task_id,
                "title": contract.title,
                "dependencies": list(contract.dependencies),
                "file_claims": list(contract.file_claims),
                "spec_refs": [section["id"] for section in contract.spec_sections],
                "acceptance_command": "\n".join(contract.acceptance_commands),
                "task_contract": contract.body(),
                "task_contract_sha256": contract.contract_sha256,
            }
            for contract in task_contracts
        ]
        return create_manifest(
            "v4-state-fixture",
            "interactive",
            root,
            root / "worktree",
            plan,
            None,
            task_graph,
            pricing,
            source_head="a" * 40,
        )


def write_manifest_fixture(payload: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="cpe-v4-load-"))
    path = root / "run_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@contextmanager
def assert_raises_text(error_type: type[BaseException], expected: str):
    try:
        yield
    except error_type as exc:
        assert str(exc) == expected, (str(exc), expected)
    else:
        raise AssertionError(f"expected {error_type.__name__}: {expected}")


def check_v4_manifest_and_initial_state() -> dict:
    manifest = create_v4_manifest(task_contracts=[fixture_contract()])
    assert manifest["schema_version"] == "4"
    state = project(manifest, [])
    assert state["schema_version"] == "4"
    assert state["attempt_budget"] == {"limit": 40, "used": 0}
    for key in (
        "runtime",
        "candidate_checkpoints",
        "verified_checkpoints",
        "checkpoint_head",
        "decisions",
        "backlog",
        "repair_roots",
        "wait_reason",
    ):
        assert key in state, key
    return manifest


def check_clean_cut_schema_rejection() -> None:
    with assert_raises_text(ValueError, "unsupported_run_schema"):
        load_manifest(write_manifest_fixture({"schema_version": "3"}))
    with assert_raises_text(ValueError, "unsupported_run_schema"):
        project({"schema_version": "3", "task_graph": []}, [])
    with tempfile.TemporaryDirectory(prefix="cpe-v4-validation-") as raw:
        run_dir = Path(raw)
        (run_dir / "run_manifest.json").write_text(
            '{"schema_version":"3"}\n', encoding="utf-8"
        )
        (run_dir / "events.jsonl").write_text("not-json\n", encoding="utf-8")
        report = validate_integrity(run_dir)
        assert report.classification == "unsupported_run_schema"
        assert report.errors == ["unsupported_run_schema"]


def check_v4_event_and_runtime_upgrade(manifest: dict) -> None:
    from cpe_runtime.runtime_upgrade import RuntimeIdentity, validate_runtime_upgrade

    assert EVENT_TYPES == EXPECTED_EVENT_TYPES
    with tempfile.TemporaryDirectory(prefix="cpe-v4-events-") as raw:
        path = Path(raw) / "events.jsonl"
        with assert_raises_text(ValueError, "unknown event type"):
            append_event(path, {"type": "attempt.recorded", "payload": {}})

        checkpoint = "b" * 40
        append_event(
            path,
            {
                "type": "task.checkpoint_verified",
                "task_id": "T1",
                "payload": {"commit": checkpoint, "contract_sha256": "c" * 64},
            },
        )
        upgrade_payload = {
            "old_runtime_commit": "a" * 40,
            "new_runtime_commit": "d" * 40,
            "reason": "resume after a runtime defect",
            "compatibility_epoch": "cpe-v4",
            "worktree_clean": True,
            "verified_checkpoint": checkpoint,
        }
        target = validate_runtime_upgrade(
            RuntimeIdentity("a" * 40, "cpe-v4"),
            upgrade_payload,
            checkpoint_head=checkpoint,
        )
        assert target == RuntimeIdentity("d" * 40, "cpe-v4")
        append_event(path, {"type": "runtime.upgraded", "payload": upgrade_payload})
        events = read_events(path)
        assert validate_chain(events) == []
        state = project(manifest, events)
        assert state["runtime"] == {
            "runtime_commit": "d" * 40,
            "compatibility_epoch": "cpe-v4",
        }
        assert state["checkpoint_head"] == checkpoint

        for field, value, message in (
            ("compatibility_epoch", "cpe-v3", "runtime_compatibility_epoch_invalid"),
            ("worktree_clean", False, "runtime_upgrade_requires_clean_tree"),
            ("verified_checkpoint", "e" * 40, "runtime_upgrade_requires_verified_checkpoint"),
        ):
            invalid = {**upgrade_payload, field: value}
            with assert_raises_text(ValueError, message):
                validate_runtime_upgrade(
                    RuntimeIdentity("a" * 40, "cpe-v4"),
                    invalid,
                    checkpoint_head=checkpoint,
                )


def main() -> int:
    manifest = check_v4_manifest_and_initial_state()
    check_clean_cut_schema_rejection()
    check_v4_event_and_runtime_upgrade(manifest)
    print('{"passed": true}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
