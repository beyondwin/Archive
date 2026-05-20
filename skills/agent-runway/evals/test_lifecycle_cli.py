from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def test_lifecycle_commands_return_json_for_missing_run(isolated_home: Path, tmp_path: Path) -> None:
    for command in ("status", "inspect", "events", "resume", "cancel", "apply"):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), command, "--run", "missing"],
            cwd=tmp_path,
            text=True,
            capture_output=True,
        )
        assert result.returncode in {0, 1}
        assert json.loads(result.stdout)["run_id"] == "missing"


def test_clean_reports_removed_count(isolated_home: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "clean", "--older-than", "0d", "--successful"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "removed" in json.loads(result.stdout)


def test_events_command_filters_by_type(isolated_home: Path, tmp_path: Path) -> None:
    from agentrunway.db import AgentRunwayDb

    run_dir = isolated_home / "runs" / "ws" / "run-1"
    run_dir.mkdir(parents=True)
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.insert_event(event_type="agentrunway.run_started", payload={"run_id": "run-1"}, status="agentlens_disabled")
    db.insert_event(event_type="agentrunway.gate_retry", payload={"run_id": "run-1"}, status="agentlens_disabled")
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-1", "status": "finished", "run_dir": str(run_dir), "state_db": str(run_dir / "state.sqlite")}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "events", "--run", "run-1", "--type", "agentrunway.gate_retry"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert [event["event_type"] for event in payload["events"]] == ["agentrunway.gate_retry"]
