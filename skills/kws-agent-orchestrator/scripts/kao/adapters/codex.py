from __future__ import annotations

from pathlib import Path

from .base import AdapterCapabilities


class CodexAdapter:
    capabilities = AdapterCapabilities(runtime="codex", supports_reattach=False)

    def __init__(self, model: str = "gpt-5.5", reasoning_effort: str = "xhigh"):
        self.model = model
        self.reasoning_effort = reasoning_effort

    def build_command(self, prompt_path: Path, workdir: Path) -> list[str]:
        return [
            "codex",
            "exec",
            "--model",
            self.model,
            "--reasoning-effort",
            self.reasoning_effort,
            "--cwd",
            str(workdir),
            str(prompt_path),
        ]
