"""Snapshot tests for ``--format json`` output (spec §10.2, task_12).

Locks JSON schema v1 for the five query commands (``latest``, ``status``,
``show``, ``failures``, ``risks``). Each test seeds a deterministic
``AGENTLENS_HOME`` from the committed fixture run trees, invokes the CLI
via :class:`typer.testing.CliRunner`, normalizes the parsed JSON via
:func:`agentlens.evaluator.engine.normalize_for_diff` (masks ``*_at``
timestamps to ``0000-00-00T00:00:00Z``) and compares byte-for-byte against
``tests/fixtures/format_snapshots/<command>.json``.

To regenerate snapshots after an intentional schema change::

    AGENTLENS_UPDATE_SNAPSHOTS=1 \
        .venv/bin/python -m pytest tests/integration/test_format_json_snapshot.py

The snapshot files are part of the schema contract — review the diff
before committing.

JSON output MUST NOT leak absolute filesystem paths (spec §10.2). This is
enforced by an explicit substring check against ``tmp_path`` and the
fixture source directory inside each snapshot test.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens.cli import app
from agentlens.evaluator.engine import normalize_for_diff

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOT_DIR = FIXTURE_ROOT / "format_snapshots"

# Fixture-run sources: (fixture_dir_name, workspace_id, run_id)
_SEED_RUNS = (
    ("minimal_run", "ws_0000000000000001", "run_20260101_000000_aaaaaa"),
    ("failed_command_run", "ws_0000000000000002", "run_20260101_000001_bbbbbb"),
    ("residual_risk_run", "ws_0000000000000004", "run_20260101_000003_dddddd"),
)

UPDATE_ENV = "AGENTLENS_UPDATE_SNAPSHOTS"


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def seeded_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Materialize a deterministic ``AGENTLENS_HOME`` from committed fixtures.

    Each fixture's ``expected_eval.json`` becomes the run's ``eval.json``
    so query.failures/query.risks see a populated evaluator output.
    """
    home = tmp_path / "agentlens_home"
    runs_root = home / "runs"
    runs_root.mkdir(parents=True)
    for fixture_name, workspace_id, run_id in _SEED_RUNS:
        src = FIXTURE_ROOT / fixture_name
        dst = runs_root / workspace_id / run_id
        dst.mkdir(parents=True)
        for member in src.iterdir():
            if member.name == "expected_eval.json":
                shutil.copyfile(member, dst / "eval.json")
            else:
                shutil.copyfile(member, dst / member.name)
    monkeypatch.setenv("AGENTLENS_HOME", str(home))
    return home


def _invoke_json(runner: CliRunner, args: list[str]) -> object:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _snapshot_path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.json"


def _canonical_text(payload: object) -> str:
    """Canonical form: deep-masked timestamps, sorted keys, indent=2, NL."""
    masked = normalize_for_diff(payload)
    return json.dumps(masked, sort_keys=True, indent=2) + "\n"


def _assert_snapshot(name: str, payload: object, leak_guards: list[str]) -> None:
    """Compare *payload* against the named snapshot (creating if requested)."""
    canonical = _canonical_text(payload)
    for guard in leak_guards:
        assert guard not in canonical, (
            f"absolute path leak in {name}: {guard!r} present in JSON output"
        )
    snapshot = _snapshot_path(name)
    if os.environ.get(UPDATE_ENV) == "1":
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(canonical, encoding="utf-8")
        return
    assert snapshot.is_file(), (
        f"snapshot missing: {snapshot} — re-run with {UPDATE_ENV}=1 to create"
    )
    expected = snapshot.read_text(encoding="utf-8")
    assert canonical == expected, (
        f"{name} snapshot mismatch.\n"
        f"--- expected ({snapshot}) ---\n{expected}\n"
        f"--- actual ---\n{canonical}"
    )


def _leak_guards(seeded_home: Path) -> list[str]:
    return [str(seeded_home), str(FIXTURE_ROOT)]


def test_latest_json_snapshot(
    runner: CliRunner, seeded_home: Path
) -> None:
    payload = _invoke_json(runner, ["latest", "--format", "json"])
    _assert_snapshot("latest", payload, _leak_guards(seeded_home))


def test_status_json_snapshot(
    runner: CliRunner, seeded_home: Path
) -> None:
    payload = _invoke_json(runner, ["status", "--format", "json"])
    _assert_snapshot("status", payload, _leak_guards(seeded_home))


def test_show_json_snapshot(
    runner: CliRunner, seeded_home: Path
) -> None:
    # Pin to the failed_command_run so the snapshot covers both failures and a
    # rich, non-trivial run row.
    payload = _invoke_json(
        runner,
        ["show", "run_20260101_000001_bbbbbb", "--format", "json"],
    )
    _assert_snapshot("show", payload, _leak_guards(seeded_home))


def test_failures_json_snapshot(
    runner: CliRunner, seeded_home: Path
) -> None:
    # Fixtures are dated 2026-01-01; use a wide --since-days window so the
    # snapshot stays valid regardless of system clock relative to fixtures.
    payload = _invoke_json(
        runner, ["failures", "--since-days", "36500", "--format", "json"]
    )
    _assert_snapshot("failures", payload, _leak_guards(seeded_home))


def test_risks_json_snapshot(
    runner: CliRunner, seeded_home: Path
) -> None:
    payload = _invoke_json(
        runner, ["risks", "--since-days", "36500", "--format", "json"]
    )
    _assert_snapshot("risks", payload, _leak_guards(seeded_home))


def test_no_absolute_paths_in_full_scan_schema_invalid_rows(
    runner: CliRunner, seeded_home: Path, tmp_path: Path
) -> None:
    """Schema-invalid rows from full_scan_runs MUST NOT leak ``_source_dir``.

    Seeds a malformed run directory (run.json missing required fields), then
    asserts the absolute path does not appear in ``status --format json`` and
    the row carries ``schema_invalid: true`` instead of ``_source_dir``.
    """
    runs_root = seeded_home / "runs" / "ws_0000000000000099"
    broken = runs_root / "run_20260101_000099_bad000"
    broken.mkdir(parents=True)
    # run.json missing required ``workspace_id``/``started_at`` etc.
    (broken / "run.json").write_text(
        json.dumps({"schema": "agentlens.run.v1", "run_id": "broken"}),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["status", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    rows = [r for r in payload if r.get("run_id") == "run_20260101_000099_bad000"]
    assert rows, "schema-invalid row missing from status JSON"
    row = rows[0]
    assert row.get("schema_invalid") is True
    assert "_source_dir" not in row
    text = json.dumps(payload)
    assert str(broken) not in text
    assert str(seeded_home) not in text
