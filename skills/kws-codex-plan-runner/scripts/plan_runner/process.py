from __future__ import annotations

import hashlib
import math
import os
import selectors
import shutil
import signal
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


def _executable(argv0: str, cwd: Path, env: Mapping[str, str]) -> Path:
    located = shutil.which(argv0, path=env.get("PATH"))
    if located is None:
        raise ValueError("command executable is unavailable")
    candidate = Path(located)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError("command executable is unavailable") from error
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("command executable is unavailable")
    return resolved


def _append_tail(current: bytearray, chunk: bytes, limit: int) -> None:
    if limit == 0:
        current.clear()
        return
    current.extend(chunk)
    if len(current) > limit:
        del current[: len(current) - limit]


def _kill_group(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return False
    forced = False
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        forced = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)
    # `Popen.wait` reaps the group leader. A group lookup additionally proves
    # that descendants did not survive a deadline as background processes.
    until = time.monotonic() + 1
    while True:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return forced
        if time.monotonic() >= until:
            raise RuntimeError("command process group survived termination")
        time.sleep(0.01)


def run_exact(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    deadline_seconds: float,
    output_limit: int = 1_048_576,
) -> ProcessResult:
    """Run literal argv in its own process group with independent bounded logs."""
    _validate(argv, cwd, env, deadline_seconds, output_limit)
    executable = _executable(argv[0], cwd, env)
    started_at = _now()
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        executable=str(executable),
        cwd=str(cwd),
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout_hash = hashlib.sha256()
    stderr_hash = hashlib.sha256()
    stdout_tail = bytearray()
    stderr_tail = bytearray()
    timed_out = False
    forced_kill = False
    try:
        while selector.get_map():
            remaining = deadline_seconds - (time.monotonic() - started)
            if remaining <= 0:
                timed_out = True
                forced_kill = _kill_group(process)
                remaining = 0
            for key, _events in selector.select(min(remaining, 0.05)):
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    selector.unregister(stream)
                    continue
                if key.data == "stdout":
                    stdout_hash.update(chunk)
                    _append_tail(stdout_tail, chunk, output_limit)
                else:
                    stderr_hash.update(chunk)
                    _append_tail(stderr_tail, chunk, output_limit)
            if timed_out and process.poll() is not None:
                continue
            if process.poll() is not None and not selector.get_map():
                break
        if not timed_out:
            exit_code = process.wait()
            kind = "success" if exit_code == 0 else "failed"
        else:
            exit_code = None
            kind = "verification_timed_out"
    finally:
        selector.close()
        if process.poll() is None:
            forced_kill = _kill_group(process) or forced_kill
        process.stdout.close()
        process.stderr.close()
    return ProcessResult(
        kind=kind,
        exit_code=exit_code,
        stdout_tail=bytes(stdout_tail),
        stderr_tail=bytes(stderr_tail),
        stdout_digest=stdout_hash.hexdigest(),
        stderr_digest=stderr_hash.hexdigest(),
        started_at=started_at,
        finished_at=_now(),
        forced_kill=forced_kill,
    )
