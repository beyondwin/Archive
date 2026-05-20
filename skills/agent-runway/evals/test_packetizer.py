from __future__ import annotations

import json
from pathlib import Path

from agentrunway.artifacts import ArtifactStore
from agentrunway.config import BuiltinProfiles
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.packetizer import build_task_packet, materialize_prompt, materialize_worker_prompt
from agentrunway.runner import _spec_slices


def test_artifact_store_writes_hash_and_home_relative_ref(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store = ArtifactStore(tmp_path / ".agentrunway" / "runs" / "ws" / "run" / "artifacts")
    record = store.write_text("task_001", "log", "hello")
    assert Path(record.path).read_text(encoding="utf-8") == "hello"
    assert record.sha256
    assert record.ref.startswith("~/.agentrunway/")


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
    assert packet.schema == "agentrunway.task_packet.v1"
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


def test_materialize_worker_prompt_inlines_packet_and_result_contract(tmp_path: Path) -> None:
    task = TaskSpec(
        task_id="task_001",
        title="Docs",
        risk="low",
        phase="docs",
        dependencies=(),
        spec_refs=(),
        file_claims=(FileClaim("docs/usage.md", "owned"),),
        acceptance_commands=("pytest",),
    )
    packet = build_task_packet("run-1", task, [], BuiltinProfiles.default()["codex-default"])
    path = materialize_worker_prompt(packet, tmp_path / "packet.json", tmp_path / "worker_result.json", tmp_path)
    text = path.read_text(encoding="utf-8")

    data = json.loads(text.split("```json", 1)[1].rsplit("```", 1)[0])
    assert data["task_id"] == "task_001"
    assert '"output_schema": "agentrunway.worker_result.v1"' in text
    for field in ("schema", "worker_id", "task_id", "role", "status", "changed_files", "summary", "method_audit"):
        assert field in text


def test_packet_spec_slices_canonicalize_numbered_input_refs(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "# AgentRunway Trust Hardening\n\n"
        "## 1. Overview\n\n"
        "Overview text.\n\n"
        "## 2. Runner\n\n"
        "Runner text.\n\n"
        "## 3. Workers\n\n"
        "Worker text.\n\n"
        "## 4. Review\n\n"
        "Review text.\n\n"
        "## 5. Verification\n\n"
        "Verification text.\n\n"
        "## 6. Spec References\n\n"
        "Spec reference text.\n\n"
        "### 6.1 Manifest\n\n"
        "Manifest text.\n\n"
        "### 6.2 Contract\n\n"
        "Contract text.\n\n"
        "### 6.3 Canonical Resolver\n\n"
        "Resolver text.\n",
        encoding="utf-8",
    )
    task = TaskSpec(
        task_id="task_001",
        title="Docs",
        risk="low",
        phase="docs",
        dependencies=(),
        spec_refs=("6.3",),
        file_claims=(FileClaim("docs/usage.md", "owned"),),
        acceptance_commands=("pytest",),
    )

    packet = build_task_packet("run-1", task, _spec_slices(spec, task.spec_refs), BuiltinProfiles.default()["same-host"])

    assert packet.spec_refs[0]["id"] == "S1.6.3"
    assert packet.spec_refs[0]["text"].strip()
    assert packet.spec_refs[0]["input_ref"] in {"6.3", "S6.3"}
