"""Tests for evaluator failure taxonomy + 12 deterministic checks (task_6).

Covers spec §5.13 (Failure / FailureCategory), §5.14 (12 checks), §5.15-6.3
(engine: alphabetical dispatch, per-check exception → EVALUATOR_ERROR,
resolve_status decision matrix, sort_keys serialization).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from agentlens.constants import (
    SCHEMA_EVAL_V1,
    SCHEMA_EVENT_V1,
    SCHEMA_FINAL_V1,
    SCHEMA_MANIFEST_V1,
    SCHEMA_RUN_V1,
)
from agentlens.evaluator import checks as checks_mod
from agentlens.evaluator import engine as engine_mod
from agentlens.evaluator.checks import (
    REQUIRED_CHECKS,
    CheckResult,
    EvalContext,
    check_agent_outcome_valid,
    check_artifact_hashes_valid,
    check_changed_files_present_when_success,
    check_commands_resolved,
    check_events_well_formed,
    check_failed_commands_acknowledged,
    check_final_present,
    check_manifest_sealed,
    check_residual_risks_explicit,
    check_run_started,
    check_schema_valid,
    check_verification_present,
)
from agentlens.evaluator.engine import evaluate, resolve_status
from agentlens.evaluator.failures import Failure, FailureCategory


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _sha256_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _hash_text(s: str) -> str:
    return _sha256_bytes(s.encode("utf-8"))


def _run_dict(run_id: str = "run_20260101_000000_aaaaaa") -> dict[str, Any]:
    return {
        "schema": SCHEMA_RUN_V1,
        "run_id": run_id,
        "workspace_id": "ws_" + "0" * 16,
        "started_at": "2026-01-01T00:00:00Z",
        "agent": {"name": "generic", "mode": "cli"},
        "workspace": {
            "root_label": "./workspace",
            "root_hash": _hash_text("workspace"),
            "id_basis": "path",
        },
        "recording": {"mode": "minimal", "adapter": "generic"},
    }


def _event(run_id: str, evt_id: str, evt_type: str, payload: dict | None = None) -> dict:
    return {
        "schema": SCHEMA_EVENT_V1,
        "event_id": evt_id,
        "run_id": run_id,
        "ts": "2026-01-01T00:00:01Z",
        "type": evt_type,
        "payload": payload or {},
    }


def _final_dict(
    run_id: str = "run_20260101_000000_aaaaaa",
    outcome: str = "success",
    *,
    changed_files: list | None = None,
    verification: list | None = None,
    residual_risks: list | None = None,
    no_changes_reason: str | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": SCHEMA_FINAL_V1,
        "run_id": run_id,
        "ended_at": "2026-01-01T00:00:02Z",
        "agent_outcome": outcome,
        "summary": "ok",
        "changed_files": [] if changed_files is None else changed_files,
        "verification": [] if verification is None else verification,
        "residual_risks": [] if residual_risks is None else residual_risks,
    }
    if no_changes_reason is not None:
        doc["no_changes_reason"] = no_changes_reason
    return doc


def _manifest_dict(
    run_id: str = "run_20260101_000000_aaaaaa",
    *,
    sealed: bool = True,
    sealed_phase: str = "final",
    files: list | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_MANIFEST_V1,
        "run_id": run_id,
        "sealed_at": "2026-01-01T00:00:10Z",
        "sealed": sealed,
        "sealed_phase": sealed_phase,
        "files": files or [],
        "redaction": {
            "absolute_paths": "masked",
            "secret_like_values": "masked",
            "full_prompts": "not_stored",
            "full_command_output": "excerpted",
        },
    }


def _mkctx(
    tmp_path: Path,
    *,
    run: dict | None = None,
    events: list[dict] | None = None,
    final: dict | None = None,
    manifest: dict | None = None,
    events_lines: list[str] | None = None,
) -> EvalContext:
    run_dir = tmp_path
    run = run if run is not None else _run_dict()
    events = events if events is not None else [_event(run["run_id"], "evt_aaaaaaaaaaaa", "run.started")]
    if events_lines is None:
        events_lines = [json.dumps(e) for e in events]
    return EvalContext(
        run=run,
        events=events,
        events_lines=events_lines,
        final=final,
        manifest=manifest,
        run_dir=run_dir,
    )


# ---------------------------------------------------------------------------
# Failure / FailureCategory
# ---------------------------------------------------------------------------


def test_failure_category_enum_has_all_spec_codes() -> None:
    expected = {
        "MISSING_FINAL",
        "INVALID_RUN_SCHEMA",
        "INVALID_EVENT_SCHEMA",
        "INVALID_FINAL_SCHEMA",
        "INVALID_MANIFEST_SCHEMA",
        "MISSING_VERIFICATION_EVIDENCE",
        "UNACKNOWLEDGED_FAILED_COMMAND",
        "SUCCESS_WITH_RESIDUAL_RISK",
        "ARTIFACT_HASH_MISMATCH",
        "MANIFEST_NOT_SEALED",
        "RECORDING_INCOMPLETE",
        "EVALUATOR_ERROR",
        "COMMAND_TIMEOUT",
        "ENVIRONMENT_BLOCKER",
        "DIFF_SCOPE_UNKNOWN",
        "CHANGED_FILES_MISSING",
        "AGENT_REPORTED_GAP",
        "USER_CORRECTION",
        "UNKNOWN",
    }
    actual = {c.value for c in FailureCategory}
    assert expected == actual


def test_failure_dataclass_to_dict_rounds_confidence() -> None:
    f = Failure(
        category=FailureCategory.EVALUATOR_ERROR,
        severity="high",
        source="evaluator",
        blame_scope="unknown",
        recoverability="rerun_or_fix",
        confidence=0.123456,
        summary="boom",
        evidence=("trace1", "trace2"),
    )
    d = f.to_dict()
    assert d["category"] == "EVALUATOR_ERROR"
    assert d["confidence"] == 0.12
    assert d["evidence"] == ["trace1", "trace2"]


def test_failure_is_frozen() -> None:
    f = Failure(
        category=FailureCategory.UNKNOWN,
        severity="low",
        source="evaluator",
        blame_scope="unknown",
        recoverability="informational",
        confidence=0.5,
        summary="x",
        evidence=(),
    )
    with pytest.raises((AttributeError, Exception)):
        f.severity = "high"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# REQUIRED_CHECKS structure
# ---------------------------------------------------------------------------


def test_required_checks_has_12_entries() -> None:
    assert len(REQUIRED_CHECKS) == 12


def test_required_checks_contains_all_named_checks() -> None:
    names = {fn.__name__ for fn in REQUIRED_CHECKS}
    assert names == {
        "check_schema_valid",
        "check_run_started",
        "check_events_well_formed",
        "check_final_present",
        "check_agent_outcome_valid",
        "check_verification_present",
        "check_commands_resolved",
        "check_failed_commands_acknowledged",
        "check_changed_files_present_when_success",
        "check_residual_risks_explicit",
        "check_manifest_sealed",
        "check_artifact_hashes_valid",
    }


# ---------------------------------------------------------------------------
# check_schema_valid
# ---------------------------------------------------------------------------


def test_check_schema_valid_passes_for_valid_docs(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=_final_dict())
    r = check_schema_valid(ctx)
    assert r.status == "passed"


def test_check_schema_valid_fails_for_invalid_run(tmp_path: Path) -> None:
    bad = _run_dict()
    del bad["agent"]
    ctx = _mkctx(tmp_path, run=bad)
    r = check_schema_valid(ctx)
    assert r.status == "failed"
    assert any(f.category == FailureCategory.INVALID_RUN_SCHEMA for f in r.failures)


def test_check_schema_valid_fails_for_malformed_event_line(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, events_lines=["{not json"])
    r = check_schema_valid(ctx)
    assert r.status == "failed"
    assert any(f.category == FailureCategory.INVALID_EVENT_SCHEMA for f in r.failures)


# ---------------------------------------------------------------------------
# check_run_started
# ---------------------------------------------------------------------------


def test_check_run_started_passes_when_run_loaded(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path)
    r = check_run_started(ctx)
    assert r.status == "passed"


def test_check_run_started_fails_when_no_run_started_event(tmp_path: Path) -> None:
    events = [_event(_run_dict()["run_id"], "evt_bbbbbbbbbbbb", "task.started")]
    ctx = _mkctx(tmp_path, events=events)
    r = check_run_started(ctx)
    assert r.status == "failed"


# ---------------------------------------------------------------------------
# check_events_well_formed
# ---------------------------------------------------------------------------


def test_check_events_well_formed_passes(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path)
    r = check_events_well_formed(ctx)
    assert r.status == "passed"


def test_check_events_well_formed_fails_on_bad_line(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, events_lines=["{not json"])
    r = check_events_well_formed(ctx)
    assert r.status == "failed"


# ---------------------------------------------------------------------------
# check_final_present
# ---------------------------------------------------------------------------


def test_check_final_present_passes_when_final_loaded(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=_final_dict())
    r = check_final_present(ctx)
    assert r.status == "passed"


def test_check_final_present_fails_when_missing(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=None)
    r = check_final_present(ctx)
    assert r.status == "failed"
    assert any(f.category == FailureCategory.MISSING_FINAL for f in r.failures)


# ---------------------------------------------------------------------------
# check_agent_outcome_valid
# ---------------------------------------------------------------------------


def test_check_agent_outcome_valid_passes_for_known_outcome(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=_final_dict(outcome="success"))
    r = check_agent_outcome_valid(ctx)
    assert r.status == "passed"


def test_check_agent_outcome_valid_skipped_when_no_final(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=None)
    r = check_agent_outcome_valid(ctx)
    assert r.status == "skipped"


def test_check_agent_outcome_valid_fails_on_bogus_outcome(tmp_path: Path) -> None:
    final = _final_dict()
    final["agent_outcome"] = "weird"
    ctx = _mkctx(tmp_path, final=final)
    r = check_agent_outcome_valid(ctx)
    assert r.status == "failed"


# ---------------------------------------------------------------------------
# check_verification_present
# ---------------------------------------------------------------------------


def _v(status: str = "passed") -> dict:
    return {
        "kind": "command",
        "command_hash": _hash_text("cmd"),
        "status": status,
        "excerpt": "ok",
    }


def test_check_verification_present_passes_with_entries(tmp_path: Path) -> None:
    final = _final_dict(verification=[_v()])
    ctx = _mkctx(tmp_path, final=final)
    r = check_verification_present(ctx)
    assert r.status == "passed"


def test_check_verification_present_fails_when_success_with_no_entries(tmp_path: Path) -> None:
    final = _final_dict(outcome="success", verification=[])
    ctx = _mkctx(tmp_path, final=final)
    r = check_verification_present(ctx)
    assert r.status == "failed"
    assert any(
        f.category == FailureCategory.MISSING_VERIFICATION_EVIDENCE for f in r.failures
    )


def test_check_verification_present_skipped_for_non_success(tmp_path: Path) -> None:
    final = _final_dict(outcome="failed", verification=[])
    ctx = _mkctx(tmp_path, final=final)
    r = check_verification_present(ctx)
    assert r.status == "skipped"


def test_check_verification_present_skipped_when_no_final(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=None)
    r = check_verification_present(ctx)
    assert r.status == "skipped"


# ---------------------------------------------------------------------------
# check_commands_resolved
# ---------------------------------------------------------------------------


def _cmd_started(run_id: str, eid: str, cmd_hash: str | None = None) -> dict:
    return _event(
        run_id,
        eid,
        "command.started",
        {"command_hash": cmd_hash or _hash_text("cmd1")},
    )


def _cmd_finished(
    run_id: str, eid: str, cmd_hash: str | None = None, status: str = "passed"
) -> dict:
    return _event(
        run_id,
        eid,
        "command.finished",
        {"command_hash": cmd_hash or _hash_text("cmd1"), "status": status},
    )


def test_check_commands_resolved_passes_when_all_started_have_finished(
    tmp_path: Path,
) -> None:
    run = _run_dict()
    events = [
        _event(run["run_id"], "evt_aaaaaaaaaaaa", "run.started"),
        _cmd_started(run["run_id"], "evt_bbbbbbbbbbbb"),
        _cmd_finished(run["run_id"], "evt_cccccccccccc"),
    ]
    ctx = _mkctx(tmp_path, run=run, events=events)
    r = check_commands_resolved(ctx)
    assert r.status == "passed"


def test_check_commands_resolved_fails_when_started_missing_finished(
    tmp_path: Path,
) -> None:
    run = _run_dict()
    events = [
        _event(run["run_id"], "evt_aaaaaaaaaaaa", "run.started"),
        _cmd_started(run["run_id"], "evt_bbbbbbbbbbbb"),
    ]
    ctx = _mkctx(tmp_path, run=run, events=events)
    r = check_commands_resolved(ctx)
    assert r.status == "failed"


# ---------------------------------------------------------------------------
# check_failed_commands_acknowledged
# ---------------------------------------------------------------------------


def test_check_failed_commands_acknowledged_passes_when_no_failed(
    tmp_path: Path,
) -> None:
    run = _run_dict()
    events = [
        _event(run["run_id"], "evt_aaaaaaaaaaaa", "run.started"),
        _cmd_started(run["run_id"], "evt_bbbbbbbbbbbb"),
        _cmd_finished(run["run_id"], "evt_cccccccccccc", status="passed"),
    ]
    ctx = _mkctx(tmp_path, run=run, events=events, final=_final_dict())
    r = check_failed_commands_acknowledged(ctx)
    assert r.status == "passed"


def test_check_failed_commands_acknowledged_fails_when_unacknowledged(
    tmp_path: Path,
) -> None:
    run = _run_dict()
    h = _hash_text("bad-cmd")
    events = [
        _event(run["run_id"], "evt_aaaaaaaaaaaa", "run.started"),
        _cmd_started(run["run_id"], "evt_bbbbbbbbbbbb", cmd_hash=h),
        _cmd_finished(run["run_id"], "evt_cccccccccccc", cmd_hash=h, status="failed"),
    ]
    # final acknowledges nothing
    ctx = _mkctx(
        tmp_path,
        run=run,
        events=events,
        final=_final_dict(outcome="success", verification=[]),
    )
    r = check_failed_commands_acknowledged(ctx)
    assert r.status == "failed"
    assert any(
        f.category == FailureCategory.UNACKNOWLEDGED_FAILED_COMMAND for f in r.failures
    )


def test_check_failed_commands_acknowledged_passes_when_failed_in_verification(
    tmp_path: Path,
) -> None:
    run = _run_dict()
    h = _hash_text("bad-cmd")
    events = [
        _event(run["run_id"], "evt_aaaaaaaaaaaa", "run.started"),
        _cmd_started(run["run_id"], "evt_bbbbbbbbbbbb", cmd_hash=h),
        _cmd_finished(run["run_id"], "evt_cccccccccccc", cmd_hash=h, status="failed"),
    ]
    verification = [{
        "kind": "command",
        "command_hash": h,
        "status": "failed",
        "excerpt": "see the failure",
    }]
    ctx = _mkctx(
        tmp_path,
        run=run,
        events=events,
        final=_final_dict(outcome="partial", verification=verification),
    )
    r = check_failed_commands_acknowledged(ctx)
    assert r.status == "passed"


# ---------------------------------------------------------------------------
# check_changed_files_present_when_success
# ---------------------------------------------------------------------------


def test_check_changed_files_skipped_when_outcome_not_success(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=_final_dict(outcome="failed"))
    r = check_changed_files_present_when_success(ctx)
    assert r.status == "skipped"


def test_check_changed_files_passes_when_entries_present(tmp_path: Path) -> None:
    final = _final_dict(
        outcome="success",
        changed_files=[{"path_label": "./a", "path_hash": _hash_text("./a")}],
        verification=[_v()],
    )
    ctx = _mkctx(tmp_path, final=final)
    r = check_changed_files_present_when_success(ctx)
    assert r.status == "passed"


def test_check_changed_files_passes_when_empty_with_reason(tmp_path: Path) -> None:
    final = _final_dict(
        outcome="success",
        changed_files=[],
        no_changes_reason="docs-only run",
    )
    ctx = _mkctx(tmp_path, final=final)
    r = check_changed_files_present_when_success(ctx)
    assert r.status == "passed"


def test_check_changed_files_fails_when_empty_no_reason(tmp_path: Path) -> None:
    final = _final_dict(outcome="success", changed_files=[])
    ctx = _mkctx(tmp_path, final=final)
    r = check_changed_files_present_when_success(ctx)
    assert r.status == "failed"
    assert any(f.category == FailureCategory.DIFF_SCOPE_UNKNOWN for f in r.failures)


# ---------------------------------------------------------------------------
# check_residual_risks_explicit
# ---------------------------------------------------------------------------


def test_check_residual_risks_passes_when_no_residual(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=_final_dict(residual_risks=[]))
    r = check_residual_risks_explicit(ctx)
    assert r.status == "passed"


def test_check_residual_risks_fails_when_success_with_medium_residual(
    tmp_path: Path,
) -> None:
    final = _final_dict(
        outcome="success",
        residual_risks=[{"severity": "medium", "summary": "x"}],
    )
    ctx = _mkctx(tmp_path, final=final)
    r = check_residual_risks_explicit(ctx)
    assert r.status == "failed"
    assert any(
        f.category == FailureCategory.SUCCESS_WITH_RESIDUAL_RISK for f in r.failures
    )


def test_check_residual_risks_passes_with_low_residual_and_verification(
    tmp_path: Path,
) -> None:
    final = _final_dict(
        outcome="success",
        residual_risks=[{"severity": "low", "summary": "minor"}],
        verification=[_v()],
    )
    ctx = _mkctx(tmp_path, final=final)
    r = check_residual_risks_explicit(ctx)
    assert r.status == "passed"
    assert r.message  # warning surfaced


# ---------------------------------------------------------------------------
# check_manifest_sealed
# ---------------------------------------------------------------------------


def test_check_manifest_sealed_passes_when_sealed(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, manifest=_manifest_dict(sealed=True))
    r = check_manifest_sealed(ctx)
    assert r.status == "passed"


def test_check_manifest_sealed_skipped_when_no_manifest(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, manifest=None)
    r = check_manifest_sealed(ctx)
    assert r.status == "skipped"


def test_check_manifest_sealed_fails_when_sealed_false(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, manifest=_manifest_dict(sealed=False))
    r = check_manifest_sealed(ctx)
    assert r.status == "failed"
    assert any(f.category == FailureCategory.MANIFEST_NOT_SEALED for f in r.failures)


# ---------------------------------------------------------------------------
# check_artifact_hashes_valid
# ---------------------------------------------------------------------------


def test_check_artifact_hashes_valid_skipped_when_no_manifest(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, manifest=None)
    r = check_artifact_hashes_valid(ctx)
    assert r.status == "skipped"


def test_check_artifact_hashes_valid_passes_when_files_match(tmp_path: Path) -> None:
    fpath = tmp_path / "events.jsonl"
    fpath.write_bytes(b"hello\n")
    digest = _sha256_bytes(b"hello\n")
    manifest = _manifest_dict(files=[{"path": "events.jsonl", "sha256": digest}])
    ctx = _mkctx(tmp_path, manifest=manifest)
    r = check_artifact_hashes_valid(ctx)
    assert r.status == "passed"


def test_check_artifact_hashes_valid_fails_when_mismatch(tmp_path: Path) -> None:
    fpath = tmp_path / "events.jsonl"
    fpath.write_bytes(b"hello\n")
    wrong = _sha256_bytes(b"goodbye\n")
    manifest = _manifest_dict(files=[{"path": "events.jsonl", "sha256": wrong}])
    ctx = _mkctx(tmp_path, manifest=manifest)
    r = check_artifact_hashes_valid(ctx)
    assert r.status == "failed"
    assert any(
        f.category == FailureCategory.ARTIFACT_HASH_MISMATCH for f in r.failures
    )


# ---------------------------------------------------------------------------
# resolve_status decision matrix
# ---------------------------------------------------------------------------


def test_resolve_status_incomplete_when_final_missing(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=None)
    assert resolve_status(ctx, []) == "incomplete"


def test_resolve_status_failed_when_any_check_failed(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=_final_dict())
    results = [
        CheckResult(name="schema_valid", status="passed"),
        CheckResult(name="final_present", status="failed"),
    ]
    assert resolve_status(ctx, results) == "failed"


def test_resolve_status_passed_when_all_pass_or_skipped(tmp_path: Path) -> None:
    ctx = _mkctx(tmp_path, final=_final_dict())
    results = [
        CheckResult(name="schema_valid", status="passed"),
        CheckResult(name="final_present", status="passed"),
        CheckResult(name="manifest_sealed", status="skipped"),
    ]
    assert resolve_status(ctx, results) == "passed"


# ---------------------------------------------------------------------------
# Engine integration (alphabetical dispatch + EVALUATOR_ERROR surfacing)
# ---------------------------------------------------------------------------


def _write_run_tree(
    tmp_path: Path,
    *,
    run: dict | None = None,
    events: list[dict] | None = None,
    final: dict | None = None,
    manifest: dict | None = None,
) -> Path:
    run = run if run is not None else _run_dict()
    events = events if events is not None else [
        _event(run["run_id"], "evt_aaaaaaaaaaaa", "run.started")
    ]
    (tmp_path / "run.json").write_text(json.dumps(run), encoding="utf-8")
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    if final is not None:
        (tmp_path / "final.json").write_text(json.dumps(final), encoding="utf-8")
    if manifest is not None:
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def test_engine_dispatches_checks_alphabetically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_run_tree(tmp_path, final=_final_dict(verification=[_v()]))
    order: list[str] = []

    def _wrap(fn):
        def inner(ctx):
            order.append(fn.__name__)
            return fn(ctx)
        inner.__name__ = fn.__name__
        return inner

    wrapped = tuple(_wrap(fn) for fn in REQUIRED_CHECKS)
    monkeypatch.setattr(engine_mod, "REQUIRED_CHECKS", wrapped)
    evaluate(tmp_path)
    assert order == sorted(order), f"checks not dispatched alphabetically: {order}"


def test_engine_surfaces_evaluator_error_on_check_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_run_tree(tmp_path, final=_final_dict(verification=[_v()]))

    def _boom(ctx):
        raise RuntimeError("explode")
    _boom.__name__ = "check_schema_valid"

    new_required = tuple(
        _boom if fn.__name__ == "check_schema_valid" else fn
        for fn in REQUIRED_CHECKS
    )
    monkeypatch.setattr(engine_mod, "REQUIRED_CHECKS", new_required)
    doc = evaluate(tmp_path)
    assert doc["status"] == "error"
    assert any(f["category"] == "EVALUATOR_ERROR" for f in doc["failures"])


def test_engine_serializes_with_sort_keys(tmp_path: Path) -> None:
    _write_run_tree(tmp_path, final=_final_dict(verification=[_v()]))
    evaluate(tmp_path)
    raw = (tmp_path / "eval.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    rewrote = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    assert json.loads(raw) == json.loads(rewrote)
    # top-level keys appear in alphabetical order
    keys_in_order = [k for k in parsed.keys()]
    assert keys_in_order == sorted(keys_in_order)


def test_engine_returns_incomplete_when_no_final(tmp_path: Path) -> None:
    _write_run_tree(tmp_path)
    doc = evaluate(tmp_path)
    assert doc["status"] == "incomplete"


def test_engine_returns_passed_for_clean_run(tmp_path: Path) -> None:
    fpath_events = b'{"schema":"agentlens.event.v1"}\n'  # placeholder
    _write_run_tree(
        tmp_path,
        final=_final_dict(
            verification=[_v()],
            changed_files=[{"path_label": "./a", "path_hash": _hash_text("./a")}],
        ),
    )
    doc = evaluate(tmp_path)
    assert doc["status"] == "passed", doc
