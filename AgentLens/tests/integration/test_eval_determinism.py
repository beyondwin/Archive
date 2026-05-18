"""Determinism regression: ``evaluate(run_dir)`` must be byte-equal across
runs once timestamp fields are masked (spec §9.5, S1.10.5).

For each of the five M2 fixtures (task_7), the test:

1. Copies the fixture inputs into a fresh ``tmp_path`` so the engine can
   write its own ``eval.json`` without dirtying the source tree.
2. Calls :func:`agentlens.evaluator.engine.evaluate` **twice** against the
   same inputs.
3. Normalises both outputs through
   :func:`agentlens.evaluator.engine.normalize_for_diff` (which zeros every
   ``*_at`` ISO8601-UTC timestamp).
4. Asserts the two JSON serialisations are byte-equal under ``sort_keys``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentlens.evaluator.engine import evaluate, normalize_for_diff

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

FIXTURE_NAMES: tuple[str, ...] = (
    "minimal_run",
    "failed_command_run",
    "missing_final_run",
    "residual_risk_run",
    "corrupt_manifest_run",
)

_PLACEHOLDER = "0000-00-00T00:00:00Z"


def _copy_fixture(src: Path, dst: Path) -> Path:
    """Copy fixture inputs (everything except ``expected_eval.json``)."""
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.name == "expected_eval.json":
            continue
        shutil.copy(p, dst / p.name)
    return dst


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_evaluate_is_byte_equal_across_runs(
    tmp_path: Path, fixture_name: str
) -> None:
    """Two back-to-back evaluator runs must produce identical JSON after
    timestamp normalisation (spec §9.5)."""
    run_a = _copy_fixture(FIXTURES_DIR / fixture_name, tmp_path / "a")
    run_b = _copy_fixture(FIXTURES_DIR / fixture_name, tmp_path / "b")

    doc_a = evaluate(run_a)
    doc_b = evaluate(run_b)

    norm_a = normalize_for_diff(doc_a)
    norm_b = normalize_for_diff(doc_b)

    bytes_a = json.dumps(norm_a, sort_keys=True).encode("utf-8")
    bytes_b = json.dumps(norm_b, sort_keys=True).encode("utf-8")
    assert bytes_a == bytes_b, (
        f"{fixture_name}: evaluator output drifted between two runs"
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_normalize_for_diff_masks_evaluated_at(
    tmp_path: Path, fixture_name: str
) -> None:
    """After normalisation the top-level ``evaluated_at`` field must equal
    the spec's fixed placeholder (spec §9.5)."""
    run_dir = _copy_fixture(FIXTURES_DIR / fixture_name, tmp_path / fixture_name)
    doc = evaluate(run_dir)
    assert doc["evaluated_at"] != _PLACEHOLDER  # sanity: real timestamp present
    normalised = normalize_for_diff(doc)
    assert normalised["evaluated_at"] == _PLACEHOLDER


def test_normalize_for_diff_does_not_mutate_input(tmp_path: Path) -> None:
    """``normalize_for_diff`` must return a NEW dict and leave the original
    document untouched (callers may inspect the real ``evaluated_at`` after)."""
    run_dir = _copy_fixture(FIXTURES_DIR / "minimal_run", tmp_path / "minimal_run")
    doc = evaluate(run_dir)
    original_evaluated_at = doc["evaluated_at"]
    assert original_evaluated_at != _PLACEHOLDER

    _ = normalize_for_diff(doc)
    assert doc["evaluated_at"] == original_evaluated_at
    assert doc["evaluated_at"] != _PLACEHOLDER
