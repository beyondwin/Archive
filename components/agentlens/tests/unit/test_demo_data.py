"""Tests for bundled demo data."""
from __future__ import annotations

import json

from agentlens.demo_data import demo_root


def test_demo_root_exists():
    root = demo_root()
    assert root.is_dir()


def test_demo_root_contains_runs():
    root = demo_root()
    runs_dir = root / "runs"
    assert runs_dir.is_dir()
    ws_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
    assert ws_dirs
    has_failed_eval = False
    for ws in ws_dirs:
        for run in ws.iterdir():
            eval_path = run / "eval.json"
            if eval_path.is_file():
                eval_doc = json.loads(eval_path.read_text(encoding="utf-8"))
                if eval_doc.get("status") == "failed":
                    has_failed_eval = True
    assert has_failed_eval, "demo data should include at least one failed-eval run"
