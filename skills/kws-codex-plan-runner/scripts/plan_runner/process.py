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


def _append_tail(current: bytearray, chunk: bytes, limit: int) -> None:
    if limit == 0:
        current.clear()
        return
    current.extend(chunk)
    if len(current) > limit:
        del current[: len(current) - limit]


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        # EPERM after a leader exits is not proof that a recycled PGID is ours;
        # fail closed rather than signal an unrelated session group.
        return False
    return True


def _kill_group(pgid: int) -> bool:
    """End the just-created session group even after its leader has exited."""
    if not _group_exists(pgid):
        return False
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    deadline = time.monotonic() + 10
    while _group_exists(pgid) and time.monotonic() < deadline:
        time.sleep(0.01)
    forced = _group_exists(pgid)
    if forced:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return True
    until = time.monotonic() + 1
    while _group_exists(pgid):
        if time.monotonic() >= until:
            raise RuntimeError("command process group survived termination")
        time.sleep(0.01)
    return forced


def run_exact(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    deadline_seconds: float,
    output_limit: int = 1_048_576,
    executable_path: Path | None = None,
) -> ProcessResult:
    """Run literal argv in one session, monitoring its group beyond pipe EOF."""
    _validate(argv, cwd, env, deadline_seconds, output_limit)
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
        if os.getpgid(process.pid) != pgid:
            raise RuntimeError("command did not create an isolated process group")
    except ProcessLookupError:
        # It cannot leave a descendant group when it exited before this check.
        pass
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout_hash, stderr_hash = hashlib.sha256(), hashlib.sha256()
    stdout_tail, stderr_tail = bytearray(), bytearray()
    timed_out = False
    forced_kill = False
    leader_exit_handled = False
    try:
        while True:
            remaining = deadline_seconds - (time.monotonic() - started)
            if remaining <= 0 and not timed_out:
                timed_out = True
                forced_kill = _kill_group(pgid) or forced_kill
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
            elif not timed_out and process.poll() is None:
                time.sleep(min(max(remaining, 0), 0.05))

            if process.poll() is not None and not leader_exit_handled:
                # A completed leader is not completion of its session group.
                forced_kill = _kill_group(pgid) or forced_kill
                leader_exit_handled = True
            if process.poll() is not None and not selector.get_map():
                break

        if timed_out:
            exit_code, kind = None, "verification_timed_out"
        else:
            exit_code = process.wait(timeout=0)
            kind = "success" if exit_code == 0 else "failed"
    finally:
        selector.close()
        if _group_exists(pgid):
            forced_kill = _kill_group(pgid) or forced_kill
        if process.poll() is None:
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()
    return ProcessResult(
        kind=kind, exit_code=exit_code, stdout_tail=bytes(stdout_tail),
        stderr_tail=bytes(stderr_tail), stdout_digest=stdout_hash.hexdigest(),
        stderr_digest=stderr_hash.hexdigest(), started_at=started_at,
        finished_at=_now(), forced_kill=forced_kill,
    )
