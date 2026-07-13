"""Export-only schema-4 prompt and handoff rendering."""

from __future__ import annotations

import hashlib
import shlex
from pathlib import Path
from typing import Sequence


def _document_line(role: str, path: Path) -> str:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{role} input must be a regular file")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{role} input must be a regular file")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return f"- {role}: {resolved}\n  sha256: {digest}"


def render_export(
    *,
    workspace: Path,
    specs: Sequence[Path],
    plans: Sequence[Path],
    program_plan: Path | None,
    mode: str,
) -> str:
    """Hash source documents directly and return an execution-free bundle."""

    if mode not in {"prompt", "handoff"}:
        raise ValueError("export mode must be prompt or handoff")
    if not plans:
        raise ValueError("at least one plan is required")
    expanded_workspace = workspace.expanduser()
    if expanded_workspace.is_symlink():
        raise ValueError("workspace must be a real directory")
    resolved_workspace = expanded_workspace.resolve(strict=True)
    if not resolved_workspace.is_dir():
        raise ValueError("workspace must be a real directory")
    documents = [
        *(_document_line("spec", path) for path in specs),
        *(_document_line("plan", path) for path in plans),
    ]
    if program_plan is not None:
        documents.append(_document_line("program-plan", program_plan))
    lines = [
        "# CPE schema-4 export",
        "",
        f"Workspace: {resolved_workspace}",
        "",
        "Ordered documents:",
        *documents,
        "",
        "Use Superpowers inside each bounded task, review, and final role.",
        "No CPE run started; this export created no run, artifact, or worktree state.",
    ]
    if mode == "handoff":
        command = ["python3", "scripts/cpe.py", "run"]
        for path in specs:
            command.extend(("--spec", str(path.expanduser().resolve(strict=True))))
        for path in plans:
            command.extend(("--plan", str(path.expanduser().resolve(strict=True))))
        if program_plan is not None:
            command.extend(
                ("--program-plan", str(program_plan.expanduser().resolve(strict=True)))
            )
        command.extend(("--workspace", str(resolved_workspace)))
        lines.extend(("", "Schema-4 handoff command:", shlex.join(command)))
    return "\n".join(lines) + "\n"


def render_export_bundle(*args: object, **kwargs: object) -> str:
    """Reject the removed v3 template interface with a stable error."""

    raise ValueError("legacy prompt export interface is unavailable")
