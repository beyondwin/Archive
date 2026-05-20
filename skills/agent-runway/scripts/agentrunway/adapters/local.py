from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..models import RESULT_SCHEMA, WorkerResult
from .base import AdapterCapabilities, RuntimeAdapter


class LocalAdapter(RuntimeAdapter):
    capabilities = AdapterCapabilities(runtime="local")

    def __init__(self, fake_success: bool = False):
        self.fake_success = fake_success

    def run(self, packet_path: Path, workdir: Path) -> WorkerResult:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        task_id = packet.get("task_id", "task")
        status = "simulated_success" if self.fake_success else "blocked"
        method_audit = (
            {
                "superpowers_used": True,
                "simulation": True,
                "tdd_workflow": "not_exercised_simulated",
            }
            if self.fake_success
            else {"superpowers_used": True, "simulation": False}
        )
        result = WorkerResult(
            schema=RESULT_SCHEMA,
            worker_id=f"{task_id}-implementer-001",
            task_id=task_id,
            role=packet.get("role", "implementer"),
            status=status,
            changed_files=[],
            commit=None,
            summary="local simulated success" if self.fake_success else "local adapter requires fake_success",
            commands_run=[],
            method_audit=method_audit,
            residual_risks=[],
        )
        (workdir / "worker_result.json").write_text(json.dumps(asdict(result), indent=2, sort_keys=True), encoding="utf-8")
        return result
