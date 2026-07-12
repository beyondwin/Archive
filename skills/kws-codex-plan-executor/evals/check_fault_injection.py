#!/usr/bin/env python3
"""Fault injection for the clean-cut CPE v4 scheduler lifecycle."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from cpe_runtime.reconciliation import select_v4_resume
from check_scheduler_v4 import (
    assert_resume_and_budget,
    assert_runtime_upgrade_resume,
    assert_scope_policy,
    assert_task_local_external_wait,
)


def assert_resume_selection() -> None:
    state = {
        "schema_version": "4",
        "run_id": "run-v4",
        "lifecycle": "waiting_external",
        "checkpoint_head": "a" * 40,
        "verified_checkpoints": [{"task_id": "T1", "commit": "a" * 40}],
        "tasks": {
            "T2": {
                "status": "waiting_external",
                "resume_phase": "implementation",
                "active_attempt_id": "T2.implementation.1",
            }
        },
        "attempts": [
            {
                "task_id": "T2",
                "attempt_id": "T2.implementation.1",
                "kind": "implementation",
                "status": "started",
            }
        ],
    }
    quota = select_v4_resume(state, "T2")
    assert quota.action == "resume_same_attempt"
    assert quota.attempt_id == "T2.implementation.1"
    state["attempts"][0]["status"] = "interrupted"
    state["tasks"]["T2"]["active_attempt_id"] = None
    runtime = select_v4_resume(state, "T2")
    assert runtime.action == "resume_verified_checkpoint"
    assert runtime.checkpoint_head == "a" * 40
    state["tasks"]["T2"].update(
        {
            "status": "waiting_user",
            "resume_phase": "implementation",
            "active_attempt_id": None,
        }
    )
    authority = select_v4_resume(state, "T2")
    assert authority.action == "await_user_authority"
    assert authority.phase is None and authority.attempt_id is None


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-faults-") as raw:
        root = Path(raw)
        assert_scope_policy(root / "scope")
        assert_resume_and_budget(root / "resume")
        assert_runtime_upgrade_resume(root / "runtime")
        assert_task_local_external_wait(root / "task-local")
        assert_resume_selection()
    print(
        json.dumps(
            {
                "passed": True,
                "checks": {
                    "scope_expansion_and_boundary_reopen": True,
                    "pre_turn_and_quota_resume": True,
                    "attempt_budget_hard_stop": True,
                    "runtime_upgrade_checkpoint_resume": True,
                    "task_local_external_wait": True,
                    "waiting_user_requires_authority": True,
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
