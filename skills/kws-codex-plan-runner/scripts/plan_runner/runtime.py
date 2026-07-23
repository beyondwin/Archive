from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig


UV_FIND_ARGV = (
    "uv",
    "python",
    "find",
    "--managed-python",
    "--no-python-downloads",
    "--no-project",
    "--no-config",
    "--resolve-links",
    "3.13",
)


class RuntimeUnavailable(RuntimeError):
    """Raised when the required managed interpreter cannot be used."""


@dataclass(frozen=True)
class RuntimeIdentity:
    uv_version: str
    implementation: str
    python_version: str
    executable: str
    architecture: str
    gil_disabled: bool


def _run_uv(argv: list[str]) -> str:
    try:
        completed = subprocess.run(
            argv,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeUnavailable("runtime_missing") from error
    return completed.stdout.strip()


def probe_runtime() -> RuntimeIdentity:
    uv_version = _run_uv(["uv", "--version"])
    discovered_executable = _run_uv(list(UV_FIND_ARGV))
    if not discovered_executable:
        raise RuntimeUnavailable("runtime_missing")

    managed_executable = Path(discovered_executable.splitlines()[0]).resolve()
    running_executable = Path(sys.executable).resolve()
    if managed_executable != running_executable:
        raise RuntimeUnavailable("runtime_incompatible")

    version = sys.version_info
    gil_disabled = sysconfig.get_config_var("Py_GIL_DISABLED") in (1, "1", True)
    return RuntimeIdentity(
        uv_version=uv_version,
        implementation=sys.implementation.name,
        python_version=f"{version.major}.{version.minor}.{version.micro}",
        executable=str(running_executable),
        architecture=platform.machine(),
        gil_disabled=gil_disabled,
    )


def require_compatible_runtime(identity: RuntimeIdentity | None = None) -> RuntimeIdentity:
    runtime = probe_runtime() if identity is None else identity
    try:
        major, minor, _patch = (int(part) for part in runtime.python_version.split(".", 2))
    except ValueError as error:
        raise RuntimeUnavailable("runtime_incompatible") from error
    if (
        runtime.implementation != "cpython"
        or (major, minor) != (3, 13)
        or runtime.gil_disabled
    ):
        raise RuntimeUnavailable("runtime_incompatible")
    return runtime
