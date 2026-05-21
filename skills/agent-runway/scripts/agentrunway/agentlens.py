from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AgentLensEmitError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentLensCliEmitter:
    cli: str = "agentlens"
    timeout_seconds: int = 10
    agentlens_run_id: str | None = None

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        target_run = self.agentlens_run_id or str(
            payload.get("agentlens_run_id")
            or payload.get("agentrunway_run_id")
            or payload.get("run_id")
            or ""
        )
        if not target_run:
            raise AgentLensEmitError("missing AgentLens run id")
        outbound = dict(payload)
        if outbound.get("schema") == "agentlens.event.v2":
            outbound["run_id"] = target_run
        raw = json.dumps(outbound, ensure_ascii=False, sort_keys=True)
        try:
            result = subprocess.run(
                [self.cli, "event", "append", "--run", target_run, "--type", event_type, "--payload-stdin"],
                input=raw,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AgentLensEmitError(f"AgentLens CLI not found: {self.cli}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AgentLensEmitError(f"AgentLens emit timed out after {self.timeout_seconds}s") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise AgentLensEmitError(detail)

    def close(self, *, outcome: str, summary: str) -> None:
        if not self.agentlens_run_id:
            return
        try:
            subprocess.run(
                [self.cli, "run-close", "--run", self.agentlens_run_id, "--outcome", outcome, "--summary", summary],
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return


def create_agentlens_emitter(
    *,
    cli: str = "agentlens",
    timeout_seconds: int = 10,
    agentrunway_run_id: str | None = None,
    workspace: Path | None = None,
) -> AgentLensCliEmitter | None:
    resolved = shutil.which(cli)
    if resolved is None:
        return None
    agentlens_run_id: str | None = None
    if agentrunway_run_id is not None:
        command = [
            resolved,
            "run-open",
            "--agent",
            "agentrunway",
            "--meta",
            f"agentrunway_run_id={agentrunway_run_id}",
        ]
        if workspace is not None:
            command.extend(["--workspace", str(workspace)])
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        agentlens_run_id = result.stdout.strip().splitlines()[-1]
    return AgentLensCliEmitter(cli=resolved, timeout_seconds=timeout_seconds, agentlens_run_id=agentlens_run_id)
