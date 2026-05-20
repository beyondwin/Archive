from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kao.py"


def test_kao_cli_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip().startswith("kao ")


def test_kao_cli_lists_core_commands() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for command in ("run", "status", "inspect", "events", "resume", "cancel", "apply", "clean"):
        assert command in result.stdout
