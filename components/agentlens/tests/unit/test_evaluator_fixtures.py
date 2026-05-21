"""Byte-equality regression tests for the five M2 evaluator fixtures (task_7).

Each fixture directory under ``tests/fixtures/<name>_run/`` ships a complete
pre-evaluation run tree (``run.json``, ``events.jsonl``, optionally
``final.json``, ``manifest.json``) plus the expected ``expected_eval.json``
that ``agentlens.evaluator.engine.evaluate`` must produce.

Spec §9.1 fixture-by-fixture intent (authoritative over the plan):

* ``minimal_run`` – success, verification present, no residual risks → passed
* ``failed_command_run`` – command exit 42 unacknowledged in final     → failed
* ``missing_final_run`` – events only, no final.json                   → incomplete
* ``residual_risk_run`` – success but high-severity residual risk      → failed
* ``corrupt_manifest_run`` – manifest sha256 mismatch                  → failed
  (ARTIFACT_HASH_MISMATCH)

The test:

1. Copies fixture inputs into ``tmp_path`` (so the engine can write
   ``eval.json`` without dirtying the source tree).
2. Validates every input doc against the bundled JSON Schemas — guards
   against fixture drift if a schema is bumped.
3. Calls ``evaluate(run_dir)``, normalises ``evaluated_at`` (the only
   non-deterministic field), and asserts byte-equal JSON with the fixture's
   ``expected_eval.json`` (also normalised).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from agentlens.evaluator.engine import evaluate
from agentlens.schema.validate import validate_doc, validate_event_line

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

FIXTURE_NAMES: tuple[str, ...] = (
    "minimal_run",
    "failed_command_run",
    "missing_final_run",
    "residual_risk_run",
    "corrupt_manifest_run",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_NORMALIZED_TS = "1970-01-01T00:00:00Z"


def _normalize_timestamps(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *doc* with ``evaluated_at`` zeroed.

    Only ``evaluated_at`` is non-deterministic in eval.json output. Input
    timestamps (``started_at``, ``ended_at``, ``sealed_at``, event ``ts``)
    are authored explicitly per fixture and remain comparable as-is.
    """
    out = dict(doc)
    if "evaluated_at" in out:
        out["evaluated_at"] = _NORMALIZED_TS
    return out


def _copy_fixture(src: Path, dst: Path) -> Path:
    """Copy fixture inputs (everything except ``expected_eval.json``)."""
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.name == "expected_eval.json":
            continue
        shutil.copy(p, dst / p.name)
    return dst


def _validate_fixture_inputs(fixture: Path) -> None:
    """Re-validate each input document against the bundled v1 schemas."""
    run_path = fixture / "run.json"
    assert run_path.is_file(), f"{fixture.name}: run.json missing"
    validate_doc(json.loads(run_path.read_text(encoding="utf-8")), schema_name="run")

    events_path = fixture / "events.jsonl"
    if events_path.is_file():
        for idx, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            validate_event_line(line)  # raises EventLineError on mismatch

    final_path = fixture / "final.json"
    if final_path.is_file():
        validate_doc(
            json.loads(final_path.read_text(encoding="utf-8")), schema_name="final"
        )

    manifest_path = fixture / "manifest.json"
    if manifest_path.is_file():
        validate_doc(
            json.loads(manifest_path.read_text(encoding="utf-8")), schema_name="manifest"
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_five_fixture_directories_exist() -> None:
    """Spec §9.1 requires exactly these five ``_run`` fixture directories."""
    on_disk = sorted(
        p.name for p in FIXTURES_DIR.iterdir() if p.is_dir() and p.name.endswith("_run")
    )
    assert on_disk == sorted(FIXTURE_NAMES)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_fixture_inputs_validate_against_schemas(fixture_name: str) -> None:
    """Each fixture's input JSON docs must satisfy their v1 JSON Schema."""
    _validate_fixture_inputs(FIXTURES_DIR / fixture_name)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_evaluator_output_matches_expected(
    tmp_path: Path, fixture_name: str
) -> None:
    """``evaluate(run_dir)`` must produce byte-equal JSON with the fixture's
    ``expected_eval.json`` after ``evaluated_at`` normalisation."""
    src = FIXTURES_DIR / fixture_name
    expected_path = src / "expected_eval.json"
    assert expected_path.is_file(), (
        f"{fixture_name}: expected_eval.json missing (regenerate via "
        f"`python -m agentlens.evaluator.engine` against the fixture)"
    )
    expected = _normalize_timestamps(json.loads(expected_path.read_text(encoding="utf-8")))

    work = _copy_fixture(src, tmp_path / fixture_name)
    actual = _normalize_timestamps(evaluate(work))

    actual_bytes = json.dumps(actual, sort_keys=True, indent=2).encode("utf-8")
    expected_bytes = json.dumps(expected, sort_keys=True, indent=2).encode("utf-8")
    assert actual_bytes == expected_bytes, (
        f"{fixture_name}: evaluator output drifted from expected_eval.json"
    )


# ---------------------------------------------------------------------------
# Spec-pinned status assertions (defends against silent fixture regeneration)
# ---------------------------------------------------------------------------


_EXPECTED_STATUS = {
    "minimal_run": "passed",
    "failed_command_run": "failed",
    "missing_final_run": "incomplete",
    "residual_risk_run": "failed",
    "corrupt_manifest_run": "failed",
}


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_expected_status_matches_spec(fixture_name: str) -> None:
    """Pin each fixture's top-level status to the spec §9.1 expectation."""
    expected = json.loads(
        (FIXTURES_DIR / fixture_name / "expected_eval.json").read_text(encoding="utf-8")
    )
    assert expected["status"] == _EXPECTED_STATUS[fixture_name], (
        f"{fixture_name}: expected_eval.json status drift; "
        f"spec §9.1 requires {_EXPECTED_STATUS[fixture_name]!r}"
    )


def test_corrupt_manifest_run_surfaces_artifact_hash_mismatch() -> None:
    """The corrupt-manifest fixture must specifically expose
    ``ARTIFACT_HASH_MISMATCH`` in its failures list (spec §9.1)."""
    expected = json.loads(
        (FIXTURES_DIR / "corrupt_manifest_run" / "expected_eval.json").read_text(
            encoding="utf-8"
        )
    )
    categories = {f["category"] for f in expected["failures"]}
    assert "ARTIFACT_HASH_MISMATCH" in categories
