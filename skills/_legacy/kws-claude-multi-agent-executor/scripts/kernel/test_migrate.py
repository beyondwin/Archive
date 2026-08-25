#!/usr/bin/env python3
"""Tests for migrate.to_v3 — TDD RED phase.

Run:  cd skills/kws-claude-multi-agent-executor && python3 scripts/kernel/test_migrate.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_v3_passthrough():
    """to_v3 is a no-op when schema_version == 3."""
    import migrate
    state = {"schema_version": 3, "run_id": "x", "tasks": {"t1": {}}}
    result = migrate.to_v3(state)
    assert result["schema_version"] == 3
    assert result["tasks"] == {"t1": {}}
    # should be the same object (no copy needed, but at minimum unchanged)
    assert result is state or result == state
    print("PASS test_v3_passthrough")


def test_schema_version_set():
    """to_v3 sets schema_version=3 on a v2 state."""
    import migrate
    state = {
        "schema_version": 2,
        "plan": "/path/to/plan.md",
        "spec": "/path/to/spec.md",
        "tasks": {"t1": {"status": "done"}},
        "task_summaries": {},
        "mode": "interactive_attached",
    }
    result = migrate.to_v3(state)
    assert result["schema_version"] == 3
    print("PASS test_schema_version_set")


def test_tasks_preserved_single_plan():
    """tasks dict is preserved at top level for a single-plan v2 state (no plan2_state)."""
    import migrate
    original_tasks = {"t1": {"status": "done"}, "t2": {"status": "pending"}}
    state = {
        "schema_version": 2,
        "plan": "/plans/plan.md",
        "spec": "/specs/spec.md",
        "tasks": original_tasks,
        "task_summaries": {"t1": "summary"},
        "mode": "interactive_attached",
    }
    result = migrate.to_v3(state)
    assert result["schema_version"] == 3
    assert result["tasks"] == original_tasks
    print("PASS test_tasks_preserved_single_plan")


def test_unknown_fields_go_to_legacy():
    """Fields not in the known v3 schema land in result['legacy']."""
    import migrate
    state = {
        "schema_version": 2,
        "plan": "/plans/p.md",
        "spec": "/specs/s.md",
        "tasks": {},
        "task_summaries": {},
        "mode": "interactive_attached",
        "some_future_field": "hello",
        "another_unknown": 42,
    }
    result = migrate.to_v3(state)
    assert result["schema_version"] == 3
    assert "legacy" in result
    assert result["legacy"]["some_future_field"] == "hello"
    assert result["legacy"]["another_unknown"] == 42
    # known fields must NOT be in legacy
    assert "tasks" not in result["legacy"]
    assert "plan" not in result["legacy"]
    print("PASS test_unknown_fields_go_to_legacy")


def test_missing_schema_version_treated_as_v2():
    """A state dict with no schema_version is treated as legacy and converted."""
    import migrate
    state = {
        # no schema_version
        "plan": "/plans/p.md",
        "spec": "/specs/s.md",
        "tasks": {},
        "task_summaries": {},
        "mode": "interactive_attached",
    }
    result = migrate.to_v3(state)
    assert result["schema_version"] == 3
    print("PASS test_missing_schema_version_treated_as_v2")


def test_plan2_state_becomes_plan_chain():
    """A v2 state with plan2_state is rewritten into plan_chain of 2 elements."""
    import migrate
    state = {
        "schema_version": 2,
        "plan": "/plans/plan1.md",
        "spec": "/specs/spec1.md",
        "tasks": {"t1": {"status": "done"}},
        "task_summaries": {"t1": "summary1"},
        "quality_trend": ["good"],
        "mode": "interactive_attached",
        "active_plan": "plan1",
        "plan2_state": {
            "plan_path": "/plans/plan2.md",
            "spec_path": "/specs/spec2.md",
            "tasks": {"t2": {"status": "pending"}},
            "task_summaries": {},
            "status": "queued",
            "blocked_until": None,
        },
    }
    result = migrate.to_v3(state)
    assert result["schema_version"] == 3

    # plan_chain must have exactly 2 elements
    assert "plan_chain" in result
    chain = result["plan_chain"]
    assert len(chain) == 2

    # chain[0] gets plan1 data
    assert chain[0]["index"] == 0
    assert chain[0]["plan_path"] == "/plans/plan1.md"
    assert chain[0]["spec_path"] == "/specs/spec1.md"
    assert chain[0]["tasks"] == {"t1": {"status": "done"}}

    # chain[1] gets plan2 data
    assert chain[1]["index"] == 1
    assert chain[1]["plan_path"] == "/plans/plan2.md"
    assert chain[1]["spec_path"] == "/specs/spec2.md"
    assert chain[1]["tasks"] == {"t2": {"status": "pending"}}

    # plan2_state must be removed from top-level
    assert "plan2_state" not in result

    # active_plan coerced to integer (plan1 -> 0)
    assert result["active_plan"] == 0

    print("PASS test_plan2_state_becomes_plan_chain")


def test_plan2_state_active_plan2():
    """plan2 active_plan is coerced to index 1."""
    import migrate
    state = {
        "schema_version": 2,
        "plan": "/plans/plan1.md",
        "spec": "/specs/spec1.md",
        "tasks": {},
        "task_summaries": {},
        "mode": "plan2_running",
        "active_plan": "plan2",
        "plan2_state": {
            "plan_path": "/plans/plan2.md",
            "spec_path": "/specs/spec2.md",
            "tasks": {},
            "task_summaries": {},
            "status": "running",
            "blocked_until": None,
        },
    }
    result = migrate.to_v3(state)
    assert result["active_plan"] == 1
    assert result["plan_chain"][1]["status"] == "running"
    print("PASS test_plan2_state_active_plan2")


def test_plan_chain_already_present_skips_plan2_migration():
    """If plan_chain already exists (v2.13+) and schema_version < 3, chain is preserved."""
    import migrate
    existing_chain = [
        {"index": 0, "plan_path": "/p1.md", "tasks": {}},
        {"index": 1, "plan_path": "/p2.md", "tasks": {}},
    ]
    state = {
        "schema_version": 2,
        "plan_chain": existing_chain,
        "active_plan": 0,
        "mode": "plan_chain_running",
    }
    result = migrate.to_v3(state)
    assert result["schema_version"] == 3
    assert result["plan_chain"] == existing_chain
    print("PASS test_plan_chain_already_present_skips_plan2_migration")


if __name__ == "__main__":
    test_v3_passthrough()
    test_schema_version_set()
    test_tasks_preserved_single_plan()
    test_unknown_fields_go_to_legacy()
    test_missing_schema_version_treated_as_v2()
    test_plan2_state_becomes_plan_chain()
    test_plan2_state_active_plan2()
    test_plan_chain_already_present_skips_plan2_migration()
    print("\nAll migrate tests passed.")
