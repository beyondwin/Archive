from __future__ import annotations

import hashlib
import math
import os
import selectors
import shutil
import signal
import stat
import subprocess
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


def _retain_tail(tail: bytearray, chunk: bytes, limit: int) -> None:
    if limit == 0:
        tail.clear()
        return
    tail.extend(chunk)
    if (excess := len(tail) - limit) > 0:
        del tail[:excess]


def _observe_group(pgid: int, *, timeout: float) -> dict[int, str]:
    """Inspect one process group without a shell or user-controlled arguments."""
    try:
        result = subprocess.run(
            ("/bin/ps", "-axo", "pid=,pgid=,stat="),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("command process group is unverifiable") from error
    if result.returncode != 0:
        raise RuntimeError("command process group is unverifiable")
    try:
        rows = result.stdout.decode("ascii").splitlines()
    except (AttributeError, UnicodeDecodeError) as error:
        raise RuntimeError("command process group is unverifiable") from error
    members: dict[int, str] = {}
    for row in rows:
        fields = row.split()
        if not fields:
            continue
        if len(fields) != 3:
            raise RuntimeError("command process group is unverifiable")
        try:
            pid, group = int(fields[0]), int(fields[1])
        except ValueError as error:
            raise RuntimeError("command process group is unverifiable") from error
        if pid <= 0 or group <= 0 or not fields[2]:
            raise RuntimeError("command process group is unverifiable")
        if group == pgid:
            members[pid] = fields[2]
    return members


def _anchored_members(
    process: subprocess.Popen[bytes],
    pgid: int,
    *,
    timeout: float = 0.25,
) -> tuple[bool, set[int]]:
    if process.returncode is not None:
        raise RuntimeError("command process group lost its leader anchor")
    members = _observe_group(pgid, timeout=timeout)
    leader = members.get(process.pid)
    if leader is None:
        raise RuntimeError("command process group lost its leader anchor")
    return leader.startswith("Z"), set(members) - {process.pid}


def _signal_anchored(
    process: subprocess.Popen[bytes],
    pgid: int,
    sig: signal.Signals,
) -> None:
    if process.returncode is not None:
        raise RuntimeError("refusing to signal an unanchored process group")
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError) as error:
        leader_exited, descendants = _anchored_members(process, pgid)
        if leader_exited and not descendants:
            return
        raise RuntimeError("command process group is unverifiable") from error


def _wait_for_quiet_group(
    process: subprocess.Popen[bytes],
    pgid: int,
    timeout: float,
) -> bool:
    end = time.monotonic() + timeout
    while True:
        remaining = end - time.monotonic()
        leader_exited, descendants = _anchored_members(
            process,
            pgid,
            timeout=max(0.1, min(0.25, max(remaining, 0.0))),
        )
        if leader_exited and not descendants:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.01)


def _finish_anchored_group(
    process: subprocess.Popen[bytes],
    pgid: int,
    *,
    terminate_leader: bool,
) -> tuple[int, bool]:
    _leader_exited, descendants = _anchored_members(process, pgid)
    if terminate_leader or descendants:
        _signal_anchored(process, pgid, signal.SIGTERM)
    forced = False
    if not _wait_for_quiet_group(process, pgid, 10.0):
        forced = True
        _signal_anchored(process, pgid, signal.SIGKILL)
        if not _wait_for_quiet_group(process, pgid, 1.0):
            raise RuntimeError("command process group survived termination")
    exit_code = process.wait(timeout=1)
    if _observe_group(pgid, timeout=0.25):
        raise RuntimeError("command process group survived leader reap")
    return exit_code, forced


def _bounded_direct_cleanup(
    process: subprocess.Popen[bytes],
    pgid: int,
    *,
    timeout: float = 1.0,
) -> None:
    """Always make a bounded direct-child kill/reap attempt after group errors."""
    if process.returncode is not None:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The caller will fail closed; this bounded fallback must never hang.
        return


def _close_process_streams(process: subprocess.Popen[bytes]) -> None:
    if process.stdout is not None:
        try:
            process.stdout.close()
        except OSError:
            pass
    if process.stderr is not None:
        try:
            process.stderr.close()
        except OSError:
            pass


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
        _bounded_direct_cleanup(process, process.pid)
        _close_process_streams(process)
        raise

    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout_digest = hashlib.sha256()
    stderr_digest = hashlib.sha256()
    stdout_tail = bytearray()
    stderr_tail = bytearray()
    timed_out = False
    finished_group = False
    leader_exit_code: int | None = None
    forced = False
    try:
        while True:
            remaining = deadline_seconds - (time.monotonic() - started)
            if remaining <= 0 and not timed_out:
                timed_out = True
                leader_exit_code, group_forced = _finish_anchored_group(
                    process, process.pid, terminate_leader=True
                )
                forced |= group_forced
                finished_group = True
                remaining = 0

            if selector.get_map():
                for key, _mask in selector.select(min(max(remaining, 0.0), 0.05)):
                    stream = key.fileobj
                    chunk = os.read(stream.fileno(), 65536)
                    if not chunk:
                        selector.unregister(stream)
                    elif key.data == "stdout":
                        stdout_digest.update(chunk)
                        _retain_tail(stdout_tail, chunk, output_limit)
                    else:
                        stderr_digest.update(chunk)
                        _retain_tail(stderr_tail, chunk, output_limit)
            elif not finished_group:
                time.sleep(min(max(remaining, 0.0), 0.05))

            if not finished_group:
                leader_exited, _descendants = _anchored_members(
                    process,
                    process.pid,
                    timeout=max(0.1, min(0.25, max(remaining, 0.0))),
                )
                if leader_exited:
                    leader_exit_code, group_forced = _finish_anchored_group(
                        process, process.pid, terminate_leader=False
                    )
                    forced |= group_forced
                    finished_group = True
            if finished_group and not selector.get_map():
                break
        code = None if timed_out else leader_exit_code
    finally:
        selector.close()
        try:
            if process.returncode is None:
                _bounded_direct_cleanup(process, process.pid)
        finally:
            _close_process_streams(process)
    return ProcessResult(
        kind="verification_timed_out" if timed_out else ("success" if code == 0 else "failed"),
        exit_code=code,
        stdout_tail=bytes(stdout_tail),
        stderr_tail=bytes(stderr_tail),
        stdout_digest=stdout_digest.hexdigest(),
        stderr_digest=stderr_digest.hexdigest(),
        started_at=started_at,
        finished_at=_iso_now(),
        forced_kill=forced,
    )
