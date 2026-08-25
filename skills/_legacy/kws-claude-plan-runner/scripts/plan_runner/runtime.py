from __future__ import annotations

import platform
import subprocess
import sys
import sysconfig
from dataclasses import asdict, dataclass
from pathlib import Path

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
    pass


@dataclass(frozen=True)
class RuntimeIdentity:
    uv_version: str
    implementation: str
    python_version: str
    executable: str
    architecture: str
    gil_disabled: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _invoke_uv(argv: list[str] | tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            list(argv), check=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeUnavailable("runtime_missing") from error
    return result.stdout.strip()


def probe_runtime() -> RuntimeIdentity:
    uv_version = _invoke_uv(["uv", "--version"])
    discovered = _invoke_uv(UV_FIND_ARGV)
    if not uv_version or not discovered:
        raise RuntimeUnavailable("runtime_missing")
    managed = Path(discovered.splitlines()[0]).resolve()
    running = Path(sys.executable).resolve()
    if managed != running:
        raise RuntimeUnavailable("runtime_incompatible")
    version = sys.version_info
    return RuntimeIdentity(
        uv_version=uv_version,
        implementation=sys.implementation.name,
        python_version=f"{version.major}.{version.minor}.{version.micro}",
        executable=str(running),
        architecture=platform.machine(),
        gil_disabled=bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
    )


def require_compatible_runtime(identity: RuntimeIdentity | None = None) -> RuntimeIdentity:
    found = identity if identity is not None else probe_runtime()
    try:
        version = tuple(int(piece) for piece in found.python_version.split("."))
    except (TypeError, ValueError):
        version = ()
    if (
        found.implementation != "cpython"
        or len(version) != 3
        or version[:2] != (3, 13)
        or found.gil_disabled
    ):
        raise RuntimeUnavailable("runtime_incompatible")
    return found
