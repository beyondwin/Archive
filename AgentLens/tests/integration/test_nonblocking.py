"""M5/M8 non-blocking fault-injection passthrough (spec §5.16, §S1.6.17, §10.4).

Verifies the §5.16 invariant: ``WrapperResult.exit_code`` ALWAYS reflects the
child's real exit code (or ``128+signum`` on signal), regardless of any
AgentLens-internal failure in the recording pipeline.

Each test injects a fault at a specific pipeline stage via
``unittest.mock.patch`` and asserts the wrapper still returns the child's
real exit code. The pipeline stages exercised:

  * ``compute_workspace_id``         (run-init / workspace_id derivation)
  * ``write_run_meta``               (run-init / ER-1 fix)
  * ``append_event(run.started)``    (run-init)
  * ``append_event(command.*)``      (best-effort during pipeline)
  * ``write_final``                  (final.json branches)
  * ``seal(pre_eval)``               (manifest pre-eval seal)
  * ``evaluate``                     (evaluator crash)
  * ``seal(final)``                  (final seal — manifest write)
  * ``index_run``                    (SQLite update)
  * SIGINT forwarding                (signal handler path)

Plus the "pre_eval seal fails → recording_incomplete marked" scenario.

The §10.4 6-fault-inject contract requires NAMED coverage of:

  1. run initialization (workspace_id compute fails)
  2. manifest write fails (pre_eval seal / final seal)
  3. evaluator crash
  4. SQLite update fails
  5. pre_eval seal fails (→ recording_incomplete)
  6. SIGINT received (→ 128+signum, agent_outcome=cancelled)
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from agentlens.adapters import process as proc
from agentlens.adapters.process import WrapperResult, wrap_command


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin AGENTLENS_HOME to a tmp dir so tests don't touch ~/.agentlens."""
    home = tmp_path / "agentlens_home"
    home.mkdir()
    monkeypatch.setenv("AGENTLENS_HOME", str(home))
    # cd into a tmp workspace so compute_workspace_id resolves predictably.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    return home


def _exit42_argv() -> list[str]:
    return [sys.executable, "-c", "import sys; sys.exit(42)"]


def _exit0_argv() -> list[str]:
    return [sys.executable, "-c", "print('ok')"]


def _read_manifest(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "manifest.json").read_text())


def _find_run_dir(home: Path) -> Path | None:
    """Locate the first run_dir under ``<home>/runs/<ws>/<run_id>``."""
    runs_root = home / "runs"
    if not runs_root.is_dir():
        return None
    for ws in runs_root.iterdir():
        if not ws.is_dir():
            continue
        for run in ws.iterdir():
            if run.is_dir() and run.name.startswith("run_"):
                return run
    return None


# ---------------------------------------------------------------------------
# Baseline: success path produces full pipeline output
# ---------------------------------------------------------------------------


def test_baseline_full_pipeline_records_and_preserves_exit_code(
    isolated_home: Path,
) -> None:
    """Sanity check: no faults, the wrapper records and exit code is correct."""
    result = wrap_command(
        _exit42_argv(),
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert isinstance(result, WrapperResult)
    assert result.exit_code == 42
    # run_dir should exist with a sealed manifest.
    run_dir = _find_run_dir(isolated_home)
    assert run_dir is not None
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "final.json").is_file()
    assert (run_dir / "manifest.json").is_file()
    manifest = _read_manifest(run_dir)
    assert manifest["sealed_phase"] == "final"


# ---------------------------------------------------------------------------
# Fault: write_run_meta fails (ER-1 fix)
# ---------------------------------------------------------------------------


