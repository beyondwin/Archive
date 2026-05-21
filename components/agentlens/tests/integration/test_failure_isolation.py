"""Task 14: cross-skill failure-isolation + glob-query verification.

Hardens the contract that AgentLens **never blocks the host orchestrator**:

* **A. CLI missing from ``PATH``.** A shell snippet shaped like the
  orchestrator's ``agentlens event append ... 2>/dev/null || true`` line
  must exit 0 when ``agentlens`` is not on ``PATH`` at all.
* **B. ``AGENTLENS_HOME`` unwritable.** ``agentlens event append`` against
  a chmod-stripped ``$AGENTLENS_HOME/runs`` must exit 0 with a stderr
  warning rather than raise.
* **C. Glob namespace filtering.** ``agentlens events --type 'runway.*'``
  must surface only Waygent events from a mixed stream that also contains
  ``example.*``, ``claude.*``, and ``codex.*`` namespaces.
* **D. ``--tree`` smoke recap.** A parent + 2 children built via
  ``run-open`` and ``AGENTLENS_PARENT_RUN_ID`` must all surface when
  queried with ``events --run <parent> --tree``, in ``(ts, run_id)`` order.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.adapters.process import wrap_command
from agentlens.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    home = tmp_path / "agentlens_home"
    home.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(home))
    monkeypatch.chdir(ws)
    for var in (
        "AGENTLENS_RUN_ID",
        "AGENTLENS_RUN_DIR",
        "AGENTLENS_PARENT_RUN_ID",
        "AGENTLENS_NESTED_POLICY",
    ):
        monkeypatch.delenv(var, raising=False)
    return {"home": home, "workspace": ws}


def _open_run(
    runner: CliRunner, agent: str, parent: str | None = None
) -> str:
    args = ["run-open", "--agent", agent]
    if parent:
        args += ["--parent", parent]
    r = runner.invoke(app, args)
    assert r.exit_code == 0, r.stderr
    return r.stdout.strip()


# ---------------------------------------------------------------------------
# Test A: CLI missing from PATH must not halt orchestrator-style snippets.
# ---------------------------------------------------------------------------


def test_orchestrator_snippet_exits_zero_when_cli_missing_from_path(
    tmp_path: Path,
) -> None:
    """Simulate `agentlens event append ... 2>/dev/null || true` in a shell
    where PATH does not contain the AgentLens CLI binary.

    Spec contract: host orchestrators wrap their AgentLens
    calls in ``|| true`` so a missing CLI is non-blocking. This test
    proves the snippet itself exits 0 — the contract works even before
    any prod code is involved.
    """
    snippet = tmp_path / "snippet.sh"
    snippet.write_text(
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "agentlens event append --run X --type runway.test --payload-json '{}' "
        "2>/dev/null || true\n"
        "echo done\n",
        encoding="utf-8",
    )
    snippet.chmod(0o755)

    # Build a minimal PATH that contains coreutils but NOT the AgentLens CLI.
    # We deliberately exclude any directory that might host an ``agentlens``
    # entrypoint by using a single tmp directory we create ourselves.
    safe_bin = tmp_path / "safe_bin"
    safe_bin.mkdir()
    # Symlink only the tools the snippet needs (bash itself runs the script,
    # echo is a bash builtin).
    for tool in ("bash", "true", "env"):
        src = shutil.which(tool)
        if src is not None:
            try:
                os.symlink(src, safe_bin / tool)
            except FileExistsError:
                pass

    env = {"PATH": str(safe_bin)}

    proc = subprocess.run(
        ["bash", str(snippet)],
        env=env,
        capture_output=True,
        text=True,
    )
    # The whole point: orchestrator's snippet exits 0 even with no CLI.
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "done" in proc.stdout


# ---------------------------------------------------------------------------
# Test B: unwritable AGENTLENS_HOME/runs/ must not raise.
# ---------------------------------------------------------------------------


def test_event_append_nonblocking_when_home_unreadable(
    runner: CliRunner,
    isolated: dict[str, Path],
) -> None:
    """``event append`` against an unreadable ``AGENTLENS_HOME/runs`` must
    exit 0 with stderr-only complaint.

    Strategy:
      1. Open a run normally so the run is registered.
      2. ``chmod 0o000`` ``$AGENTLENS_HOME/runs`` so the filesystem-first
         lookup either fails to find the run or raises ``OSError``. Either
         path must NOT raise out of the Typer command — exit 0.
      3. ``event append`` must exit 0 (non-blocking contract, §4.2.3).

    This proves the orchestrator never sees a crash when AgentLens loses
    access to its own home, e.g. an unwritable mount or chmod accident.
    """
    if os.geteuid() == 0:
        pytest.skip("root bypasses chmod permission checks")

    run_id = _open_run(runner, agent="waygent")
    home = isolated["home"]
    runs = home / "runs"
    assert runs.is_dir()

    original_mode = runs.stat().st_mode
    runs.chmod(0o000)
    try:
        result = runner.invoke(
            app,
            [
                "event",
                "append",
                "--run",
                run_id,
                "--type",
                "runway.failure_isolation_probe",
                "--payload-json",
                "{}",
            ],
        )
        # Non-blocking: exit 0 even though the underlying lookup failed.
        assert result.exit_code == 0, (
            result.stdout,
            getattr(result, "stderr", ""),
        )
    finally:
        runs.chmod(original_mode | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRUSR)


def test_event_append_nonblocking_for_unknown_run(
    runner: CliRunner,
    isolated: dict[str, Path],
) -> None:
    """``event append --run <bogus>`` must exit 0 with a stderr warning,
    never raise. Mirrors the host orchestrator contract that a stale run
    id (e.g. after a cleanup ran) does not halt the workflow.
    """
    result = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            "run_does_not_exist_12345",
            "--type",
            "runway.failure_isolation_probe",
            "--payload-json",
            "{}",
        ],
    )
    assert result.exit_code == 0, (
        result.stdout,
        getattr(result, "stderr", ""),
    )


# ---------------------------------------------------------------------------
# Test C: --type glob filters per namespace across mixed event streams.
# ---------------------------------------------------------------------------


def test_events_query_filters_waygent_without_leaking_other_namespaces(
    runner: CliRunner,
    isolated: dict[str, Path],
) -> None:
    """``events --type 'runway.*'`` returns only Waygent events from
    a stream that also contains ``example.*``, ``claude.*``, and ``codex.*``.
    """
    run_id = _open_run(runner, agent="waygent")

    types = [
        "runway.task_started",
        "runway.task_finished",
        "example.phase_started",
        "example.phase_finished",
        "claude.session_started",
        "codex.tool_use",
    ]
    for t in types:
        r = runner.invoke(
            app,
            [
                "event",
                "append",
                "--run",
                run_id,
                "--type",
                t,
                "--payload-json",
                "{}",
            ],
        )
        assert r.exit_code == 0, r.stderr

    # runway.* — exactly the two Waygent events.
    r = runner.invoke(app, ["events", "--run", run_id, "--type", "runway.*"])
    assert r.exit_code == 0, r.stderr
    waygent_types = [
        json.loads(ln)["type"]
        for ln in r.stdout.strip().splitlines()
        if ln.strip()
    ]
    assert sorted(waygent_types) == [
        "runway.task_finished",
        "runway.task_started",
    ]
    assert all(t.startswith("runway.") for t in waygent_types)

    for namespace, expected in {
        "example.*": ["example.phase_finished", "example.phase_started"],
        "claude.*": ["claude.session_started"],
        "codex.*": ["codex.tool_use"],
    }.items():
        r = runner.invoke(app, ["events", "--run", run_id, "--type", namespace])
        assert r.exit_code == 0, r.stderr
        other_types = [
            json.loads(ln)["type"]
            for ln in r.stdout.strip().splitlines()
            if ln.strip()
        ]
        assert sorted(other_types) == expected
        assert not any(t.startswith("runway.") for t in other_types)


# ---------------------------------------------------------------------------
# Test D: --tree traverses parent + 2 children with explicit AGENTLENS_PARENT_RUN_ID.
# ---------------------------------------------------------------------------


def test_events_tree_includes_two_children_via_parent_env(
    runner: CliRunner,
    isolated: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parent + 2 children (linked via ``AGENTLENS_PARENT_RUN_ID``) must
    all surface in ``events --run <parent> --tree``, in ``(ts, run_id)``
    ascending order.
    """
    parent_id = _open_run(runner, agent="waygent")

    monkeypatch.setenv("AGENTLENS_PARENT_RUN_ID", parent_id)
    monkeypatch.delenv("AGENTLENS_RUN_ID", raising=False)
    monkeypatch.delenv("AGENTLENS_RUN_DIR", raising=False)

    child_ids: list[str] = []
    for label in ("child_a", "child_b"):
        result = wrap_command(
            [sys.executable, "-c", f"print({label!r})"],
            agent_name="claude_code",
            agent_mode="cli",
            mode="minimal",
        )
        assert result.exit_code == 0, result
        assert result.run_id is not None
        child_ids.append(result.run_id)

    monkeypatch.delenv("AGENTLENS_PARENT_RUN_ID", raising=False)

    # Append an event on the parent so there is at least one parent event.
    r = runner.invoke(
        app,
        [
            "event",
            "append",
            "--run",
            parent_id,
            "--type",
            "lens.parent_note",
            "--payload-json",
            "{}",
        ],
    )
    assert r.exit_code == 0, r.stderr

    r = runner.invoke(app, ["events", "--run", parent_id, "--tree"])
    assert r.exit_code == 0, r.stderr
    events = [
        json.loads(ln)
        for ln in r.stdout.strip().splitlines()
        if ln.strip()
    ]
    run_ids = {e["run_id"] for e in events}
    assert parent_id in run_ids
    for cid in child_ids:
        assert cid in run_ids, (cid, run_ids)

    # (ts, run_id) ascending.
    keys = [(e["ts"], e["run_id"]) for e in events]
    assert keys == sorted(keys), keys
