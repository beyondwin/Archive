from __future__ import annotations

import json
from pathlib import Path

from kao.artifacts import ArtifactStore
from kao.config import BuiltinProfiles
from kao.models import FileClaim, TaskSpec
from kao.packetizer import build_task_packet, materialize_prompt


def test_artifact_store_writes_hash_and_home_relative_ref(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = ArtifactStore(tmp_path / ".kao" / "runs" / "ws" / "run" / "artifacts")
    record = store.write_text("task_001", "log", "hello")
    assert Path(record.path).read_text(encoding="utf-8") == "hello"
    assert record.sha256
    assert record.ref.startswith("~/.kao/")


def test_packet_builder_records_write_policy_and_model_assignment() -> None:
    task = TaskSpec(
        task_id="task_001",
        title="Docs",
        risk="low",
        phase="docs",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim("docs/usage.md", "owned"),),
        acceptance_commands=("pytest",),
        required_skills=("test-driven-development",),
    )
    profile = BuiltinProfiles.default()["codex-default"]
    packet = build_task_packet("run-1", task, [{"id": "S1", "title": "Design", "text": "body"}], profile)
    assert packet.schema == "kws.kao.task_packet.v1"
    assert packet.allowed_write_globs == ("docs/usage.md",)
    assert ".git/**" in packet.forbidden_write_globs
    assert packet.model_assignment.runtime == "codex"


def test_materialize_prompt_is_bounded_json(tmp_path: Path) -> None:
    task = TaskSpec(
        task_id="task_001",
        title="Docs",
        risk="low",
        phase="docs",
        dependencies=(),
        spec_refs=(),
        file_claims=(),
        acceptance_commands=(),
    )
    packet = build_task_packet("run-1", task, [], BuiltinProfiles.default()["same-host"])
    path = materialize_prompt(packet, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8").split("```json", 1)[1].rsplit("```", 1)[0])
    assert data["task_id"] == "task_001"
