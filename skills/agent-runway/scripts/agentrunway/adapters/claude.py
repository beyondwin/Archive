from __future__ import annotations

from pathlib import Path

from .base import AdapterCapabilities


class ClaudeAdapter:
    capabilities = AdapterCapabilities(runtime="claude", supports_reattach=True)

    def __init__(self, model: str = "opus", reasoning_effort: str = "high"):
        self.model = model
        self.reasoning_effort = reasoning_effort

    def build_command(self, prompt_path: Path, workdir: Path) -> list[str]:
        return ["claude", "-p", str(prompt_path), "--model", self.model, "--cwd", str(workdir)]
