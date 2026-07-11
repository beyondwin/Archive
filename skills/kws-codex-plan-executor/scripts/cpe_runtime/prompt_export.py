from __future__ import annotations

import hashlib
import re
import shlex
from pathlib import Path

from .model_policy import CORE_ROUTE, launcher_argv


def heredoc_delimiter(payload: str) -> str:
    base = "CPE_" + hashlib.sha256(payload.encode()).hexdigest()[:16].upper()
    candidate = base
    counter = 0
    lines = set(payload.splitlines())
    while candidate in lines:
        counter += 1
        candidate = f"{base}_{counter}"
    return candidate


def outer_fence(payload: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", payload)), default=2)
    return "`" * max(3, longest + 1)


def _render_refs(template: str, refs: dict[str, object]) -> str:
    rendered = template
    replacements = {
        "WORKSPACE": refs.get("workspace", ""),
        "PLAN": refs.get("plan", ""),
        "PLAN_SHA256": refs.get("plan_sha256", ""),
        "SPEC": refs.get("spec", "none"),
        "SPEC_SHA256": refs.get("spec_sha256", "none"),
        "DOCS": refs.get("docs", "none"),
        "MODE": refs.get("mode", "prompt"),
        "HEADLESS_SANDBOX": refs.get("headless_sandbox", "workspace-write"),
        "HANDOFF_SECTION": refs.get("handoff_section", ""),
    }
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def render_export_bundle(
    template: str,
    refs: dict[str, object] | Path,
    workspace: Path | None = None,
) -> str:
    """Render one collision-safe block; the two-argument form is kept for callers."""

    if workspace is None:
        workspace = Path(refs)
        payload = template.rstrip()
    else:
        if not isinstance(refs, dict):
            raise TypeError("export refs must be a mapping")
        payload = _render_refs(template, refs).rstrip()
    command = shlex.join(launcher_argv(CORE_ROUTE, workspace, sandbox="workspace-write"))
    delimiter = heredoc_delimiter(payload)
    block = f"{command} <<'{delimiter}'\n{payload}\n{delimiter}"
    fence = outer_fence(block)
    return f"{fence}text\n{block}\n{fence}\n"
