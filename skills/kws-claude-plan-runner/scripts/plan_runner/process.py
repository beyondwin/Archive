from __future__ import annotations

import hashlib
import math
import os
import shutil
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    kind: str
    exit_code: int | None
    stdout_tail: bytes
    stderr_tail: bytes
    stdout_digest: str
    stderr_digest: str
    started_at: str
    finished_at: str
    forced_kill: bool


def _digest_fd(descriptor: int) -> str:
    hasher = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while block := os.read(descriptor, 1024 * 1024):
        hasher.update(block)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return hasher.hexdigest()


@dataclass
class OpenedExecutable:
    path: Path
    fd: int
    sha256: str
    mode: int
    size: int
    device: int
    inode: int

    def identity(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "mode": self.mode,
            "size": self.size,
        }

    def revalidate(self) -> None:
        try:
            descriptor = os.open(
                self.path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            )
        except OSError as error:
            raise ValueError("command executable changed") from error
        try:
            metadata = os.fstat(descriptor)
            current = (
                metadata.st_dev, metadata.st_ino, metadata.st_mode,
                metadata.st_size, _digest_fd(descriptor),
            )
        finally:
            os.close(descriptor)
        expected = (self.device, self.inode, self.mode, self.size, self.sha256)
        if current != expected:
            raise ValueError("command executable changed")

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "OpenedExecutable":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> bool:
        self.close()
        return False


def _locate(argv0: str, cwd: Path, env: Mapping[str, str]) -> Path:
    located = shutil.which(argv0, path=env.get("PATH"))
    if located is None:
        raise ValueError("command executable is unavailable")
    candidate = Path(located)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        resolved = candidate.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as error:
        raise ValueError("command executable is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise ValueError("command executable is unavailable")
    return resolved


def open_executable(argv0: str, *, cwd: Path, env: Mapping[str, str]) -> OpenedExecutable:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("executable identity validation is unsupported")
    executable = _locate(argv0, cwd, env)
    try:
        descriptor = os.open(executable, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError("command executable is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
            raise ValueError("command executable is unavailable")
        return OpenedExecutable(
            executable, descriptor, _digest_fd(descriptor), metadata.st_mode,
            metadata.st_size, metadata.st_dev, metadata.st_ino,
        )
    except BaseException:
        os.close(descriptor)
        raise


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _Drain:
    def __init__(self, stream, limit: int) -> None:
        self.stream = stream
        self.limit = limit
        self.digest = hashlib.sha256()
        self.tail = bytearray()
        self.thread = threading.Thread(target=self._read, daemon=True)

    def _read(self) -> None:
        try:
            while chunk := self.stream.read(65536):
                self.digest.update(chunk)
                if self.limit:
                    self.tail.extend(chunk)
                    overflow = len(self.tail) - self.limit
                    if overflow > 0:
                        del self.tail[:overflow]
        finally:
            self.stream.close()


def _valid_inputs(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    deadline_seconds: float,
    output_limit: int,
) -> None:
    if not argv or any(not isinstance(item, str) or not item or "\0" in item for item in argv):
        raise ValueError("argv must contain non-empty strings without NUL")
    if (
        isinstance(deadline_seconds, bool)
        or not isinstance(deadline_seconds, (int, float))
        or not math.isfinite(deadline_seconds)
        or deadline_seconds <= 0
    ):
        raise ValueError("deadline_seconds must be finite and positive")
    if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit < 0:
        raise ValueError("output_limit must be a non-negative integer")
    if not cwd.is_dir():
        raise ValueError("command cwd must be an existing directory")
    if any("\0" in str(key) or "\0" in str(value) for key, value in env.items()):
        raise ValueError("command environment must contain NUL-free strings")


def _signal_group(pgid: int, sig: signal.Signals) -> bool:
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as error:
        raise RuntimeError("command process group is unverifiable") from error


def _settle_group(process: subprocess.Popen[bytes], *, terminate: bool) -> bool:
    forced = False
    if terminate:
        _signal_group(process.pid, signal.SIGTERM)
    until = time.monotonic() + 1.0
    while process.poll() is None and time.monotonic() < until:
        time.sleep(0.01)
    # A leader may have exited while descendants retained the group/pipes.
    if process.poll() is not None:
        _signal_group(process.pid, signal.SIGTERM)
    time.sleep(0.02)
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        raise RuntimeError("command process group is unverifiable") from error
    else:
        forced = True
        _signal_group(process.pid, signal.SIGKILL)
    if process.poll() is None:
        forced = True
        try:
            process.kill()
        except OSError:
            pass
    process.wait(timeout=1)
    return forced


def run_exact(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    deadline_seconds: float,
    output_limit: int = 1_048_576,
    executable_path: Path | None = None,
    opened_executable: OpenedExecutable | None = None,
) -> ProcessResult:
    _valid_inputs(argv, cwd, env, deadline_seconds, output_limit)
    if executable_path is not None and opened_executable is not None:
        raise ValueError("exactly one executable source may be supplied")
    if opened_executable is not None:
        if opened_executable.fd < 0:
            raise ValueError("opened executable is closed")
        opened_executable.revalidate()
        executable = opened_executable.path
    elif executable_path is not None:
        executable = Path(executable_path)
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("command executable is unavailable")
    else:
        executable = _locate(argv[0], cwd, env)

    started_at, started = _iso_now(), time.monotonic()
    process = subprocess.Popen(
        list(argv), executable=str(executable), cwd=cwd, env=dict(env),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, start_new_session=True,
    )
    try:
        if opened_executable is not None:
            opened_executable.revalidate()
        try:
            if os.getpgid(process.pid) != process.pid:
                raise RuntimeError("command did not create an isolated process group")
        except ProcessLookupError:
            pass
    except BaseException:
        _settle_group(process, terminate=True)
        raise

    assert process.stdout is not None and process.stderr is not None
    stdout, stderr = _Drain(process.stdout, output_limit), _Drain(process.stderr, output_limit)
    stdout.thread.start()
    stderr.thread.start()
    timed_out = False
    while process.poll() is None:
        if time.monotonic() - started >= deadline_seconds:
            timed_out = True
            break
        time.sleep(0.01)
    forced = _settle_group(process, terminate=timed_out)
    stdout.thread.join(1)
    stderr.thread.join(1)
    if stdout.thread.is_alive() or stderr.thread.is_alive():
        raise RuntimeError("command output streams did not close")
    code = None if timed_out else process.returncode
    return ProcessResult(
        kind="verification_timed_out" if timed_out else ("success" if code == 0 else "failed"),
        exit_code=code,
        stdout_tail=bytes(stdout.tail),
        stderr_tail=bytes(stderr.tail),
        stdout_digest=stdout.digest.hexdigest(),
        stderr_digest=stderr.digest.hexdigest(),
        started_at=started_at,
        finished_at=_iso_now(),
        forced_kill=forced,
    )
