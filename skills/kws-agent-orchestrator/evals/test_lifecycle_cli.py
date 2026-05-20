from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kao.py"


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
