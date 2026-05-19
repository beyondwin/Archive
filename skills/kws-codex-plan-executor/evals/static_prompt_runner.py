#!/usr/bin/env python3
"""Deterministic prompt/handoff fixture runner for local evals."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-log", required=True)
    args = parser.parse_args()

    fixture = yaml.safe_load(Path(args.fixture).read_text(encoding="utf-8")) or {}
    mode = fixture.get("mode", "prompt")
    lines = [
        "Model: gpt-5.5 high",
        "Plan: plan.md",
        "State: ~/.codex/orchestrator/<run_id>/state.json",
        "context_health: record status, next_action, and handoff_ready before exit",
        "Use scripts/validate_state.py before completion.",
    ]
    if mode == "handoff":
        lines.insert(0, "HANDOFF CHECKPOINT")
    text = "```text\n" + "\n".join(lines) + "\n```\n"
    Path(args.output).write_text(text, encoding="utf-8")
    Path(args.run_log).write_text(
        '{"type":"item.completed","item":{"type":"agent_message","text":"Deterministic prompt fixture exported."}}\n',
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
