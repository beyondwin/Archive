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
        return {"path": str(self.path), "sha256": self.sha256, "mode": self.mode, "size": self.size}

    def revalidate(self) -> None:
        try:
            current = os.open(
                str(self.path), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
            )
        except OSError as error:
            raise ValueError("command executable changed") from error
        try:
            metadata = os.fstat(current)
            digest = _digest_fd(current)
        finally:
            os.close(current)
        observed = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            digest,
        )
        expected = (self.device, self.inode, self.mode, self.size, self.sha256)
        if observed != expected:
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate(argv: Sequence[str], cwd: Path, env: Mapping[str, str], deadline: float, limit: int) -> None:
    if not argv or any(not isinstance(value, str) or not value or "\0" in value for value in argv):
        raise ValueError("argv must contain non-empty strings without NUL")
    if not isinstance(deadline, (int, float)) or isinstance(deadline, bool) or not math.isfinite(deadline) or deadline <= 0:
        raise ValueError("deadline_seconds must be finite and positive")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("output_limit must be a non-negative integer")
    if not cwd.is_dir():
        raise ValueError("command cwd must be an existing directory")
    if any(not isinstance(key, str) or not isinstance(value, str) or "\0" in key or "\0" in value for key, value in env.items()):
        raise ValueError("command environment must contain NUL-free strings")


def _validated_executable(candidate: Path) -> Path:
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError("command executable is unavailable") from error
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("command executable is unavailable")
    return resolved


def _provided_executable(candidate: Path) -> Path:
    """Validate the already-resolved identity path without resolving it again."""
    if not candidate.is_absolute():
        raise ValueError("command executable is unavailable")
    try:
        metadata = candidate.stat()
    except OSError as error:
        raise ValueError("command executable is unavailable") from error
    if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
        raise ValueError("command executable is unavailable")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("command executable is unavailable")
    return candidate


def _executable(argv0: str, cwd: Path, env: Mapping[str, str]) -> Path:
    located = shutil.which(argv0, path=env.get("PATH"))
    if located is None:
        raise ValueError("command executable is unavailable")
    candidate = Path(located)
    return _validated_executable(candidate if candidate.is_absolute() else cwd / candidate)


