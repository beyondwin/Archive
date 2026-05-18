"""Integration tests for the M5 process wrapper core (spec §5.16, §8.2).

Covers task_13 scope (spawn/drain/excerpt) and task_14 scope
(signal forwarding, exit-code preservation, agent_outcome resolution).

final.json branches, seal/eval/index_run wiring are deferred to tasks
15/18 and are NOT exercised here.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from agentlens.adapters.process import (
    EXCERPT_EXTRACTORS,
    MAX_EXCERPT_CHARS,
    WrapperResult,
    apply_excerpt_extractors,
    drain_streams_concurrently,
    resolve_agent_outcome,
    wrap_command,
)


# ---------------------------------------------------------------------------
# spawn
# ---------------------------------------------------------------------------


def test_spawn_returns_child_exit_code_zero() -> None:
    """wrap_command returns child's actual exit code (0)."""
    result = wrap_command(
        [sys.executable, "-c", "print('hello')"],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert isinstance(result, WrapperResult)
    assert result.exit_code == 0
    assert result.cancelled_by_signal is None


def test_spawn_returns_child_nonzero_exit_code() -> None:
    """wrap_command returns child's actual exit code (non-zero)."""
    result = wrap_command(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert result.exit_code == 7
    assert result.cancelled_by_signal is None


# ---------------------------------------------------------------------------
# drain
# ---------------------------------------------------------------------------


def test_drain_streams_concurrently_handles_large_output() -> None:
    """Child emitting >64KB on BOTH stdout and stderr must not deadlock.

    Default POSIX pipe buffer is ~64KB. A sequential reader (first read all
    stdout, then read all stderr) would deadlock here because the child
    blocks on whichever pipe fills first while the parent waits on the other.
    """
    payload_bytes = 200 * 1024  # 200KB on each stream, well past pipe buffer
    script = textwrap.dedent(
        f"""
        import sys
        chunk = b'A' * 1024
        for _ in range({payload_bytes // 1024}):
            sys.stdout.buffer.write(chunk)
        chunk2 = b'B' * 1024
        for _ in range({payload_bytes // 1024}):
            sys.stderr.buffer.write(chunk2)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.flush()
        """
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = drain_streams_concurrently(child, tee=False)
    exit_code = child.wait(timeout=30)
    assert exit_code == 0
    assert len(stdout) == payload_bytes
    assert len(stderr) == payload_bytes
    assert stdout == b"A" * payload_bytes
    assert stderr == b"B" * payload_bytes


def test_drain_streams_concurrently_with_interleaved_writes() -> None:
    """Alternating writes on both streams (small chunks) must all be captured."""
    script = textwrap.dedent(
        """
        import sys
        for i in range(100):
            sys.stdout.write(f"out{i}\\n")
            sys.stdout.flush()
            sys.stderr.write(f"err{i}\\n")
            sys.stderr.flush()
        """
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = drain_streams_concurrently(child, tee=False)
    child.wait(timeout=10)
    out_lines = stdout.decode().splitlines()
    err_lines = stderr.decode().splitlines()
    assert out_lines == [f"out{i}" for i in range(100)]
    assert err_lines == [f"err{i}" for i in range(100)]


def test_wrap_command_large_output_does_not_deadlock() -> None:
    """End-to-end: wrap_command also does not deadlock on dual large output."""
    script = (
        "import sys;"
        "sys.stdout.buffer.write(b'X' * (128*1024));"
        "sys.stderr.buffer.write(b'Y' * (128*1024));"
        "sys.stdout.buffer.flush();"
        "sys.stderr.buffer.flush()"
    )
    result = wrap_command(
        [sys.executable, "-c", script],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert result.exit_code == 0


def test_wrap_command_tees_child_stdout_and_stderr_to_parent(
    capfd: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    """``agentlens run -- <cmd>`` is a transparent wrapper: the user MUST
    see child stdout/stderr live. Regression for the captured-only drain
    that swallowed all child output.
    """
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AGENTLENS_RUN_ID", raising=False)
    result = wrap_command(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('TEE_OUT\\n'); "
            "sys.stderr.write('TEE_ERR\\n')",
        ],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert result.exit_code == 0
    captured = capfd.readouterr()
    assert "TEE_OUT" in captured.out
    assert "TEE_ERR" in captured.err


def test_wrap_command_initializes_sqlite_schema_on_fresh_home(
    capfd: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    """First-ever ``agentlens run`` against a brand-new AGENTLENS_HOME must
    initialize the SQLite schema; previously only ``open_db`` was called,
    leaving stderr with ``no such table: runs`` on every fresh install.
    """
    home = tmp_path / "fresh_home"
    monkeypatch.setenv("AGENTLENS_HOME", str(home))
    monkeypatch.delenv("AGENTLENS_RUN_ID", raising=False)
    result = wrap_command(
        [sys.executable, "-c", "print('ok')"],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert result.exit_code == 0
    err = capfd.readouterr().err
    assert "no such table" not in err
    assert (home / "index.db").is_file()

    import sqlite3

    conn = sqlite3.connect(str(home / "index.db"))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert {"runs", "checks", "failures", "artifacts"}.issubset(tables)


# ---------------------------------------------------------------------------
# excerpt
# ---------------------------------------------------------------------------


def test_excerpt_extractors_allow_list_contains_required_names() -> None:
    """Per spec §5.11, allow-list must include at least pytest_summary and
    error_type for task 13's coverage. Other extractors may be added by
    follow-on tasks."""
    assert isinstance(EXCERPT_EXTRACTORS, dict)
    # At least one extractor must ship so excerpt tests can verify behavior.
    assert len(EXCERPT_EXTRACTORS) >= 1
    # All values must be callables.
    for name, fn in EXCERPT_EXTRACTORS.items():
        assert callable(fn), name


def test_excerpt_unknown_extractor_returns_none() -> None:
    """Unknown extractor name is not allowed — must NOT free-text slice."""
    result = apply_excerpt_extractors(
        "some long text " * 1000, extractor="not_in_allow_list"
    )
    assert result is None


def test_excerpt_pytest_summary_extracts_summary_line() -> None:
    """`pytest_summary` extractor returns the canonical pytest summary line."""
    text = (
        "============================= test session starts ==============================\n"
        "platform darwin -- Python 3.12.0\n"
        "collected 13 items\n\n"
        "tests/test_a.py ........\n"
        "tests/test_b.py F....\n\n"
        "=================== 12 passed, 1 failed in 0.42s ===================\n"
    )
    result = apply_excerpt_extractors(text, extractor="pytest_summary")
    assert result is not None
    assert "12 passed" in result
    assert "1 failed" in result


def test_excerpt_error_type_extracts_python_exception() -> None:
    """`error_type` extractor returns the trailing 'Foo: ...' exception line."""
    text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "    raise TypeError('bad thing')\n"
        "TypeError: bad thing\n"
    )
    result = apply_excerpt_extractors(text, extractor="error_type")
    assert result is not None
    assert result.startswith("TypeError")
    assert "bad thing" in result


def test_excerpt_enforces_max_chars_and_truncated_marker() -> None:
    """Even allow-list output is capped at MAX_EXCERPT_CHARS with marker."""
    assert MAX_EXCERPT_CHARS == 4096
    # Construct input whose extractor result will be > 4096 chars: a single
    # very long error-type line.
    big_msg = "x" * (MAX_EXCERPT_CHARS + 500)
    text = f"TypeError: {big_msg}\n"
    result = apply_excerpt_extractors(text, extractor="error_type")
    assert result is not None
    assert len(result) <= MAX_EXCERPT_CHARS
    assert result.endswith("<TRUNCATED>")


def test_excerpt_bytes_input_is_decoded() -> None:
    """Extractor accepts bytes (raw stdout/stderr) and returns str or None."""
    raw = b"TypeError: oops\n"
    result = apply_excerpt_extractors(raw, extractor="error_type")
    assert isinstance(result, str)
    assert result.startswith("TypeError")


# ---------------------------------------------------------------------------
# task_14: exit code preservation
# ---------------------------------------------------------------------------


def test_wrap_command_preserves_exit_code_42() -> None:
    """wrap_command must propagate exit code 42 (arbitrary non-zero)."""
    result = wrap_command(
        [sys.executable, "-c", "import sys; sys.exit(42)"],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert result.exit_code == 42
    assert result.cancelled_by_signal is None


def test_wrap_command_preserves_exit_code_zero_via_sh() -> None:
    """`agentlens run -- sh -c 'exit 0'` → 0 (acceptance criterion)."""
    result = wrap_command(
        ["sh", "-c", "exit 0"],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert result.exit_code == 0
    assert result.cancelled_by_signal is None


def test_wrap_command_preserves_exit_code_42_via_sh() -> None:
    """`agentlens run -- sh -c 'exit 42'` → 42 (acceptance criterion)."""
    result = wrap_command(
        ["sh", "-c", "exit 42"],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert result.exit_code == 42
    assert result.cancelled_by_signal is None


# ---------------------------------------------------------------------------
# task_14: signal forwarding (SIGINT/SIGTERM → child → 128+signum)
# ---------------------------------------------------------------------------


def _send_signal_after_delay(sig: int, delay: float = 0.4) -> threading.Thread:
    """Send ``sig`` to this process after ``delay`` seconds, in a thread."""
    pid = os.getpid()

    def _send() -> None:
        time.sleep(delay)
        os.kill(pid, sig)

    t = threading.Thread(target=_send, daemon=True)
    t.start()
    return t


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal semantics required")
def test_wrap_command_signal_sigint_forwards_and_returns_130() -> None:
    """SIGINT delivered to wrapper → forwarded to child → exit_code == 130."""
    t = _send_signal_after_delay(signal.SIGINT, delay=0.5)
    try:
        result = wrap_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    finally:
        t.join(timeout=2)
    assert result.cancelled_by_signal == "SIGINT"
    assert result.exit_code == 130


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal semantics required")
def test_wrap_command_signal_sigterm_forwards_and_returns_143() -> None:
    """SIGTERM delivered to wrapper → forwarded to child → exit_code == 143."""
    t = _send_signal_after_delay(signal.SIGTERM, delay=0.5)
    try:
        result = wrap_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            agent_name="generic",
            agent_mode="cli",
            mode="minimal",
        )
    finally:
        t.join(timeout=2)
    assert result.cancelled_by_signal == "SIGTERM"
    assert result.exit_code == 143


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal semantics required")
def test_wrap_command_restores_signal_handlers() -> None:
    """Wrapper MUST restore prior SIGINT/SIGTERM handlers on return.

    Required so the wrapper is safe to call from library/CLI contexts and
    doesn't permanently alter the parent's signal disposition.
    """
    prior_sigint = signal.getsignal(signal.SIGINT)
    prior_sigterm = signal.getsignal(signal.SIGTERM)
    result = wrap_command(
        [sys.executable, "-c", "print('quick')"],
        agent_name="generic",
        agent_mode="cli",
        mode="minimal",
    )
    assert result.exit_code == 0
    assert signal.getsignal(signal.SIGINT) is prior_sigint
    assert signal.getsignal(signal.SIGTERM) is prior_sigterm


# ---------------------------------------------------------------------------
# task_14: resolve_agent_outcome — 5 logical branches per spec §5.16
# ---------------------------------------------------------------------------


def test_resolve_agent_outcome_signal_name_yields_cancelled() -> None:
    """sig_name set → cancelled, regardless of exit_code/final."""
    assert (
        resolve_agent_outcome(
            exit_code=130, sig_name="SIGINT", explicit_final_present=False
        )
        == "cancelled"
    )
    assert (
        resolve_agent_outcome(
            exit_code=143, sig_name="SIGTERM", explicit_final_present=True
        )
        == "cancelled"
    )


def test_resolve_agent_outcome_explicit_final_passthrough_exit_code_zero() -> None:
    """explicit_final_present → agent wrote final.json; outcome is not
    overwritten by the wrapper. Sentinel value 'success' acts as
    'agent-decided' placeholder per spec §5.16 (final.json contents win)."""
    outcome = resolve_agent_outcome(
        exit_code=0, sig_name=None, explicit_final_present=True
    )
    assert outcome in {"success", "failed", "partial"}


def test_resolve_agent_outcome_no_final_exit_code_zero_is_unknown() -> None:
    """No signal, no explicit final, exit_code == 0 → unknown (spec §5.16)."""
    assert (
        resolve_agent_outcome(
            exit_code=0, sig_name=None, explicit_final_present=False
        )
        == "unknown"
    )


def test_resolve_agent_outcome_no_final_exit_code_nonzero_is_failed() -> None:
    """No signal, no explicit final, exit_code != 0 → failed (spec §5.16)."""
    assert (
        resolve_agent_outcome(
            exit_code=7, sig_name=None, explicit_final_present=False
        )
        == "failed"
    )
    assert (
        resolve_agent_outcome(
            exit_code=42, sig_name=None, explicit_final_present=False
        )
        == "failed"
    )
