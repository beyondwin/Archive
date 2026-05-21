"""``agentlens doctor`` — inspect integrations and paths (spec §S1.6.18, §S1.8.4).

The command reports two scoped views:

* ``integrations`` — for each known agent runtime, the v0 integration level
  (``none`` or ``shim``; spec leaves ``watcher-only|full|native-experimental``
  reserved) and the shim-lockfile integrity (``ok`` / ``drift_warning``).
* ``paths`` — resolved ``AGENTLENS_HOME``, workspace id (with id basis), and
  the shim directory.

The default scope is ``all`` (both sections). Output is either human-readable
text or deterministic JSON (``--format json``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from ..adapters import wrapper_detect
from ..adapters.shims import (
    _parse_lockfile,
    read_cmux_install_metadata,
    verify_cmux_chain,
    verify_shim_integrity,
)
from ..ids import compute_workspace_id
from ..store.paths import agentlens_home

# v0 agents tracked by `doctor integrations`. Spec §S1.6.18 enumerates the
# integration-level allow-list; for v0 only `none` and `shim` are realised.
_KNOWN_AGENTS: tuple[str, ...] = ("claude", "codex")


def _shim_dir() -> Path:
    return Path.home() / ".agentlens" / "shims"


def _integrations_block() -> dict:
    out: dict = {}
    for name in _KNOWN_AGENTS:
        integrity = verify_shim_integrity(name)
        if integrity == "missing":
            out[name] = {"integration_level": "none"}
        elif integrity == "wrapper_chain_warning":
            # Re-scan to surface the category + remediation alongside the
            # integrity verdict (spec §3.5).
            lockfile = _shim_dir() / f"{name}.real"
            target = Path(_parse_lockfile(lockfile)["path"])
            detection = wrapper_detect.scan_real_candidate(target)
            out[name] = {
                "integration_level": "shim",
                "shim_integrity": "wrapper_chain_warning",
                "wrapper_detected": detection.category,
                "remediation": detection.remediation,
            }
        else:
            out[name] = {
                "integration_level": "shim",
                "shim_integrity": integrity,
            }
    return out


def _paths_block() -> dict:
    home = agentlens_home()
    workspace_id, basis, _metadata = compute_workspace_id(Path.cwd())
    shim_dir = _shim_dir()
    return {
        "AGENTLENS_HOME": {
            "path": str(home),
            "exists": home.exists(),
        },
        "workspace_id": {
            "id": workspace_id,
            "id_basis": basis,
        },
        "shim_dir": {
            "path": str(shim_dir),
            "exists": shim_dir.exists(),
        },
    }


def _format_text_integrations(integrations: dict) -> str:
    lines = ["Integrations:"]
    for name in sorted(integrations):
        info = integrations[name]
        level = info.get("integration_level", "none")
        if "shim_integrity" in info:
            lines.append(
                f"  {name}: integration_level={level} "
                f"shim_integrity={info['shim_integrity']}"
            )
            if info["shim_integrity"] == "wrapper_chain_warning":
                lines.append(
                    f"    wrapper_detected={info.get('wrapper_detected')} "
                    f"— fix: {info.get('remediation', '')}"
                )
        else:
            lines.append(f"  {name}: integration_level={level}")
    return "\n".join(lines)


def _cmux_block() -> dict | None:
    """Return the cmux-chain status block, or ``None`` if not installed.

    The block is omitted from the doctor output when no cmux install
    metadata exists (the common case). When metadata is present, the
    block reports drift, missing-backup, sha mismatch, version drift,
    and permission errors — see ``verify_cmux_chain`` for shape.
    """
    if read_cmux_install_metadata() is None:
        return None
    return verify_cmux_chain()


def _format_text_cmux(cmux: dict) -> str:
    status = cmux.get("status", "unknown")
    lines = [f"Cmux chain: status={status}"]
    if "message" in cmux:
        lines.append(f"  {cmux['message']}")
    return "\n".join(lines)


def _format_text_paths(paths: dict) -> str:
    home = paths["AGENTLENS_HOME"]
    ws = paths["workspace_id"]
    shim = paths["shim_dir"]
    return "\n".join(
        [
            "Paths:",
            f"  AGENTLENS_HOME: {home['path']} "
            f"({'exists' if home['exists'] else 'missing'})",
            f"  workspace_id: {ws['id']} ({ws['id_basis']} basis)",
            f"  shim_dir: {shim['path']} "
            f"({'exists' if shim['exists'] else 'missing'})",
        ]
    )


def collect_doctor_report(scope: str = "all") -> dict[str, object]:
    """Return the structured doctor report used by CLI and web routes."""
    if scope not in {"integrations", "paths", "all"}:
        raise ValueError(
            f"invalid scope {scope!r}; expected integrations | paths | all"
        )
    report: dict[str, object] = {}
    if scope in {"integrations", "all"}:
        report["integrations"] = _integrations_block()
    if scope in {"paths", "all"}:
        report["paths"] = _paths_block()
    report.setdefault("warnings", [])
    return report


def doctor(
    scope: str = typer.Argument(
        "all", help="What to inspect: integrations | paths | all."
    ),
    fmt: str = typer.Option(
        "text", "--format", help="Output format: text | json."
    ),
) -> None:
    """Inspect AgentLens integrations and paths."""
    if scope not in {"integrations", "paths", "all"}:
        raise typer.BadParameter(
            f"invalid scope {scope!r}; expected integrations | paths | all"
        )
    if fmt not in {"text", "json"}:
        raise typer.BadParameter(
            f"invalid --format {fmt!r}; expected text | json"
        )

    doc = collect_doctor_report(scope)
    if scope in {"integrations", "all"}:
        cmux = _cmux_block()
        if cmux is not None:
            doc["cmux"] = cmux

    if fmt == "json":
        typer.echo(json.dumps(doc, sort_keys=True))
        return

    parts: list[str] = []
    if "integrations" in doc:
        parts.append(_format_text_integrations(doc["integrations"]))
    if "paths" in doc:
        parts.append(_format_text_paths(doc["paths"]))
    if "cmux" in doc:
        parts.append(_format_text_cmux(doc["cmux"]))
    typer.echo("\n".join(parts))


__all__ = ["collect_doctor_report", "doctor"]
