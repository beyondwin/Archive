"""Shared test helpers for AgentLens tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def copy_fixture_as_run_id(
    fixtures: Path, fixture_name: str, runs_root: Path
) -> tuple[str, str]:
    """Copy a fixture under runs/<workspace_id>/<run_id> from run.json."""
    src = fixtures / fixture_name
    run_doc = json.loads((src / "run.json").read_text(encoding="utf-8"))
    run_id = run_doc["run_id"]
    workspace_id = run_doc["workspace_id"]
    workspace_dir = runs_root / workspace_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    dest = workspace_dir / run_id
    shutil.copytree(src, dest)
    expected_eval = dest / "expected_eval.json"
    if expected_eval.is_file() and not (dest / "eval.json").exists():
        shutil.copyfile(expected_eval, dest / "eval.json")
    return workspace_id, run_id