def _digest_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def open_executable(argv0: str, *, cwd: Path, env: Mapping[str, str]) -> OpenedExecutable:
    """Open and hash the original executable for same-UID mutation checks."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("executable identity validation is unsupported")
    path = _executable(argv0, cwd, env)
    try:
        source = os.open(
            str(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        )
    except OSError as error:
        raise ValueError("command executable is unavailable") from error
    try:
        metadata = os.fstat(source)
        if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
            raise ValueError("command executable is unavailable")
        return OpenedExecutable(
            path=path,
            fd=source,
            sha256=_digest_fd(source),
            mode=metadata.st_mode,
            size=metadata.st_size,
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )
    except BaseException:
        os.close(source)
        raise


def _append_tail(current: bytearray, chunk: bytes, limit: int) -> None:
    if limit == 0:
        current.clear()
        return
    current.extend(chunk)
    if len(current) > limit:
        del current[: len(current) - limit]


def _observe_group(pgid: int, *, timeout: float) -> dict[int, str]:
    """Return shell-free PID/status observations for one process group."""
    try:
        observed = subprocess.run(
            ("/bin/ps", "-axo", "pid=,pgid=,stat="),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("command process group is unverifiable") from error
    if observed.returncode != 0:
        raise RuntimeError("command process group is unverifiable")
    try:
        lines = observed.stdout.decode("ascii").splitlines()
    except (AttributeError, UnicodeDecodeError) as error:
        raise RuntimeError("command process group is unverifiable") from error
    members: dict[int, str] = {}
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 3:
            raise RuntimeError("command process group is unverifiable")
        try:
            pid, member_pgid = int(fields[0]), int(fields[1])
        except ValueError as error:
            raise RuntimeError("command process group is unverifiable") from error
        if pid <= 0 or member_pgid <= 0 or not fields[2]:
            raise RuntimeError("command process group is unverifiable")
        if member_pgid == pgid:
            members[pid] = fields[2]
    return members


def process_group_is_quiescent(
    pgid: int,
    recorded_pids: Sequence[int],
) -> bool:
    if type(pgid) is not int or pgid <= 0:
        raise ValueError("provider process group evidence is invalid")
    if (
        not isinstance(recorded_pids, Sequence)
        or isinstance(recorded_pids, (str, bytes))
        or any(type(pid) is not int or pid <= 0 for pid in recorded_pids)
    ):
        raise ValueError("recorded process evidence is invalid")
    if _observe_group(pgid, timeout=0.25):
        return False
    for pid in set(recorded_pids):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            return False
        return False
    return True


def _anchored_group(
    process: subprocess.Popen[bytes],
    pgid: int,
    *,
    observation_timeout: float = 0.25,
) -> tuple[bool, set[int]]:
    """Observe members while the unreaped leader prevents PGID/PID reuse."""
    if process.returncode is not None:
        raise RuntimeError("command process group lost its leader anchor")
    members = _observe_group(pgid, timeout=observation_timeout)
    leader_status = members.get(process.pid)
    if leader_status is None:
        raise RuntimeError("command process group lost its leader anchor")
    return leader_status.startswith("Z"), set(members) - {process.pid}


def _signal_anchored_group(
    process: subprocess.Popen[bytes],
    pgid: int,
    sig: signal.Signals,
) -> None:
    """Signal only while the original unreaped leader anchors this PGID."""
    if process.returncode is not None:
        raise RuntimeError("refusing to signal an unanchored process group")
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError) as error:
        leader_exited, descendants = _anchored_group(process, pgid)
        if leader_exited and not descendants:
            return
        raise RuntimeError("command process group is unverifiable") from error


def _wait_for_quiet_group(
    process: subprocess.Popen[bytes],
    pgid: int,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        leader_exited, descendants = _anchored_group(
            process,
            pgid,
            observation_timeout=max(0.1, min(0.25, max(remaining, 0))),
        )
        if leader_exited and not descendants:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def _finish_group(
    process: subprocess.Popen[bytes],
    pgid: int,
    *,
    terminate_leader: bool,
) -> tuple[int, bool]:
    """Terminate remaining members, then reap the anchored leader exactly once."""
    leader_exited, descendants = _anchored_group(process, pgid)
    if terminate_leader or descendants:
        _signal_anchored_group(process, pgid, signal.SIGTERM)
    forced = False
    if not _wait_for_quiet_group(process, pgid, 10):
        forced = True
        _signal_anchored_group(process, pgid, signal.SIGKILL)
        if not _wait_for_quiet_group(process, pgid, 1):
            raise RuntimeError("command process group survived termination")
    exit_code = process.wait(timeout=1)
    if _observe_group(pgid, timeout=0.25):
        # The leader has been reaped, so the numeric PGID is no longer safe to
        # signal. Fail closed if observation does not confirm disappearance.
        raise RuntimeError("command process group survived leader reap")
    return exit_code, forced


def _bounded_direct_cleanup(
    process: subprocess.Popen[bytes],
    pgid: int,
    *,
    timeout: float = 1,
) -> None:
    """Best-effort group cleanup plus bounded direct-child kill and reap."""
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
    """Run literal argv in one session, monitoring its group beyond pipe EOF."""
    _validate(argv, cwd, env, deadline_seconds, output_limit)
    if executable_path is not None and opened_executable is not None:
        raise ValueError("exactly one executable source may be supplied")
    if opened_executable is not None:
        if opened_executable.fd < 0:
            raise ValueError("opened executable is closed")
        opened_executable.revalidate()
        executable = opened_executable.path
    else:
        executable = _executable(argv[0], cwd, env) if executable_path is None else _provided_executable(executable_path)
    started_at = _now()
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv), executable=str(executable), cwd=str(cwd), env=dict(env),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, start_new_session=True,
    )
    pgid = process.pid
    try:
        if opened_executable is not None:
            # Popen returned only after the child exec handshake completed.
            opened_executable.revalidate()
        if os.getpgid(process.pid) != pgid:
            raise RuntimeError("command did not create an isolated process group")
    except ProcessLookupError:
        # It cannot leave a descendant group when it exited before this check.
        pass
    except BaseException:
        _bounded_direct_cleanup(process, pgid)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        raise
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout_hash, stderr_hash = hashlib.sha256(), hashlib.sha256()
    stdout_tail, stderr_tail = bytearray(), bytearray()
    timed_out = False
    forced_kill = False
    leader_exit_handled = False
    leader_exit_code: int | None = None
    try:
        while True:
            remaining = deadline_seconds - (time.monotonic() - started)
            if remaining <= 0 and not timed_out:
                timed_out = True
                leader_exit_code, forced = _finish_group(
                    process, pgid, terminate_leader=True
                )
                forced_kill = forced or forced_kill
                leader_exit_handled = True
                remaining = 0
            if selector.get_map():
                for key, _events in selector.select(min(max(remaining, 0), 0.05)):
                    stream = key.fileobj
                    chunk = os.read(stream.fileno(), 65536)
                    if not chunk:
                        selector.unregister(stream)
                    elif key.data == "stdout":
                        stdout_hash.update(chunk)
                        _append_tail(stdout_tail, chunk, output_limit)
                    else:
                        stderr_hash.update(chunk)
                        _append_tail(stderr_tail, chunk, output_limit)
            elif not leader_exit_handled:
                time.sleep(min(max(remaining, 0), 0.05))

            if not leader_exit_handled:
                # A completed leader is not completion of its session group.
                leader_exited, _descendants = _anchored_group(
                    process,
                    pgid,
                    observation_timeout=max(0.1, min(0.25, max(remaining, 0))),
                )
                if leader_exited:
                    leader_exit_code, forced = _finish_group(
                        process, pgid, terminate_leader=False
                    )
                    forced_kill = forced or forced_kill
                    leader_exit_handled = True
            if leader_exit_handled and not selector.get_map():
                break

        if timed_out:
            exit_code, kind = None, "verification_timed_out"
        else:
            assert leader_exit_code is not None
            exit_code = leader_exit_code
            kind = "success" if exit_code == 0 else "failed"
    finally:
        selector.close()
        try:
            if process.returncode is None:
                _bounded_direct_cleanup(process, pgid)
        finally:
            process.stdout.close()
            process.stderr.close()
    return ProcessResult(
        kind=kind, exit_code=exit_code, stdout_tail=bytes(stdout_tail),
        stderr_tail=bytes(stderr_tail), stdout_digest=stdout_hash.hexdigest(),
        stderr_digest=stderr_hash.hexdigest(), started_at=started_at,
        finished_at=_now(), forced_kill=forced_kill,
    )
