"""``agentlens gc`` — apply retention policy to the run store (spec §5.9, §8.4).

The command consults the default :class:`agentlens.store.retention.RetentionPolicy`
and either prints what would be deleted (``--dry-run``) or performs the
deletion. Output is human-readable text suitable for ``stdout``.

Config-driven overrides (workspace/global config keys) are deferred to v1;
v0 uses the dataclass defaults.
"""
from __future__ import annotations

import typer

from ..store.paths import agentlens_home
from ..store.retention import RetentionPolicy, gc as retention_gc


def gc(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print deletion candidates without unlinking."
    ),
) -> None:
    """Apply retention policy: list (or delete) eligible artifacts."""
    home = agentlens_home()
    policy = RetentionPolicy()
    report = retention_gc(home, policy, dry_run=dry_run)

    verb = "Would delete" if report.dry_run else "Deleted"
    for path in report.deleted_paths:
        typer.echo(f"{verb}: {path}")
    typer.echo(
        f"Total: {len(report.deleted_paths)} files, "
        f"{report.freed_bytes} bytes"
    )


__all__ = ["gc"]
