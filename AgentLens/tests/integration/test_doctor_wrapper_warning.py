"""Integration test for `agentlens doctor` wrapper-chain detection (Task 8).

Spec §3.5 (Layer 5): when a `.real` lockfile points at a script that matches
a wrapper signature (e.g. cmux launcher), doctor reports
``shim_integrity=wrapper_chain_warning`` together with ``wrapper_detected``
(the category) and ``remediation`` (the suggested CLI command). The sha256
must match the recorded value so that drift is excluded — the new branch
fires after the drift check passes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "install_wrapper_safety"
)
CMUX_FIXTURE = FIXTURE_DIR / "cmux-launcher.sh"


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _stage_shim_pointing_at(home_dir: Path, agent: str, target: Path) -> None:
    """Manually stage a shim + lockfile so the .real target is the wrapper."""
    shim_dir = home_dir / ".agentlens" / "shims"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim_dir.chmod(0o700)
    # Dummy shim binary (presence-only; doctor reads only the .real lockfile).
    shim = shim_dir / agent
    shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    shim.chmod(0o755)
    lockfile = shim_dir / f"{agent}.real"
    lockfile.write_text(
        f"path={target}\nsha256={_sha256(target)}\n",
        encoding="utf-8",
    )


class TestDoctorWrapperWarning:
    def test_doctor_json_reports_wrapper_chain_warning(
        self, runner: CliRunner, home: Path
    ) -> None:
        _stage_shim_pointing_at(home, "claude", CMUX_FIXTURE)

        result = runner.invoke(app, ["doctor", "--format", "json"])
        assert result.exit_code == 0, result.output
        doc = json.loads(result.output)
        claude = doc["integrations"]["claude"]
        assert claude["integration_level"] == "shim"
        assert claude["shim_integrity"] == "wrapper_chain_warning"
        assert claude["wrapper_detected"] == "cmux"
        assert isinstance(claude["remediation"], str)
        assert claude["remediation"].startswith("agentlens install")

    def test_doctor_text_emits_two_lines(
        self, runner: CliRunner, home: Path
    ) -> None:
        _stage_shim_pointing_at(home, "claude", CMUX_FIXTURE)

        result = runner.invoke(app, ["doctor", "--format", "text"])
        assert result.exit_code == 0, result.output
        out = result.output
        assert "shim_integrity=wrapper_chain_warning" in out
        assert "wrapper_detected=cmux" in out
        assert "fix:" in out
