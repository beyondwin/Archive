from __future__ import annotations

import sys
from pathlib import Path

from agentrunway.detach import build_detached_argv
from agentrunway.invocation import parse_run_args


def test_run_parser_accepts_hidden_run_id() -> None:
    args = parse_run_args(["run", "--plan", "plan.md", "--run-id", "fixed-run"])

    assert args.run_id == "fixed-run"


def test_build_detached_argv_removes_detach_and_absoluteizes_plan_and_spec(tmp_path: Path) -> None:
    invocation_cwd = tmp_path / "operator"
    invocation_cwd.mkdir()
    original = [
        "run",
        "--plan",
        "plans/plan.md",
        "--spec",
        "specs/spec.md",
        "--detach",
        "--adapter",
        "codex",
    ]

    argv = build_detached_argv(
        executable=sys.executable,
        script=Path("skills/agent-runway/scripts/agentrunway.py"),
        original_argv=original,
        invocation_cwd=invocation_cwd,
        run_id="fixed-run",
    )

    assert "--detach" not in argv
    assert argv[argv.index("--plan") + 1] == str((invocation_cwd / "plans" / "plan.md").resolve())
    assert argv[argv.index("--spec") + 1] == str((invocation_cwd / "specs" / "spec.md").resolve())
    assert argv[argv.index("--run-id") + 1] == "fixed-run"
