from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentrunway.adapters.base import AdapterCapabilities, RuntimeAdapter, WorkerHandle
from agentrunway.db import AgentRunwayDb
from agentrunway.git_ops import Git
from agentrunway.models import FileClaim, ProcessSnapshot, TaskSpec, WorkerResultEnvelope, WorkerSpec
from agentrunway.supervisor import run_implementer_attempt
from agentrunway.worktrees import create_main_worktree


class AdvancingBaseAdapter(RuntimeAdapter):
    capabilities = AdapterCapabilities(runtime="test")

    def __init__(self, *, main_worktree: Path) -> None:
        self.main_worktree = main_worktree
        self.spec: WorkerSpec | None = None
        self.commit: str | None = None

    def prepare(self, spec: WorkerSpec) -> WorkerHandle:
        self.spec = spec
        return WorkerHandle(worker_id=spec.worker_id, task_id=spec.task_id, role=spec.role, pid=None)

    def start(self, handle: WorkerHandle) -> WorkerHandle:
        return handle

    def poll(self, handle: WorkerHandle) -> ProcessSnapshot:
        return ProcessSnapshot(state="exited", pid=None, returncode=0)

    def collect(self, handle: WorkerHandle) -> WorkerResultEnvelope:
        assert self.spec is not None
        dependency = self.main_worktree / "docs" / "dependency.md"
        dependency.parent.mkdir(parents=True, exist_ok=True)
        dependency.write_text("dependency\n", encoding="utf-8")
        subprocess.run(["git", "add", "docs/dependency.md"], cwd=self.main_worktree, check=True)
        subprocess.run(["git", "commit", "-m", "dependency"], cwd=self.main_worktree, check=True, capture_output=True)

        worker_tree = Path(self.spec.worktree_path)
        target = worker_tree / "src" / "task.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/task.py"], cwd=worker_tree, check=True)
        subprocess.run(["git", "commit", "-m", "worker"], cwd=worker_tree, check=True, capture_output=True)
        self.commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worker_tree,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        payload = {
            "schema": "agentrunway.worker_result.v1",
            "worker_id": self.spec.worker_id,
            "task_id": self.spec.task_id,
            "role": self.spec.role,
            "status": "success",
            "changed_files": ["src/task.py"],
            "commit": self.commit,
            "commits": [self.commit],
            "summary": "done",
            "method_audit": {"superpowers_used": True, "tdd_red": "failed", "tdd_green": "passed"},
        }
        output_path = Path(self.spec.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload), encoding="utf-8")
        return WorkerResultEnvelope(
            worker_id=self.spec.worker_id,
            task_id=self.spec.task_id,
            role=self.spec.role,
            runtime="test",
            process=ProcessSnapshot(state="exited", pid=None, returncode=0),
            result_path=str(output_path),
            result_json=payload,
            stdout_path=str(output_path.with_suffix(".stdout")),
            stderr_path=str(output_path.with_suffix(".stderr")),
        )


def test_implementer_scope_validation_uses_worker_creation_base(git_repo: Path, tmp_path: Path) -> None:
    run_id = "run-scope-base"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    main_worktree = tmp_path / "main"
    create_main_worktree(Git(git_repo), main_worktree, run_id, Git(git_repo).rev_parse("HEAD"))
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    task = TaskSpec(
        task_id="task_001",
        title="Task",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1.1",),
        file_claims=(FileClaim(path="src/*.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )

    candidate_id = run_implementer_attempt(
        db=db,
        run_id=run_id,
        git=Git(git_repo),
        main_worktree=main_worktree,
        worktree_root=tmp_path / "worktrees",
        run_dir=run_dir,
        task=task,
        packet_path=run_dir / "packet.json",
        prompt_path=run_dir / "prompt.txt",
        adapter=AdvancingBaseAdapter(main_worktree=main_worktree),
        runtime="test",
        model="test",
        reasoning_effort="n/a",
        attempt=1,
        timeout_seconds=30,
    )

    candidate = db.list_merge_candidates()[0]
    assert candidate["id"] == candidate_id
    assert candidate["changed_files"] == ["src/task.py"]
