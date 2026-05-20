from __future__ import annotations

from agentrunway.status import format_inspect_payload


def test_format_inspect_payload_includes_scheduler_state() -> None:
    text = format_inspect_payload(
        {
            "run_id": "run-1",
            "status": "blocked",
            "diagnosis": {"status": "blocked", "reason": "blocked_dependency"},
            "tasks": [{"task_id": "task_001"}],
            "workers": [],
            "coverage": {"covered": [], "blocked": []},
            "agentlens": {"failed": 0},
            "next_action": "await_human_decision",
            "durable": {
                "projection_status": "blocked",
                "safe_wave": [],
                "withheld_tasks": [{"task_id": "task_002"}],
                "stale_activities": [{"activity_id": "task_001.implement.001"}],
            },
        }
    )

    assert "projection=blocked" in text
    assert "safe_wave=0" in text
    assert "withheld=1" in text
    assert "stale=1" in text