def test_write_run_meta_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """If write_run_meta raises, child command still runs and exit code is preserved."""
    with mock.patch.object(
        proc, "write_run_meta", side_effect=RuntimeError("disk full")
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42
    # Recording was not initialized — run_id is None on failure path.
    assert result.run_id is None


# ---------------------------------------------------------------------------
# Fault: append_event(run.started) fails during init
# ---------------------------------------------------------------------------


def test_run_started_append_event_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """If the run.started append_event raises during init, child exit code stays."""
    with mock.patch.object(
        proc, "append_event", side_effect=RuntimeError("write fail")
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42
    assert result.run_id is None


# ---------------------------------------------------------------------------
# Fault: command.started/finished append_event fails (best-effort post-init)
# ---------------------------------------------------------------------------


def test_command_event_append_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """append_event for command.* during the pipeline must NEVER block exit.

    Set up so the run.started succeeds (we let init complete) but subsequent
    append_event calls inside the post-drain pipeline raise. The simplest
    way: patch append_event to raise only after the first successful call.
    """
    call_count = {"n": 0}
    real = proc.append_event

    def _selective(*args: Any, **kwargs: Any) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            real(*args, **kwargs)
            return
        raise RuntimeError("event log failed mid-pipeline")

    with mock.patch.object(proc, "append_event", side_effect=_selective):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42


# ---------------------------------------------------------------------------
# Fault: write_final fails
# ---------------------------------------------------------------------------


def test_write_final_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """write_final raising must NOT change wrapper exit_code."""
    with mock.patch.object(
        proc, "write_final", side_effect=RuntimeError("final write fail")
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42


# ---------------------------------------------------------------------------
# Fault: seal(pre_eval) fails → mark recording_incomplete
# ---------------------------------------------------------------------------


def test_pre_eval_seal_failure_marks_recording_incomplete_and_preserves_exit_code(
    isolated_home: Path,
) -> None:
    """When pre_eval seal raises, the wrapper falls back to recording_incomplete.

    Child exit code must still be preserved.
    """
    call_count = {"n": 0}
    real_seal = proc.seal

    def _selective_seal(run_dir: Path, phase: str) -> None:
        call_count["n"] += 1
        # Fail the first seal call (pre_eval); subsequent recording_incomplete
        # fallback should succeed (real_seal).
        if call_count["n"] == 1:
            raise RuntimeError("pre_eval seal fail")
        real_seal(run_dir, phase)

    with mock.patch.object(proc, "seal", side_effect=_selective_seal):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42

    run_dir = _find_run_dir(isolated_home)
    assert run_dir is not None
    manifest = _read_manifest(run_dir)
    assert manifest["sealed_phase"] == "recording_incomplete"


def test_pre_eval_seal_failure_and_recording_incomplete_also_fails_preserves_exit_code(
    isolated_home: Path,
) -> None:
    """Even if BOTH pre_eval seal AND the recording_incomplete fallback fail,
    the wrapper must still return the child's exit code (double-guard)."""
    with mock.patch.object(
        proc, "seal", side_effect=RuntimeError("all seal calls fail")
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42


# ---------------------------------------------------------------------------
# Fault: evaluate() crashes
# ---------------------------------------------------------------------------


def test_evaluate_crash_preserves_child_exit_code_and_marks_recording_incomplete(
    isolated_home: Path,
) -> None:
    """evaluate() raising must NOT change exit code; recording is marked incomplete."""
    with mock.patch.object(
        proc, "evaluate", side_effect=RuntimeError("evaluator crashed")
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42

    run_dir = _find_run_dir(isolated_home)
    assert run_dir is not None
    manifest = _read_manifest(run_dir)
    assert manifest["sealed_phase"] == "recording_incomplete"


# ---------------------------------------------------------------------------
# Fault: seal(final) fails
# ---------------------------------------------------------------------------


def test_final_seal_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """seal(final) failing is best-effort; exit code must be preserved."""
    call_count = {"n": 0}
    real_seal = proc.seal

    def _selective_seal(run_dir: Path, phase: str) -> None:
        call_count["n"] += 1
        if phase == "final":
            raise RuntimeError("final seal fail")
        real_seal(run_dir, phase)

    with mock.patch.object(proc, "seal", side_effect=_selective_seal):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42


# ---------------------------------------------------------------------------
# Fault: SQLite index_run fails
# ---------------------------------------------------------------------------


def test_index_run_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """SQLite update failing must be swallowed; exit code preserved."""
    with mock.patch.object(
        proc, "index_run", side_effect=RuntimeError("sqlite blew up")
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42


def test_open_db_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """open_db failing (before index_run can be called) must be swallowed too."""
    with mock.patch.object(
        proc, "open_db", side_effect=RuntimeError("cannot open db")
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42


# ---------------------------------------------------------------------------
# Fault: write_workspace_pointer fails during init
# ---------------------------------------------------------------------------


def test_workspace_pointer_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """write_workspace_pointer raising during init → recording disabled, exit preserved."""
    with mock.patch.object(
        proc, "write_workspace_pointer", side_effect=RuntimeError("pointer fail")
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42
    assert result.run_id is None


# ---------------------------------------------------------------------------
# Edge: zero exit code with init failure still passes through 0
# ---------------------------------------------------------------------------


def test_init_failure_with_zero_exit_still_returns_zero(
    isolated_home: Path,
) -> None:
    """The §5.16 invariant must hold even for exit_code == 0."""
    with mock.patch.object(
        proc, "write_run_meta", side_effect=RuntimeError("init fail")
    ):
        result = wrap_command(
            _exit0_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 0
    assert result.run_id is None


# ---------------------------------------------------------------------------
# §10.4 fault-inject scenario 1: compute_workspace_id raises during init
# ---------------------------------------------------------------------------


def test_compute_workspace_id_failure_preserves_child_exit_code(
    isolated_home: Path,
) -> None:
    """When ``compute_workspace_id`` raises in init, the wrapper takes the
    ER-1 passthrough branch: child still runs, exit code is the child's, and
    ``run_id`` is ``None`` because recording never came up (spec §S1.6.17)."""
    with mock.patch.object(
        proc,
        "compute_workspace_id",
        side_effect=RuntimeError("workspace_id basis lookup blew up"),
    ):
        result = wrap_command(
            _exit42_argv(),
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    assert result.exit_code == 42
    assert result.run_id is None
    # No run_dir was created — the init function bailed before mkdir.
    assert _find_run_dir(isolated_home) is None


# ---------------------------------------------------------------------------
# §10.4 fault-inject scenario 6: SIGINT received → 128+SIGINT, cancelled
# ---------------------------------------------------------------------------


def _sigint_self_after(delay: float) -> threading.Timer:
    """Schedule ``os.kill(os.getpid(), SIGINT)`` after ``delay`` seconds.

    The Timer thread fires SIGINT to the test process; wrap_command's signal
    handler (installed on the main thread) catches it, forwards to the child,
    and the wrapper returns ``128 + SIGINT`` as the exit code.
    """
    t = threading.Timer(delay, lambda: os.kill(os.getpid(), signal.SIGINT))
    t.daemon = True
    t.start()
    return t


def test_sigint_forwarded_yields_128_plus_signum_and_cancelled_final(
    isolated_home: Path,
) -> None:
    """SIGINT delivered to the parent must be forwarded to the long-running
    child; the wrapper exit code is ``128 + signal.SIGINT`` (typically 130),
    ``cancelled_by_signal == "SIGINT"``, and ``final.json`` carries
    ``agent_outcome == "cancelled"`` with ``exit_signal == "SIGINT"``."""
    # Child sleeps long enough for the timer to fire (~0.5s after spawn).
    sleep_argv = [
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
    ]
    timer = _sigint_self_after(0.5)
    try:
        result = wrap_command(
            sleep_argv,
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    finally:
        timer.cancel()

    assert result.cancelled_by_signal == "SIGINT"
    assert result.exit_code == 128 + int(signal.SIGINT)
    # Run was initialised (signal hit during drain, not during init).
    assert result.run_id is not None

    run_dir = _find_run_dir(isolated_home)
    assert run_dir is not None

    # final.json reflects cancellation.
    final_doc = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final_doc["agent_outcome"] == "cancelled"
    assert final_doc.get("exit_signal") == "SIGINT"
    # The child's real exit code (which the kernel reports as -SIGINT) is
    # stored verbatim — separate from the wrapper's 128+signum return value.
    assert "exit_code" in final_doc

    # Cancelled runs still seal to "final" so the post-drain pipeline ran.
    manifest = _read_manifest(run_dir)
    assert manifest["sealed_phase"] == "final"
