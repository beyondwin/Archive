"""Tests for agentlens.store.lock (S1.6.5)."""
from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest

from agentlens.store.lock import LockTimeoutError, file_lock


def _hold_lock_in_subprocess(lock_path: str, hold_secs: float, ready_path: str) -> None:
    """Acquire an exclusive lock in a subprocess and hold it for `hold_secs`."""
    from agentlens.store.lock import file_lock as _fl

    with _fl(Path(lock_path), mode="exclusive"):
        Path(ready_path).write_text("ready")
        time.sleep(hold_secs)


def _hold_shared_in_subprocess(lock_path: str, hold_secs: float, ready_path: str) -> None:
    from agentlens.store.lock import file_lock as _fl

    with _fl(Path(lock_path), mode="shared"):
        Path(ready_path).write_text("ready")
        time.sleep(hold_secs)


def test_file_lock_basic_acquire_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    with file_lock(lock_path):
        # While held, the lock file should exist.
        assert lock_path.exists()
    # After release, file may or may not be present; either way no error.


def test_file_lock_creates_lock_file_in_existing_parent(tmp_path: Path) -> None:
    parent = tmp_path / "sub"
    parent.mkdir()
    lock_path = parent / "events.jsonl.lock"
    with file_lock(lock_path):
        assert lock_path.exists()


def test_file_lock_timeout_when_other_process_holds(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    ready = tmp_path / "ready"
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_hold_lock_in_subprocess, args=(str(lock_path), 3.0, str(ready)))
    proc.start()
    try:
        # Wait for the subprocess to acquire the lock.
        deadline = time.monotonic() + 5.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "subprocess never acquired the lock"

        with pytest.raises(LockTimeoutError):
            with file_lock(lock_path, mode="exclusive", timeout=0.3):
                pass
    finally:
        proc.join(timeout=10)


def test_file_lock_shared_allows_multiple_readers(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    ready = tmp_path / "ready"
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_hold_shared_in_subprocess, args=(str(lock_path), 2.0, str(ready)))
    proc.start()
    try:
        deadline = time.monotonic() + 5.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "subprocess never acquired the shared lock"

        # A second shared lock should succeed quickly.
        with file_lock(lock_path, mode="shared", timeout=1.0):
            pass
    finally:
        proc.join(timeout=10)


def test_file_lock_shared_blocked_by_exclusive(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    ready = tmp_path / "ready"
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_hold_lock_in_subprocess, args=(str(lock_path), 3.0, str(ready)))
    proc.start()
    try:
        deadline = time.monotonic() + 5.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()

        with pytest.raises(LockTimeoutError):
            with file_lock(lock_path, mode="shared", timeout=0.3):
                pass
    finally:
        proc.join(timeout=10)


def test_file_lock_sequential_in_same_process(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    with file_lock(lock_path, timeout=1.0):
        pass
    # Should be reusable.
    with file_lock(lock_path, timeout=1.0):
        pass


def test_file_lock_default_timeout_kwarg(tmp_path: Path) -> None:
    """Default timeout is 5s (spec); test by passing explicit kwarg=None falls back."""
    lock_path = tmp_path / "x.lock"
    # Just verify default branch is exercised (no contention -> immediate success).
    with file_lock(lock_path):
        pass
