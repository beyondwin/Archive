from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DetachedLaunch:
    run_id: str
    pid: int
    pidfile: str
    stdout_path: str
    stderr_path: str
    argv: list[str]


def _absolutize(value: str, cwd: Path) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else (cwd / path).resolve())


def build_detached_argv(
    *,
    executable: str,
    script: Path,
    original_argv: list[str],
    invocation_cwd: Path,
    run_id: str,
) -> list[str]:
    rebuilt: list[str] = []
    skip_next = False
    index = 0
    while index < len(original_argv):
        token = original_argv[index]
        if skip_next:
            skip_next = False
            index += 1
            continue
        if token == "--detach":
            index += 1
            continue
        if token == "--run-id":
            skip_next = True
            index += 1
            continue
        if token in {"--plan", "--spec"} and index + 1 < len(original_argv):
            rebuilt.extend([token, _absolutize(original_argv[index + 1], invocation_cwd)])
            skip_next = True
            index += 1
            continue
        rebuilt.append(token)
        index += 1
    if rebuilt[:1] != ["run"]:
        rebuilt.insert(0, "run")
    rebuilt.extend(["--run-id", run_id])
    return [executable, str(script.resolve()), *rebuilt]


def launch_detached(*, argv: list[str], cwd: Path, run_id: str, run_dir: Path) -> DetachedLaunch:
    detach_dir = run_dir / ".agentrunway-detached"
    detach_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = detach_dir / "stdout.log"
    stderr_path = detach_dir / "stderr.log"
    with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open("a", encoding="utf-8") as stderr:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
            env=os.environ.copy(),
            start_new_session=True,
        )
    pidfile = detach_dir / "pidfile"
    pidfile.write_text(f"{proc.pid}\n", encoding="utf-8")
    return DetachedLaunch(
        run_id=run_id,
        pid=proc.pid,
        pidfile=str(pidfile),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        argv=list(argv),
    )


def script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "agentrunway.py"


def python_executable() -> str:
    return sys.executable
