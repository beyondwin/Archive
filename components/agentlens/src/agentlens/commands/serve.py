"""``agentlens serve`` - boot the dashboard."""
from __future__ import annotations

import os
import shutil
import socket
import tempfile
from pathlib import Path

from click.core import ParameterSource
import typer
import uvicorn

from agentlens.demo_data import demo_root
from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def _materialise_demo_home() -> tuple[Path, Path]:
    """Copy bundled demo data into a fresh temp dir; return (home, marker)."""
    home = Path(tempfile.mkdtemp(prefix="agentlens-demo-"))
    src_runs = demo_root() / "runs"
    if src_runs.exists():
        shutil.copytree(src_runs, home / "runs")
    marker = home / ".demo"
    marker.write_text("agentlens demo home\n", encoding="utf-8")
    return home, marker


def _select_port(port: int, *, auto: bool, max_offset: int = 3) -> int:
    """Return an available port, optionally trying ``port + 1..max_offset``."""

    def _is_free(candidate: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                return False
            return True

    if _is_free(port):
        return port
    if not auto:
        raise OSError(
            f"port {port} is already in use; pass --auto-port to try "
            f"{port + 1}..{port + max_offset}"
        )
    for offset in range(1, max_offset + 1):
        candidate = port + offset
        if _is_free(candidate):
            return candidate
    raise OSError(f"no free port in range {port}..{port + max_offset}")


def _settings_overrides_from_cli(
    ctx: typer.Context, values: dict[str, object]
) -> dict[str, object]:
    """Return only values explicitly supplied on the command line."""
    overrides: dict[str, object] = {}
    for key, value in values.items():
        if ctx.get_parameter_source(key) is ParameterSource.COMMANDLINE:
            overrides[key] = value
    return overrides


def serve(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(5757, "--port", help="TCP port."),
    demo: bool = typer.Option(False, "--demo", help="Use bundled demo data."),
    debug: bool = typer.Option(False, "--debug", help="Expose error details."),
    auto_port: bool = typer.Option(
        False, "--auto-port", help="Try port+1..+3 when busy."
    ),
    dev_proxy: str | None = typer.Option(
        None, "--dev-proxy", help="Proxy SPA requests to a loopback Vite server."
    ),
    allow_origin: list[str] = typer.Option(
        [], "--allow-origin", help="Allowed CORS origin; may be repeated."
    ),
) -> None:
    """Spawn the AgentLens web viewer."""
    settings = ServeSettings(
        **_settings_overrides_from_cli(
            ctx,
            {
                "host": host,
                "port": port,
                "demo": demo,
                "debug": debug,
                "auto_port": auto_port,
                "dev_proxy": dev_proxy,
                "allow_origin": tuple(allow_origin),
            },
        )
    )

    if settings.demo:
        demo_home, _ = _materialise_demo_home()
        os.environ["AGENTLENS_HOME"] = str(demo_home)
        typer.secho(
            f"agentlens: demo mode - using temp home at {demo_home}",
            fg=typer.colors.YELLOW,
            err=True,
        )

    if not settings.is_loopback_only():
        typer.secho(
            "agentlens: bound to a non-loopback host - no authentication is enabled. "
            "Expose only on networks you trust.",
            fg=typer.colors.RED,
            err=True,
        )

    app = create_app(settings)
    chosen = _select_port(settings.port, auto=settings.auto_port)
    if chosen != settings.port:
        typer.secho(f"agentlens: port {settings.port} busy - using {chosen}", err=True)
    uvicorn.run(app, host=settings.host, port=chosen, log_level="info")


__all__ = ["_materialise_demo_home", "_select_port", "serve"]
