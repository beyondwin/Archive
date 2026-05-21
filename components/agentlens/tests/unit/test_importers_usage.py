"""Unit tests for importers.usage.extract_usage (spec §4.3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentlens.importers.usage import ModelUsage, UsageSummary, extract_usage

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "usage"


def _load_jsonl(name: str) -> list[dict]:
    path = FIXTURES / name
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Dataclass shape / defaults
# ---------------------------------------------------------------------------


def test_usage_summary_defaults_are_spec_aligned() -> None:
    summary = UsageSummary(source="claude-session")
    assert summary.cost_usd is None
    assert summary.pricing_source == "unknown"
    assert summary.schema_version == "1"
    assert summary.confidence == "unknown"
    assert summary.model_breakdown == ()
    assert summary.events_with_usage == 0
    assert summary.events_missing_usage == 0
    assert summary.model_field_missing_events == 0


def test_to_dict_matches_spec_shape() -> None:
    summary = UsageSummary(
        source="claude-session",
        input_tokens=10,
        output_tokens=5,
        cache_creation_tokens=2,
        cache_read_tokens=1,
        reasoning_tokens=0,
        model_breakdown=(
            ModelUsage(
                model="claude-opus-4-7",
                input_tokens=10,
                output_tokens=5,
                cache_creation_tokens=2,
                cache_read_tokens=1,
            ),
        ),
        confidence="exact",
        events_with_usage=1,
    )
    out = summary.to_dict()
    assert out["schema_version"] == "1"
    assert out["source"] == "claude-session"
    assert out["input_tokens"] == 10
    assert out["output_tokens"] == 5
    assert out["cache_creation_tokens"] == 2
    assert out["cache_read_tokens"] == 1
    assert out["reasoning_tokens"] == 0
    assert out["cost_usd"] is None
    assert out["pricing_source"] == "unknown"
    assert out["confidence"] == "exact"
    assert isinstance(out["model_breakdown"], list)
    assert out["model_breakdown"][0] == {
        "model": "claude-opus-4-7",
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_tokens": 2,
        "cache_read_tokens": 1,
        "reasoning_tokens": 0,
    }
    assert out["diagnostics"] == {
        "events_with_usage": 1,
        "events_missing_usage": 0,
        "model_field_missing_events": 0,
    }


# ---------------------------------------------------------------------------
# Empty / degenerate
# ---------------------------------------------------------------------------


def test_empty_records_yields_unknown_all_zero() -> None:
    summary = extract_usage("claude-session", [])
    assert summary.confidence == "unknown"
    assert summary.input_tokens == 0
    assert summary.output_tokens == 0
    assert summary.cache_creation_tokens == 0
    assert summary.cache_read_tokens == 0
    assert summary.reasoning_tokens == 0
    assert summary.events_with_usage == 0
    assert summary.events_missing_usage == 0
    assert summary.model_field_missing_events == 0
    assert summary.model_breakdown == ()


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


def test_claude_with_full_usage_is_exact() -> None:
    records = _load_jsonl("claude-with-usage.jsonl")
    assert len(records) == 10
    summary = extract_usage("claude-session", records)
    assert summary.source == "claude-session"
    assert summary.confidence == "exact"
    assert summary.events_with_usage == 10
    assert summary.events_missing_usage == 0
    assert summary.model_field_missing_events == 0
    # Totals from the fixture.
    assert summary.input_tokens == 100 + 200 + 300 + 120 + 140 + 160 + 180 + 110 + 130 + 150
    assert summary.output_tokens == 50 + 75 + 80 + 60 + 65 + 70 + 72 + 55 + 58 + 62
    assert summary.cache_creation_tokens == 10 + 20 + 30 + 12 + 14 + 16 + 18 + 11 + 13 + 15
    assert summary.cache_read_tokens == 5 + 15 + 25 + 8 + 9 + 11 + 13 + 6 + 7 + 10
    assert summary.reasoning_tokens == 0
    # One model in the breakdown.
    assert len(summary.model_breakdown) == 1
    only = summary.model_breakdown[0]
    assert only.model == "claude-opus-4-7"
    assert only.input_tokens == summary.input_tokens


def test_claude_mixed_usage_is_estimated() -> None:
    records = _load_jsonl("claude-mixed-usage.jsonl")
    assert len(records) == 3
    summary = extract_usage("claude-session", records)
    assert summary.confidence == "estimated"
    assert summary.events_with_usage == 3
    assert summary.events_missing_usage == 0
    # Missing cache_read_input_tokens treated as 0 across all three lines.
    assert summary.cache_read_tokens == 0
    assert summary.input_tokens == 600
    assert summary.output_tokens == 205


def test_claude_under_50_percent_with_usage_is_unknown() -> None:
    # 10 records total, 4 with usage → 40% < 50% → unknown.
    records: list[dict] = []
    for _ in range(4):
        records.append(
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-7",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_creation_input_tokens": 1,
                        "cache_read_input_tokens": 0,
                    },
                },
            }
        )
    for _ in range(6):
        records.append({"type": "assistant", "message": {"model": "claude-opus-4-7"}})
    summary = extract_usage("claude-session", records)
    assert summary.confidence == "unknown"
    assert summary.events_with_usage == 4
    assert summary.events_missing_usage == 6


def test_claude_missing_model_field_increments_diagnostic() -> None:
    records = [
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 1,
                    "cache_read_input_tokens": 0,
                }
            },
        }
    ]
    summary = extract_usage("claude-session", records)
    assert summary.events_with_usage == 1
    assert summary.model_field_missing_events == 1
    # No model breakdown entry when no model is known.
    assert summary.model_breakdown == ()


def test_claude_multi_model_aggregation() -> None:
    records = [
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 5,
                },
            },
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-7",
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 75,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 15,
                },
            },
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 25,
                    "cache_creation_input_tokens": 5,
                    "cache_read_input_tokens": 2,
                },
            },
        },
    ]
    summary = extract_usage("claude-session", records)
    assert summary.confidence == "exact"
    assert summary.input_tokens == 350
    assert summary.output_tokens == 150
    by_model = {m.model: m for m in summary.model_breakdown}
    assert set(by_model) == {"claude-opus-4-7", "claude-sonnet-4-7"}
    assert by_model["claude-opus-4-7"].input_tokens == 150
    assert by_model["claude-opus-4-7"].output_tokens == 75
    assert by_model["claude-sonnet-4-7"].input_tokens == 200
    assert by_model["claude-sonnet-4-7"].output_tokens == 75


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------


def test_codex_cli_with_usage_is_exact() -> None:
    records = _load_jsonl("codex-cli-with-usage.jsonl")
    assert len(records) == 5
    summary = extract_usage("codex-rollout", records)
    assert summary.source == "codex-rollout"
    assert summary.confidence == "exact"
    assert summary.events_with_usage == 5
    assert summary.events_missing_usage == 0
    assert summary.input_tokens == 500 + 600 + 700 + 400 + 300
    assert summary.output_tokens == 150 + 200 + 250 + 120 + 90
    assert summary.cache_read_tokens == 100 + 150 + 200 + 50 + 30
    assert summary.reasoning_tokens == 40 + 60 + 80 + 20 + 10


def test_codex_desktop_no_usage_is_unknown() -> None:
    records = _load_jsonl("codex-desktop-no-usage.jsonl")
    assert len(records) == 5
    summary = extract_usage("codex-rollout", records)
    assert summary.confidence == "unknown"
    assert summary.events_with_usage == 0
    assert summary.events_missing_usage == 5
    assert summary.input_tokens == 0
    assert summary.output_tokens == 0


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def test_returns_frozen_dataclass() -> None:
    summary = extract_usage("claude-session", [])
    with pytest.raises(Exception):
        summary.input_tokens = 999  # type: ignore[misc]


def test_mixed_full_and_no_usage_records_force_estimated() -> None:
    """5 records with full usage + 5 records with no usage block → estimated.

    Spec §4.3: 'Mix of populated and inferred' includes per-record absence.
    """
    records = [
        {
            "message": {
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            }
        }
        for _ in range(5)
    ] + [
        {"message": {"model": "claude-opus-4-7"}}  # no usage block
        for _ in range(5)
    ]
    summary = extract_usage("claude-session", records)
    assert summary.confidence == "estimated", summary
    assert summary.events_with_usage == 5
    assert summary.events_missing_usage == 5
