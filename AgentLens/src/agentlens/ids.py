"""Identifier generation (spec §S1.6.3, §S1.7.1).

* ``make_run_id``  – per-run identifier; schema pattern
  ``^run_\\d{8}_\\d{6}_[a-z0-9]{6}$``.
* ``make_event_id`` – per-event identifier; pattern ``^evt_[a-z0-9]{12}$``.
* ``compute_workspace_id`` – stable workspace identifier derived from git
  remote + worktree identity (preferred) or hashed absolute path (fallback).
  The identifier is persisted to ``<workspace>/.agentlens/config.yaml`` on
  first use so it survives workspace moves.
"""
from __future__ import annotations

import secrets
import socket
import subprocess
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal

try:  # PyYAML is a declared dependency, but degrade gracefully if absent.
    import yaml  # type: ignore[import-untyped]

    _HAVE_YAML = True
except ModuleNotFoundError:  # pragma: no cover - exercised when yaml missing
    yaml = None
    _HAVE_YAML = False

from .constants import RUN_TS_FORMAT

WorkspaceBasis = Literal["git", "path"]


# ---------------------------------------------------------------------------
# Run / event ids
# ---------------------------------------------------------------------------

def make_run_id(now: datetime | None = None) -> str:
    """Return a run id matching ``^run_\\d{8}_\\d{6}_[a-z0-9]{6}$``.

    ``now`` defaults to UTC now. The 6-char suffix is hex (``[a-f0-9]``), which
    is a subset of ``[a-z0-9]`` and satisfies the schema regex.
    """
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    suffix = secrets.token_hex(3)  # 6 hex chars
    return f"run_{when.strftime(RUN_TS_FORMAT)}_{suffix}"


# Acceptance-criteria alias.
run_id = make_run_id


def make_event_id() -> str:
    """Return an event id matching ``^evt_[a-z0-9]{12}$``."""
    return "evt_" + secrets.token_hex(6)  # 12 hex chars


# ---------------------------------------------------------------------------
# Workspace id (spec §S1.7.1, §6.1)
# ---------------------------------------------------------------------------

def _read_workspace_config(root: Path) -> dict:
    cfg = root / ".agentlens" / "config.yaml"
    if not cfg.exists():
        return {}
    text = cfg.read_text(encoding="utf-8")
    if _HAVE_YAML:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            data = {}
        if isinstance(data, dict):
            return data
        return {}
    # Minimal ``key: value`` parser used only when PyYAML is unavailable.
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            data[k.strip()] = v.strip()
    return data


