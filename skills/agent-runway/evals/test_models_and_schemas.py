from __future__ import annotations

import json
from pathlib import Path

from agentrunway.models import (
    CLAIM_MODES,
    EVENT_SCHEMA,
    OUTCOMES,
    REASONING_LEVELS,
    RESULT_SCHEMA,
    TASK_PACKET_SCHEMA,
)


ROOT = Path(__file__).resolve().parents[1]


def test_schema_constants_match_design() -> None:
    assert TASK_PACKET_SCHEMA == "agentrunway.task_packet.v1"
    assert RESULT_SCHEMA == "agentrunway.worker_result.v1"
    assert EVENT_SCHEMA == "agentrunway.event.v1"


def test_core_enums_cover_mvp_policy() -> None:
    assert CLAIM_MODES == {"owned", "shared_append", "consumes", "read_only", "forbidden"}
    assert OUTCOMES == {"finished", "failed", "blocked", "cancelled", "unknown"}
    assert REASONING_LEVELS == {"lowest", "low", "medium", "high", "highest"}


def test_reference_schema_files_are_valid_json() -> None:
    schema_dir = ROOT / "references" / "schemas"
    expected = {
        "task_packet.v1.json",
        "worker_result.v1.json",
        "review_result.v1.json",
        "verification_result.v1.json",
        "event.v1.json",
    }
    assert {path.name for path in schema_dir.glob("*.json")} == expected
    for path in schema_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert data["type"] == "object"


def test_review_schema_matches_runtime_statuses() -> None:
    data = json.loads((ROOT / "references" / "schemas" / "review_result.v1.json").read_text(encoding="utf-8"))
    assert data["properties"]["status"]["enum"] == ["approved", "changes_requested", "rejected"]
