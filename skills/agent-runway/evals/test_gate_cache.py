from __future__ import annotations

from agentrunway.db import AgentRunwayDb
from agentrunway.gate_cache import GateCacheKey, gate_cache_digest


def test_gate_cache_round_trips_by_digest(tmp_path):
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    key = GateCacheKey(
        gate="verification",
        base_commit="base",
        task_packet_hash="packet",
        diff_hash="diff",
        command_hash="commands",
        tool_version="python-3",
    )
    digest = gate_cache_digest(key)
    result = {
        "schema": "agentrunway.verification_result.v1",
        "worker_id": "task_001-verifier-001",
        "task_id": "task_001",
        "status": "passed",
        "checks": [{"command": "python -m pytest", "status": "passed"}],
        "method_audit": {"superpowers_used": True},
    }

    assert db.get_gate_cache(gate="verification", cache_key=digest) is None

    db.put_gate_cache(gate="verification", cache_key=digest, result=result, metadata={"source": "local"})

    cached = db.get_gate_cache(gate="verification", cache_key=digest)
    assert cached is not None
    assert cached["result"] == result
    assert cached["metadata"] == {"source": "local"}
