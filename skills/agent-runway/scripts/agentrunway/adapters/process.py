from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ..models import ProcessSnapshot


@dataclass(frozen=True)
class ProcessLaunchSpec:
    worker_id: str
    command: list[str]
    cwd: Path
    stdout_path: Path
    stderr_path: Path
    timeout_seconds: int
    env: dict[str, str]


@dataclass(frozen=True)
class ProcessHandle:
    worker_id: str
    pid: int
    command: list[str]
    cwd: str
    stdout_path: str
    stderr_path: str
    timeout_seconds: int
    started_at: float


class ProcessSupervisor:
    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen[str]] = {}

    def start(self, spec: ProcessLaunchSpec) -> ProcessHandle:
        spec.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        spec.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = spec.stdout_path.open("w", encoding="utf-8")
        stderr = spec.stderr_path.open("w", encoding="utf-8")
        env = os.environ.copy()
        env.update(spec.env)
        proc = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            stdout=stdout,
            stderr=stderr,
            text=True,
            env=env,
            start_new_session=True,
        )
        stdout.close()
        stderr.close()
        self._processes[proc.pid] = proc
        return ProcessHandle(
            worker_id=spec.worker_id,
            pid=proc.pid,
            command=list(spec.command),
            cwd=str(spec.cwd),
            stdout_path=str(spec.stdout_path),
            stderr_path=str(spec.stderr_path),
            timeout_seconds=spec.timeout_seconds,
            started_at=time.time(),
        )

    def poll(self, handle: ProcessHandle) -> ProcessSnapshot:
        proc = self._processes.get(handle.pid)
        if proc is None:
            return self._missing(handle)
        returncode = proc.poll()
        state = "running" if returncode is None else "exited"
        return ProcessSnapshot(
            state=state,
            pid=handle.pid,
            returncode=returncode,
            started_at=handle.started_at,
            ended_at=None if returncode is None else time.time(),
            stdout_path=handle.stdout_path,
            stderr_path=handle.stderr_path,
        )

    def wait(self, handle: ProcessHandle) -> ProcessSnapshot:
        proc = self._processes.get(handle.pid)
        if proc is None:
            return self._missing(handle)
        try:
            returncode = proc.wait(timeout=max(handle.timeout_seconds, 0))
        except subprocess.TimeoutExpired:
            self.cancel(handle)
            return ProcessSnapshot(
                state="timed_out",
                pid=handle.pid,
                returncode=None,
                started_at=handle.started_at,
                ended_at=time.time(),
                stdout_path=handle.stdout_path,
                stderr_path=handle.stderr_path,
                reason="timeout",
            )
        finally:
            self._processes.pop(handle.pid, None)
        return ProcessSnapshot(
            state="exited",
            pid=handle.pid,
            returncode=returncode,
            started_at=handle.started_at,
            ended_at=time.time(),
            stdout_path=handle.stdout_path,
            stderr_path=handle.stderr_path,
        )

    def cancel(self, handle: ProcessHandle) -> None:
        try:
            os.killpg(handle.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def _missing(self, handle: ProcessHandle) -> ProcessSnapshot:
        return ProcessSnapshot(
            state="missing",
            pid=handle.pid,
            started_at=handle.started_at,
            stdout_path=handle.stdout_path,
            stderr_path=handle.stderr_path,
            reason="process_not_tracked",
        )
