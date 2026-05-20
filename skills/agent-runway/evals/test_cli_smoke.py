from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agentrunway.py"


def test_agentrunway_cli_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip().startswith("agentrunway ")


def test_agentrunway_cli_lists_core_commands() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for command in ("run", "status", "inspect", "events", "resume", "cancel", "apply", "clean"):
        assert command in result.stdout


def test_clean_help_lists_retention_safety_flags() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "clean", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "--older-than" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--apply" in result.stdout
