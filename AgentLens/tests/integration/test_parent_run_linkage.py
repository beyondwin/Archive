"""Integration tests for explicit AGENTLENS_PARENT_RUN_ID linkage (Task 5).

Spec §4.4 — Parent-link env contract
====================================

``AGENTLENS_PARENT_RUN_ID`` is an explicit opt-in signal read by the
process wrapper at startup. When set and non-empty, the wrapper records
a new child run whose ``run.json::parent_run_id`` is populated with the
provided value — *even when an inherited* ``AGENTLENS_RUN_ID`` *would*
*otherwise trigger the default nested-passthrough policy.*

This module verifies three behaviors:

1. Explicit parent only        → new child run, parent_run_id = explicit value.
2. Inherited AGENTLENS_RUN_ID  → preserves existing passthrough behavior.
3. Both env vars set           → explicit parent wins; inherited RUN_ID is
                                 NOT used as the parent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agentlens.adapters.process import wrap_command


def _read_run_json(home: Path, run_id: str) -> dict:
    """Locate the run.json for ``run_id`` under ``home/runs/<workspace>/<run_id>``."""
    candidates = list((home / "runs").glob("*/*"))
    candidates = [
        d for d in candidates if d.is_dir() and (d / "run.json").is_file()
    ]
    match = [d for d in candidates if d.name == run_id]
    assert match, f"no run dir matched {run_id} under {home}"
    return json.loads((match[0] / "run.json").read_text(encoding="utf-8"))


def test_explicit_parent_only_records_child_with_parent_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGENTLENS_PARENT_RUN_ID set, AGENTLENS_RUN_ID unset → new child run
    is recorded with ``parent_run_id`` populated from the explicit env var."""
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTLENS_PARENT_RUN_ID", "run_parent_001")
    monkeypatch.delenv("AGENTLENS_RUN_ID", raising=False)
    monkeypatch.delenv("AGENTLENS_NESTED_POLICY", raising=False)
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)

    result = wrap_command(
        [sys.executable, "-c", "print('child')"],
        agent_name="claude_code",
        agent_mode="cli",
        mode="minimal",
    )

    assert result.exit_code == 0
    assert result.run_id is not None  # explicit parent → must record.
    run_doc = _read_run_json(tmp_path / "home", result.run_id)
    assert run_doc.get("parent_run_id") == "run_parent_001"


def test_inherited_parent_only_preserves_passthrough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGENTLENS_PARENT_RUN_ID unset/empty + AGENTLENS_RUN_ID inherited
    + default nested policy → the wrapper must still take the existing
    passthrough branch (no new run recorded). This locks down that the
    new explicit-parent logic does NOT regress the original
    AGENTLENS_RUN_ID-only behavior."""
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTLENS_RUN_ID", "run_existing_002")
    monkeypatch.setenv("AGENTLENS_RUN_DIR", str(tmp_path))
    # Explicit parent absent OR empty must NOT trigger child recording.
    monkeypatch.delenv("AGENTLENS_PARENT_RUN_ID", raising=False)
    monkeypatch.delenv("AGENTLENS_NESTED_POLICY", raising=False)
    monkeypatch.chdir(tmp_path)

    result = wrap_command(
        [sys.executable, "-c", "print('child')"],
        agent_name="claude_code",
        agent_mode="cli",
        mode="minimal",
    )

    assert result.exit_code == 0
    # Default passthrough → no recording, no new run_id.
    assert result.run_id is None


def test_inherited_parent_only_empty_explicit_value_still_passthrough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty-string AGENTLENS_PARENT_RUN_ID is equivalent to unset
    (spec: ``set and non-empty``)."""
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTLENS_RUN_ID", "run_existing_002b")
    monkeypatch.setenv("AGENTLENS_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTLENS_PARENT_RUN_ID", "")  # explicitly empty
    monkeypatch.delenv("AGENTLENS_NESTED_POLICY", raising=False)
    monkeypatch.chdir(tmp_path)

    result = wrap_command(
        [sys.executable, "-c", "print('child')"],
        agent_name="claude_code",
        agent_mode="cli",
        mode="minimal",
    )

    assert result.exit_code == 0
    assert result.run_id is None  # empty == unset → still passthrough


def test_both_set_explicit_parent_wins_over_inherited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When BOTH AGENTLENS_PARENT_RUN_ID and AGENTLENS_RUN_ID are set,
    the explicit parent wins (spec §4.4): a new child run is recorded
    with ``parent_run_id == AGENTLENS_PARENT_RUN_ID`` and the inherited
    AGENTLENS_RUN_ID is NOT used as the parent.

    Distinct constants in this test guarantee an implementation that
    accidentally substitutes ``inherited_run_id`` for the explicit value
    is caught.
    """
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTLENS_PARENT_RUN_ID", "run_parent_003")
    monkeypatch.setenv("AGENTLENS_RUN_ID", "run_existing_004")
    monkeypatch.setenv("AGENTLENS_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("AGENTLENS_NESTED_POLICY", raising=False)
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)

    result = wrap_command(
        [sys.executable, "-c", "print('child')"],
        agent_name="claude_code",
        agent_mode="cli",
        mode="minimal",
    )

    assert result.exit_code == 0
    assert result.run_id is not None  # explicit parent overrides passthrough.
    run_doc = _read_run_json(tmp_path / "home", result.run_id)
    # Explicit parent wins.
    assert run_doc.get("parent_run_id") == "run_parent_003"
    # And the inherited run_id is NOT used as the parent.
    assert run_doc.get("parent_run_id") != "run_existing_004"
