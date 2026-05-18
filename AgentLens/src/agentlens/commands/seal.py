"""``agentlens seal`` — seal the active run's manifest (pre_eval or final)."""
from __future__ import annotations

from pathlib import Path

import typer

from agentlens.store.manifest import seal_final, seal_pre_eval

from ._run_resolve import latest_run_dir


def seal(
    final: bool = typer.Option(
        False, "--final", help="seal at phase 'final' (default: 'pre_eval')"
    ),
) -> None:
    """Compute the manifest and seal the active run."""
    run_dir = latest_run_dir(Path.cwd())
    if final:
        seal_final(run_dir)
    else:
        seal_pre_eval(run_dir)


__all__ = ["seal"]
