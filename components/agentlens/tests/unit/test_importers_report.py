"""Tests for `agentlens.importers.report` and `agentlens.importers.artifacts`.

Covers spec §4.1 (import-report shape, counter aggregation, analysis-state
derivation, source-path redaction) and the artifact writer's atomic-replace
guarantees.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agentlens.importers.artifacts import write_artifact_json
from agentlens.importers.report import ImportReport


# ---------------------------------------------------------------------------
# Counter aggregation + analysis_state
# ---------------------------------------------------------------------------


def _new_report(**overrides):
    defaults = dict(source="claude-session", source_session_id="abc123")
    defaults.update(overrides)
    return ImportReport(**defaults)


def test_counter_aggregation():
    r = _new_report()
    for _ in range(100):
        r.record_parsed()
    for i in range(3):
        r.record_skip("json_decode", line_number=i + 1, byte_offset=i * 10)
    r.record_skip("line_too_large", line_number=104, byte_offset=999)

    assert r.total_scanned == 104
    assert r.parsed == 100
    assert r.skipped_malformed == 3
    assert r.skipped_oversized == 1
    assert r.skipped_unsupported_type == 0
    assert r.analysis_state == "partial"


def test_analysis_state_full():
    r = _new_report()
    for _ in range(5):
        r.record_parsed()
    assert r.analysis_state == "full"


def test_analysis_state_byte_cap_partial():
    r = _new_report()
    for _ in range(10):
        r.record_parsed()
    r.record_byte_cap_hit()
    assert r.byte_cap_hit is True
    assert r.analysis_state == "partial"


def test_analysis_state_deep_parse_only_skipped():
    r = _new_report()
    for _ in range(10):
        r.record_parsed()
    r.deep_parse_only_skipped = True
    assert r.analysis_state == "skipped"


def test_analysis_state_unsupported_type_partial():
    r = _new_report()
    r.record_parsed()
    r.record_skip("unsupported_type:foo", line_number=1, byte_offset=0)
    assert r.skipped_unsupported_type == 1
    assert r.analysis_state == "partial"


def test_record_skip_unknown_reason_raises():
    r = _new_report()
    with pytest.raises(ValueError):
        r.record_skip("nonsense", line_number=1, byte_offset=0)


def test_first_error_preserved():
    r = _new_report()
    r.record_skip("json_decode", line_number=2, byte_offset=42)
    r.record_skip("json_decode", line_number=5, byte_offset=200)
    r.record_skip("line_too_large", line_number=8, byte_offset=900)
    assert r.first_error is not None
    assert r.first_error.line_number == 2
    assert r.first_error.byte_offset == 42
    assert r.first_error.reason == "json_decode"


# ---------------------------------------------------------------------------
# Source path redaction + hash
# ---------------------------------------------------------------------------


def test_source_path_redaction(tmp_path: Path):
    raw = tmp_path / "secret-dir" / "session-xyz.jsonl"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("x", encoding="utf-8")

    r = _new_report(source_session_id="sess-XYZ")
    r.set_source_path(raw)

    # The label must not contain the raw absolute path or HOME prefix.
    assert "secret-dir" not in r.source_path
    assert str(raw) not in r.source_path
    assert str(tmp_path) not in r.source_path

    # Hash format: "sha256:<64-hex>" = 71 chars total.
    assert r.source_path_hash.startswith("sha256:")
    assert len(r.source_path_hash) == 71

    # The full serialized dict must also not leak the raw path.
    serialized = json.dumps(r.to_dict(), sort_keys=True)
    assert str(raw) not in serialized
    assert str(tmp_path) not in serialized


def test_to_dict_matches_spec_shape():
    r = _new_report()
    r.record_parsed()
    r.record_parsed()
    r.set_display_title("hello", source="first_user_message")
    r.set_transcript_artifact("/relative/transcript.jsonl", 1234)
    r.finalize(duration_ms=42)

    d = r.to_dict()

    # Top-level required keys.
    for key in (
        "schema_version",
        "source",
        "source_path",
        "source_path_hash",
        "source_session_id",
        "analysis_state",
        "source_bytes",
        "byte_cap_bytes",
        "byte_cap_hit",
        "byte_cap_source",
        "lines",
        "first_error",
        "transcript_artifact",
        "derived",
        "duration_ms",
    ):
        assert key in d, f"missing key: {key}"

    # Nested shapes.
    assert set(d["lines"].keys()) == {
        "total_scanned",
        "parsed",
        "skipped_malformed",
        "skipped_unsupported_type",
        "skipped_oversized",
    }
    assert d["lines"]["parsed"] == 2
    assert d["lines"]["total_scanned"] == 2

    assert set(d["derived"].keys()) == {
        "display_title",
        "title_source",
        "title_algorithm",
    }
    assert d["derived"]["display_title"] == "hello"
    assert d["derived"]["title_source"] == "first_user_message"
    assert d["derived"]["title_algorithm"].startswith("agentlens.title.")

    assert d["transcript_artifact"] == {
        "path": "/relative/transcript.jsonl",
        "bytes": 1234,
        "copied": True,
    }
    assert d["first_error"] is None
    assert d["analysis_state"] == "full"
    assert d["duration_ms"] == 42
    assert d["schema_version"] == "1"


def test_to_dict_first_error_serialized():
    r = _new_report()
    r.record_skip("json_decode", line_number=3, byte_offset=99)
    d = r.to_dict()
    assert d["first_error"] == {
        "line_number": 3,
        "byte_offset": 99,
        "reason": "json_decode",
    }


# ---------------------------------------------------------------------------
# Artifact writer (atomic + deterministic)
# ---------------------------------------------------------------------------


def test_write_artifact_json_writes_deterministic(tmp_path: Path):
    target = tmp_path / "out" / "import_report.json"
    data = {"b": 2, "a": 1, "nested": {"y": 2, "x": 1}}
    write_artifact_json(target, data)

    assert target.exists()
    text = target.read_text(encoding="utf-8")
    # Deterministic: keys sorted, indent=2, trailing newline.
    assert text == json.dumps(data, sort_keys=True, indent=2) + "\n"


def test_atomic_write_no_partial_on_failure(monkeypatch, tmp_path: Path):
    target = tmp_path / "out" / "import_report.json"

    def boom(src, dst):  # noqa: ARG001
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        write_artifact_json(target, {"a": 1})

    # The target file must NOT exist (atomic replace failed before publish).
    assert not target.exists()
    # And no tmp leftovers should be lying around in the parent dir.
    leftovers = [
        p for p in target.parent.iterdir() if p.name != target.name
    ]
    assert leftovers == [], f"tmp leftovers: {leftovers}"
