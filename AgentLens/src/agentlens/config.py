"""AgentLens configuration loader (spec §S1.3 row 69, §S1.4).

Implements the priority chain:

    AGENTLENS_DISABLE=1  >  AGENTLENS_<KEY> env vars  >
    <workspace_root>/.agentlens/config.yaml  >
    ~/.agentlens/config.yaml (or $AGENTLENS_HOME/config.yaml)  >
    defaults

The only configuration key recognised in v0 is ``mode`` (one of
``disabled``, ``minimal``, ``full``). Unknown keys from YAML files are
preserved verbatim so future versions can introduce additional settings
without a migration; unknown ``AGENTLENS_<KEY>`` env vars (other than
``AGENTLENS_DISABLE``, ``AGENTLENS_HOME``, ``AGENTLENS_MODE``) are ignored.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .store.paths import agentlens_home

VALID_MODES: frozenset[str] = frozenset({"disabled", "minimal", "full"})
DEFAULT_MODE: str = "minimal"

# Truthy literals for AGENTLENS_DISABLE (case-insensitive).
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Env vars we do NOT treat as configuration keys even though they begin with
# the AGENTLENS_ prefix.
_RESERVED_ENV = frozenset({"AGENTLENS_HOME", "AGENTLENS_DISABLE"})


class ConfigError(ValueError):
    """Raised for invalid configuration values (e.g. unknown ``mode``)."""


def _user_config_path() -> Path:
    """Return the path to the user-level config file."""
    return agentlens_home() / "config.yaml"


def _workspace_config_path(workspace_root: Path) -> Path:
    return Path(workspace_root) / ".agentlens" / "config.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.strip():
        return {}
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"config file {path} must contain a YAML mapping at the top level"
        )
    return data


def _env_overrides() -> dict[str, Any]:
    """Extract AGENTLENS_<KEY> env vars as a config-shaped dict.

    Only ``AGENTLENS_MODE`` is recognised in v0; other AGENTLENS_* env vars
    are ignored for forward compatibility (per task_16 decision).
    """
    out: dict[str, Any] = {}
    mode = os.environ.get("AGENTLENS_MODE")
    if mode is not None:
        out["mode"] = mode
    return out


def _disable_active() -> bool:
    raw = os.environ.get("AGENTLENS_DISABLE")
    if raw is None:
        return False
    return raw.strip().lower() in _TRUTHY


def _validate(cfg: dict[str, Any], *, source: str) -> None:
    mode = cfg.get("mode")
    if mode is not None and mode not in VALID_MODES:
        raise ConfigError(
            f"invalid mode {mode!r} from {source}; "
            f"expected one of {sorted(VALID_MODES)}"
        )


def load_config(workspace_root: Path | None = None) -> dict[str, Any]:
    """Resolve the effective AgentLens config per the priority chain.

    Returns a dict that always contains a valid ``mode`` key. Other keys
    from YAML files are merged through unchanged. Raises :class:`ConfigError`
    when any source supplies an invalid ``mode``.
    """
    # 1. Hard kill switch — wins unconditionally.
    if _disable_active():
        return {"mode": "disabled"}

    merged: dict[str, Any] = {"mode": DEFAULT_MODE}

    # 4. User config (lowest non-default precedence).
    user_cfg = _load_yaml(_user_config_path())
    _validate(user_cfg, source=str(_user_config_path()))
    merged.update(user_cfg)

    # 3. Workspace config.
    if workspace_root is not None:
        ws_path = _workspace_config_path(workspace_root)
        ws_cfg = _load_yaml(ws_path)
        _validate(ws_cfg, source=str(ws_path))
        merged.update(ws_cfg)

    # 2. Env vars.
    env_cfg = _env_overrides()
    _validate(env_cfg, source="AGENTLENS_* env")
    merged.update(env_cfg)

    return merged


def write_workspace_mode(workspace_root: Path, mode: str) -> Path:
    """Persist ``mode`` to ``<workspace_root>/.agentlens/config.yaml``.

    Creates the ``.agentlens`` directory if needed. Merges with any existing
    YAML keys (so unrelated future keys survive). Returns the file path.
    """
    if mode not in VALID_MODES:
        raise ConfigError(
            f"invalid mode {mode!r}; expected one of {sorted(VALID_MODES)}"
        )
    path = _workspace_config_path(workspace_root)
    existing = _load_yaml(path)
    existing["mode"] = mode
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(existing, sort_keys=True), encoding="utf-8")
    return path


__all__ = [
    "ConfigError",
    "DEFAULT_MODE",
    "VALID_MODES",
    "load_config",
    "write_workspace_mode",
]
