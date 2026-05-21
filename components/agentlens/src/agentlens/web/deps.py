"""FastAPI dependencies for the web layer."""
from __future__ import annotations

from pathlib import Path

from agentlens.store.paths import agentlens_home


def resolve_home() -> Path:
    """Return ``$AGENTLENS_HOME`` or the default AgentLens home."""
    return agentlens_home()


def store_exists() -> bool:
    """Return true when the durable runs directory exists."""
    return (resolve_home() / "runs").is_dir()


__all__ = ["resolve_home", "store_exists"]
