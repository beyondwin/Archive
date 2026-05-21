from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentlens.store.trust_artifacts import (
    TrustArtifactError,
    read_trust_report,
    write_projection,
    write_trust_report,
)


def _projection(run_id: str) -> dict:
    return {
        "schema": "agentlens.waygent_projection.v1",
        "run_id": run_id,
        "waygent_run_id": "run_waygent",
        "producer": "waygent",
        "status": "finished",
        "event_count": 1,
        "timeline": [],
        "tasks": [],
        "artifacts": {"contract": "present", "artifact_graph": "present", "coverage": "present"},
        "coverage": {"covered": [], "partial": [], "blocked": [], "unreferenced": []},
        "projection_issues": [],
        "agentlens_emit_health": {"last_status": "agentlens_emitted", "statuses": {}},
        "payload_safety": "ok",
    }


def _report(run_id: str) -> dict:
    return {
        "schema": "agentlens.trust_report.v1",
        "run_id": run_id,
        "waygent_run_id": "run_waygent",
        "claimed_outcome": "success",
        "trust_verdict": "trusted",
        "evidence_strength": "strong",
        "blocking_evidence": [],
        "missing_evidence": [],
        "residual_risks": [],
        "operator_actions": [],
        "projection_issues": [],
    }


def test_write_and_read_trust_artifacts(tmp_path: Path) -> None:
    run_id = "run_20260521_000000_agent"

    projection_path = write_projection(tmp_path, _projection(run_id))
    report_path = write_trust_report(tmp_path, _report(run_id))

    assert projection_path == tmp_path / "artifacts" / "waygent_projection.json"
    assert report_path == tmp_path / "artifacts" / "trust_report.json"
    assert read_trust_report(tmp_path)["trust_verdict"] == "trusted"


def test_read_trust_report_rejects_malformed_artifact(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "trust_report.json").write_text(json.dumps({"schema": "agentlens.trust_report.v1"}), encoding="utf-8")

    with pytest.raises(TrustArtifactError):
        read_trust_report(tmp_path)
