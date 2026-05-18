"""Advisory file lock with timeout and stale-PID recovery (spec §5.5, §S1.6.5).

Posix ``fcntl.flock`` is used as the underlying primitive. The lock is
advisory and process-scoped; threads in the same process do **not** contend.

The lock file path passed in is the lock file itself (e.g.
``events.jsonl.lock``); its parent directory must already exist.

Stale-PID recovery: the lock file content is ``<pid>\\n``. When acquisition
times out and the recorded PID is no longer alive (``os.kill(pid, 0)`` raises
``ProcessLookupError``), the lock file is removed and acquisition is retried
once before surfacing ``LockTimeoutError``.

The default timeout is 5 seconds per spec; callers may pass a smaller value
in tests via the ``timeout`` kwarg. The env var
``AGENTLENS_LOCK_TIMEOUT_SEC`` overrides the default when set.
"""
from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

_DEFAULT_TIMEOUT_SEC = 5.0
_POLL_INTERVAL_SEC = 0.05


class LockTimeoutError(Exception):
    """Raised when the lock cannot be acquired within the timeout window."""


def _resolve_timeout(timeout: float | None) -> float:
    if timeout is not None:
        return float(timeout)
    env = os.environ.get("AGENTLENS_LOCK_TIMEOUT_SEC")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return _DEFAULT_TIMEOUT_SEC


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user.
        return True
    except OSError as exc:  # pragma: no cover - defensive
        if exc.errno == errno.ESRCH:
            return False
        return True
    return True


def _read_pid(path: Path) -> int | None:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    if not content:
        return None
    try:
        return int(content.split()[0])
    except (ValueError, IndexError):
        return None


@contextmanager
def file_lock(
    path: Path,
    mode: Literal["exclusive", "shared"] = "exclusive",
    *,
    timeout: float | None = None,
) -> Iterator[None]:
    """Acquire an advisory ``fcntl.flock`` on *path*.

    Args:
        path: lock file path (its parent must exist).
        mode: ``"exclusive"`` (LOCK_EX) or ``"shared"`` (LOCK_SH).
        timeout: seconds to wait before raising ``LockTimeoutError``.
            ``None`` -> read ``AGENTLENS_LOCK_TIMEOUT_SEC`` env var or
            fall back to the spec default (5s).

    Raises:
        LockTimeoutError: if the lock cannot be acquired within ``timeout``.
    """
    if mode == "exclusive":
        flock_op = fcntl.LOCK_EX
    elif mode == "shared":
        flock_op = fcntl.LOCK_SH
    else:
        raise ValueError(f"unknown lock mode: {mode!r}")

    resolved_timeout = _resolve_timeout(timeout)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + resolved_timeout
        stale_recovery_attempted = False
        while True:
            try:
                fcntl.flock(fd, flock_op | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    # Try one stale-PID recovery before giving up.
                    if not stale_recovery_attempted:
                        stale_recovery_attempted = True
                        pid = _read_pid(path)
                        if pid is not None and not _is_pid_alive(pid):
                            # Best-effort unlink; if it fails, surface the
                            # original timeout.
                            try:
                                os.unlink(str(path))
                            except FileNotFoundError:
                                pass
                            # Continue the loop briefly to retry.
                            deadline = time.monotonic() + _POLL_INTERVAL_SEC * 4
                            continue
                    raise LockTimeoutError(
                        f"timed out after {resolved_timeout}s waiting for {path}"
                    )
                time.sleep(_POLL_INTERVAL_SEC)

        # Record our PID for stale detection by other waiters.
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            os.fsync(fd)
        except OSError:
            # Non-fatal; lock is still held.
            pass

        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


__all__ = ["LockTimeoutError", "file_lock"]
