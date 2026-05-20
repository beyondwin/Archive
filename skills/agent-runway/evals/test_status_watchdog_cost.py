from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentrunway.cost import normalize_cost
from agentrunway.models import ProcessSnapshot
from agentrunway.status import format_run_status
from agentrunway.watchdog import classify_stall, classify_worker_snapshot


def test_status_formatter_summarizes_counts() -> None:
    text = format_run_status(
        {
            "run_id": "run-1",
            "status": "created",
            "tasks": [{"status": "pending"}, {"status": "merged"}],
        }
    )
    assert "run-1" in text
    assert "pending=1" in text
    assert "merged=1" in text


def test_status_formatter_marks_simulated_runs() -> None:
    text = format_run_status(
        {
            "run_id": "run-1",
            "status": "simulated_finished",
            "simulation": True,
            "diagnosis": {"next_action": "inspect run state"},
            "next_operator_action": "run without --fake-success before applying artifacts",
            "tasks": [{"status": "simulated_completed"}],
        }
    )
    assert "status=simulated_finished" in text
    assert "simulation=true" in text
    assert "simulated_completed=1" in text
    assert "run without --fake-success before applying artifacts" in text


def test_watchdog_classifies_wall_clock_timeout() -> None:
    started = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert classify_stall(started, timeout_seconds=60) == "wall_clock_timeout"


def test_cost_normalization_accepts_known_runtime_shapes() -> None:
    assert normalize_cost({"input_tokens": 10, "output_tokens": 5})["tokens_input"] == 10
    assert normalize_cost({"usage": {"prompt_tokens": 7, "completion_tokens": 3}})["tokens_output"] == 3
    assert normalize_cost({})["status"] == "unknown"


def test_watchdog_classifies_missing_result_after_successful_exit() -> None:
    snapshot = ProcessSnapshot(state="exited", pid=123, returncode=0, reason=None)
    assert classify_worker_snapshot(snapshot, result_exists=False) == "malformed_result"


def test_watchdog_classifies_nonzero_exit_as_adapter_crash() -> None:
    snapshot = ProcessSnapshot(state="exited", pid=123, returncode=2, reason=None)
    assert classify_worker_snapshot(snapshot, result_exists=False) == "adapter_crashed"
