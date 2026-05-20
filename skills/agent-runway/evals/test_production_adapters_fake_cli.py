from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agentrunway.adapters.claude import ClaudeAdapter
from agentrunway.adapters.codex import CodexAdapter
from agentrunway.models import WorkerSpec


ROOT = Path(__file__).resolve().parents[1]
FAKE_BIN = ROOT / "evals" / "fixtures" / "fake-bin"


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "agentrunway@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "AgentRunway Test"], cwd=path, check=True)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True)


def _spec(tmp_path: Path, runtime: str) -> WorkerSpec:
    artifact_dir = tmp_path / "artifacts" / runtime
    prompt = artifact_dir / "prompt.txt"
    packet = artifact_dir / "packet.json"
    output = artifact_dir / "worker_result.json"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    prompt.write_text("Run fake worker and write AGENTRUNWAY_WORKER_OUTPUT.\n", encoding="utf-8")
    packet.write_text("{}", encoding="utf-8")
    return WorkerSpec(
        run_id="run-1",
        task_id="task_001",
        worker_id=f"task_001-{runtime}-001",
        role="implementer",
        runtime=runtime,
        model="test-model",
        reasoning_effort="high",
        prompt_path=str(prompt),
        packet_path=str(packet),
        output_path=str(output),
        worktree_path=str(tmp_path),
        artifact_dir=str(artifact_dir),
        timeout_seconds=10,
        attempt=1,
    )


def test_codex_adapter_runs_fake_cli_and_collects_worker_result(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ['PATH']}")
    adapter = CodexAdapter(model="test-model", reasoning_effort="high")
    handle = adapter.start(adapter.prepare(_spec(tmp_path, "codex")))
    envelope = adapter.collect(handle)

    assert envelope.process.state == "exited"
    assert envelope.result_json is not None
    assert envelope.result_json["summary"] == "fake codex success"
    assert (tmp_path / "src" / "codex_worker.py").exists()


def test_claude_adapter_runs_fake_cli_and_collects_worker_result(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ['PATH']}")
    adapter = ClaudeAdapter(model="test-model", reasoning_effort="high")
    handle = adapter.start(adapter.prepare(_spec(tmp_path, "claude")))
    envelope = adapter.collect(handle)

    assert envelope.process.state == "exited"
    assert envelope.result_json is not None
    assert envelope.result_json["summary"] == "fake claude success"
    assert (tmp_path / "src" / "claude_worker.py").exists()
