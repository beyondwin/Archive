from __future__ import annotations

import shlex
from pathlib import Path

from .model_policy import CORE_ROUTE, launcher_argv


def render_export_bundle(prompt: str, workspace: Path) -> str:
    command = shlex.join(launcher_argv(CORE_ROUTE, workspace, sandbox="workspace-write"))
    return f"```text\n{command} <<'CPE_PROMPT'\n{prompt.rstrip()}\nCPE_PROMPT\n```\n"
