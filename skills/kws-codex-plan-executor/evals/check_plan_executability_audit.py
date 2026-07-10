#!/usr/bin/env python3
"""Exercise the public read-only plan compiler against approved plans."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from cpe_runtime.plan_compiler import compile_run


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def main() -> int:
    repo = Path(__file__).resolve().parents[3]
    plans = repo / "docs" / "superpowers" / "plans"
    specs = repo / "docs" / "superpowers" / "specs"
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="cpe-plan-compiler-") as temp:
        root = Path(temp)
        workspace = root / "workspace"
        codex_home = root / "codex-home"
        workspace.mkdir()
        run(["git", "init", "-q"], workspace)
        run(["git", "config", "user.email", "fixture@example.invalid"], workspace)
        run(["git", "config", "user.name", "CPE Fixture"], workspace)
        (workspace / "README.md").write_text("fixture\n", encoding="utf-8")
        run(["git", "add", "README.md"], workspace)
        run(["git", "commit", "-qm", "fixture"], workspace)
        old_codex_home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(codex_home)
        try:
            integrity = compile_run(
                plan=plans / "2026-07-10-cpe-v3-integrity-closure.md",
                spec=specs / "2026-07-10-cpe-v3-integrity-closure-design.md",
                docs=(),
                workspace=workspace,
                mode="interactive",
            )
            quality = compile_run(
                plan=plans / "2026-07-10-cpe-v3-quality-model-routing.md",
                spec=specs / "2026-07-10-cpe-v3-quality-model-routing-design.md",
                docs=(),
                workspace=workspace,
                mode="interactive",
            )
            explicit_plan = root / "explicit-plan.md"
            explicit_plan.write_text(
                "# Explicit CPE Plan\n\n"
                "```yaml waygent-task\n"
                "id: task_1\n"
                "title: Explicit contract\n"
                "dependencies: []\n"
                "file_claims:\n"
                "  - src/explicit.py\n"
                "acceptance: python3 -m py_compile src/explicit.py\n"
                "```\n",
                encoding="utf-8",
            )
            explicit = compile_run(
                plan=explicit_plan,
                spec=None,
                docs=(),
                workspace=workspace,
                mode="interactive",
            )
        finally:
            if old_codex_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = old_codex_home

        checks["integrity_plan_compiles"] = len(integrity.tasks) == 13
        checks["quality_plan_compiles"] = len(quality.tasks) == 12
        checks["explicit_cpe_plan_compiles"] = len(explicit.tasks) == 1
        checks["plan_source_is_first"] = integrity.sources[0].role == "plan"
        checks["compiled_contracts_present"] = all(
            task.get("execution_contract") and task.get("source_hashes") for task in integrity.tasks
        )
        try:
            integrity.source_head = "mutated"  # type: ignore[misc]
        except FrozenInstanceError:
            checks["compiled_run_is_immutable"] = True
        else:
            checks["compiled_run_is_immutable"] = False
        checks["compile_created_no_run_root"] = not (codex_home / "orchestrator").exists()
        checks["compile_created_no_worktree_root"] = not (codex_home / "worktrees").exists()

    failures.extend(name for name, passed in checks.items() if not passed)
    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