def _persist_workspace_config(root: Path, workspace_id: str, *, id_basis: str) -> None:
    cfg_dir = root / ".agentlens"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / "config.yaml"
    existing = _read_workspace_config(root)
    existing["workspace_id"] = workspace_id
    existing["id_basis"] = id_basis
    if _HAVE_YAML:
        cfg.write_text(yaml.safe_dump(existing, sort_keys=True), encoding="utf-8")
    else:  # pragma: no cover
        lines = [f"{k}: {v}" for k, v in sorted(existing.items())]
        cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git(root: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def _find_git_toplevel(root: Path) -> Path | None:
    out = _git(root, "rev-parse", "--show-toplevel")
    if not out:
        return None
    return Path(out)


def _git_remote_url(toplevel: Path) -> str | None:
    # Prefer "origin"; fall back to the first listed remote.
    origin = _git(toplevel, "config", "--get", "remote.origin.url")
    if origin:
        return origin
    remotes = _git(toplevel, "remote")
    if not remotes:
        return None
    first = remotes.splitlines()[0].strip()
    if not first:
        return None
    return _git(toplevel, "config", "--get", f"remote.{first}.url")


def _git_branch(toplevel: Path) -> str | None:
    out = _git(toplevel, "rev-parse", "--abbrev-ref", "HEAD")
    if out and out != "HEAD":
        return out
    return None


def normalize_git_remote(remote: str) -> str:
    """Normalise a git remote URL to ``host/org/repo`` form.

    Examples
    --------
    * ``https://host/org/repo.git``     -> ``host/org/repo``
    * ``ssh://git@host/org/repo.git``  -> ``host/org/repo``
    * ``git@host:org/repo.git``         -> ``host/org/repo``

    Host is lowercased; path is preserved verbatim (case-sensitive providers
    such as GitHub treat ``Org`` and ``org`` as distinct).
    """
    r = remote.strip()
    # SSH shorthand: ``git@host:org/repo.git``
    if "://" not in r and r.startswith(("git@", "hg@")) and ":" in r:
        user_host, _, path = r.partition(":")
        _, _, host = user_host.partition("@")
        host = host.lower()
        path = path.lstrip("/")
        if path.endswith(".git"):
            path = path[: -len(".git")]
        return f"{host}/{path}"
    # Scheme URL
    if "://" in r:
        scheme, _, rest = r.partition("://")
        # Strip optional ``user@``
        if "@" in rest.split("/", 1)[0]:
            _, _, rest = rest.partition("@")
        host, _, path = rest.partition("/")
        host = host.lower()
        if path.endswith(".git"):
            path = path[: -len(".git")]
        return f"{host}/{path}"
    # Bare path-like input – return as-is (lowercased to be safe).
    return r.lower()


def compute_workspace_id(root: Path) -> tuple[str, WorkspaceBasis, dict]:
    """Return ``(workspace_id, id_basis, metadata)``.

    Algorithm (spec §6.1):

    1. If ``<root>/.agentlens/config.yaml`` already contains ``workspace_id``,
       return it (preserves identity across workspace moves).
    2. Else, if ``root`` is inside a git checkout with a remote: derive id
       from the normalised remote, the repo-relative path, and the resolved
       toplevel (so main checkouts and ``git worktree add`` siblings get
       distinct ids).
    3. Else, derive id from the absolute path + machine hostname.
    4. Persist the computed id back to the workspace config on first use.

    The returned id always matches ``^ws_[a-f0-9]{16}$``.
    """
    root = Path(root)
    persisted_cfg = _read_workspace_config(root)
    persisted_id = persisted_cfg.get("workspace_id")
    if persisted_id:
        basis_raw = persisted_cfg.get("id_basis", "path")
        basis: WorkspaceBasis = "git" if basis_raw == "git" else "path"
        return persisted_id, basis, {}

    git_top = _find_git_toplevel(root)
    if git_top is not None:
        remote = _git_remote_url(git_top)
        if remote:
            norm = normalize_git_remote(remote)
            try:
                rel = root.resolve().relative_to(git_top.resolve()).as_posix()
            except ValueError:
                rel = "."
            if rel == "":
                rel = "."
            worktree_identity = sha256(
                str(git_top.resolve()).encode("utf-8")
            ).hexdigest()[:16]
            basis_input = f"git:{norm}:{rel}:{worktree_identity}"
            wid = "ws_" + sha256(basis_input.encode("utf-8")).hexdigest()[:16]
            _persist_workspace_config(root, wid, id_basis="git")
            metadata: dict = {
                "git_remote_hash": "sha256:"
                + sha256(norm.encode("utf-8")).hexdigest(),
            }
            branch = _git_branch(git_top)
            if branch:
                metadata["git_branch"] = branch
            return wid, "git", metadata

    host_id = sha256(socket.gethostname().encode("utf-8")).hexdigest()[:16]
    canon = sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    basis_input = f"path:{host_id}:{canon}"
    wid = "ws_" + sha256(basis_input.encode("utf-8")).hexdigest()[:16]
    _persist_workspace_config(root, wid, id_basis="path")
    return wid, "path", {}


__all__ = [
    "compute_workspace_id",
    "make_event_id",
    "make_run_id",
    "normalize_git_remote",
    "run_id",
]
