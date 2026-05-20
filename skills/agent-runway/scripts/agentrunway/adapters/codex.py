from __future__ import annotations

import json
from pathlib import Path

from ..models import ProcessSnapshot, WorkerResultEnvelope, WorkerSpec
from .base import AdapterCapabilities, WorkerHandle
from .process import ProcessHandle, ProcessLaunchSpec, ProcessSupervisor


class CodexAdapter:
    capabilities = AdapterCapabilities(runtime="codex", supports_reattach=False)

    def __init__(self, model: str = "gpt-5.5", reasoning_effort: str = "xhigh"):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.supervisor = ProcessSupervisor()

    def build_command(self, prompt_text: str, workdir: Path) -> list[str]:
        return [
            "codex",
            "exec",
            "--model",
            self.model,
            "-c",
            f'model_reasoning_effort="{self.reasoning_effort}"',
            prompt_text,
        ]

    def prepare(self, spec: WorkerSpec) -> WorkerHandle:
        artifact_dir = Path(spec.artifact_dir)
        stdout_path = artifact_dir / f"{spec.worker_id}.stdout.log"
        stderr_path = artifact_dir / f"{spec.worker_id}.stderr.log"
        prompt_text = Path(spec.prompt_path).read_text(encoding="utf-8")
        launch = ProcessLaunchSpec(
            worker_id=spec.worker_id,
            command=self.build_command(prompt_text, Path(spec.worktree_path)),
            cwd=Path(spec.worktree_path),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_seconds=spec.timeout_seconds,
            env={
                "AGENTRUNWAY_RUN_ID": spec.run_id,
                "AGENTRUNWAY_TASK_ID": spec.task_id,
                "AGENTRUNWAY_WORKER_ID": spec.worker_id,
                "AGENTRUNWAY_WORKER_ROLE": spec.role,
                "AGENTRUNWAY_PACKET_PATH": spec.packet_path,
                "AGENTRUNWAY_WORKER_OUTPUT": spec.output_path,
            },
        )
        return WorkerHandle(
            worker_id=spec.worker_id,
            task_id=spec.task_id,
            role=spec.role,
            pid=None,
            metadata={"spec": spec.__dict__, "launch": self._launch_json(launch)},
        )

    def start(self, handle: WorkerHandle) -> WorkerHandle:
        process = self.supervisor.start(self._launch_from_json(dict(handle.metadata["launch"])))
        metadata = dict(handle.metadata)
        metadata["process"] = process.__dict__
        return WorkerHandle(handle.worker_id, handle.task_id, handle.role, process.pid, metadata)

    def poll(self, handle: WorkerHandle) -> ProcessSnapshot:
        return self.supervisor.poll(ProcessHandle(**dict(handle.metadata["process"])))

    def collect(self, handle: WorkerHandle) -> WorkerResultEnvelope:
        process = ProcessHandle(**dict(handle.metadata["process"]))
        snapshot = self.supervisor.wait(process)
        spec = dict(handle.metadata["spec"])
        output_path = Path(str(spec["output_path"]))
        result_json = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else None
        return WorkerResultEnvelope(
            worker_id=handle.worker_id,
            task_id=handle.task_id,
            role=handle.role,
            runtime="codex",
            process=snapshot,
            result_path=str(output_path),
            result_json=result_json,
            stdout_path=str(process.stdout_path),
            stderr_path=str(process.stderr_path),
            error=None if result_json is not None else "missing_worker_result",
        )

    def cancel(self, handle: WorkerHandle) -> None:
        self.supervisor.cancel(ProcessHandle(**dict(handle.metadata["process"])))

    def _launch_json(self, launch: ProcessLaunchSpec) -> dict[str, object]:
        return {
            "worker_id": launch.worker_id,
            "command": launch.command,
            "cwd": str(launch.cwd),
            "stdout_path": str(launch.stdout_path),
            "stderr_path": str(launch.stderr_path),
            "timeout_seconds": launch.timeout_seconds,
            "env": launch.env,
        }

    def _launch_from_json(self, launch: dict[str, object]) -> ProcessLaunchSpec:
        return ProcessLaunchSpec(
            worker_id=str(launch["worker_id"]),
            command=[str(item) for item in launch["command"]],
            cwd=Path(str(launch["cwd"])),
            stdout_path=Path(str(launch["stdout_path"])),
            stderr_path=Path(str(launch["stderr_path"])),
            timeout_seconds=int(launch["timeout_seconds"]),
            env={str(key): str(value) for key, value in dict(launch["env"]).items()},
        )
