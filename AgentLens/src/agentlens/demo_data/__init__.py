"""Bundled demo runs used by ``agentlens serve --demo``."""
from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path


def demo_root() -> Path:
    """Return the bundled demo data root resolved on disk."""
    pkg = files("agentlens.demo_data")
    with as_file(pkg) as path:
        return Path(path)


__all__ = ["demo_root"]
