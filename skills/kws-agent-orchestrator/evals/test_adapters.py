from __future__ import annotations

import json
from pathlib import Path

from kao.adapters.base import AdapterCapabilities, WorkerHandle
from kao.adapters.local import LocalAdapter


def test_worker_handle_can_be_serialized() -> None:
    handle = WorkerHandle(worker_id="w1", task_id="task_001", role="implementer", pid=None, metadata={"a": 1})
    assert handle.to_json()["worker_id"] == "w1"


def test_local_adapter_writes_fake_success_result(tmp_path: Path) -> None:
    adapter = LocalAdapter(fake_success=True)
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps({"task_id": "task_001", "role": "implementer"}), encoding="utf-8")
    result = adapter.run(packet, tmp_path)
    assert result.status == "success"
    assert result.method_audit["superpowers_used"] is True
    assert (tmp_path / "worker_result.json").exists()


def test_adapter_capabilities_default_to_no_network() -> None:
    caps = AdapterCapabilities(runtime="local")
    assert caps.network_egress == ()
