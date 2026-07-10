#!/usr/bin/env python3
"""Verify blocking public preflight is mutation-free."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def initialize_repo(repo: Path) -> None:
    repo.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "fixture@example.invalid"],
        ["git", "config", "user.name", "CPE Fixture"],
    ):
        result = run(command, repo)
        if result.returncode:
            raise RuntimeError(result.stderr)


def blocked_run(repo: Path, plan: Path, codex_home: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home)
    return run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "cpe.py"),
            "run",
            "--plan",
            str(plan),
            "--workspace",
            str(repo),
            "--mode",
            "interactive",
        ],
        SKILL_ROOT,
        env,
    )


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []
    header = (
        "# Fixture Plan\n\n"
        "> REQUIRED SUB-SKILL: subagent-driven-development or executing-plans\n\n"
    )
    with tempfile.TemporaryDirectory(prefix="cpe-readiness-") as temp:
        root = Path(temp)

        missing_repo = root / "missing-repo"
        initialize_repo(missing_repo)
        missing_plan = missing_repo / "plan.md"
        missing_plan.write_text(header + "## Task 1: Missing Files\n\nVerification:\n```bash\ntrue\n```\n", encoding="utf-8")
        run(["git", "add", "."], missing_repo)
        run(["git", "commit", "-qm", "fixture"], missing_repo)
        missing_home = root / "missing-home"
        missing = blocked_run(missing_repo, missing_plan, missing_home)
        checks["missing_files_blocks"] = missing.returncode == 2 and "preflight_blocked" in missing.stderr
        checks["missing_files_creates_no_roots"] = not (missing_home / "orchestrator").exists() and not (
            missing_home / "worktrees"
        ).exists()

        dangerous_repo = root / "dangerous-repo"
        initialize_repo(dangerous_repo)
        (dangerous_repo / "target.txt").write_text("target\n", encoding="utf-8")
        dangerous_plan = dangerous_repo / "plan.md"
        dangerous_plan.write_text(
            header
            + "## Task 1: Dangerous\n\n**Files:**\n- Modify: `target.txt`\n\nVerification:\n```bash\ngit push origin main\n```\n",
            encoding="utf-8",
        )
        run(["git", "add", "."], dangerous_repo)
        run(["git", "commit", "-qm", "fixture"], dangerous_repo)
        dangerous_home = root / "dangerous-home"
        dangerous = blocked_run(dangerous_repo, dangerous_plan, dangerous_home)
        checks["unsafe_command_blocks"] = dangerous.returncode == 2 and "operator_review_required" in dangerous.stderr
        checks["unsafe_command_creates_no_roots"] = not (dangerous_home / "orchestrator").exists() and not (
            dangerous_home / "worktrees"
        ).exists()

        dirty_repo = root / "dirty-repo"
        initialize_repo(dirty_repo)
        (dirty_repo / "target.txt").write_text("target\n", encoding="utf-8")
        dirty_plan = dirty_repo / "plan.md"
        dirty_plan.write_text(
            header
            + "## Task 1: Dirty\n\n**Files:**\n- Modify: `target.txt`\n\nVerification:\n```bash\ntrue\n```\n",
            encoding="utf-8",
        )
        run(["git", "add", "."], dirty_repo)
        run(["git", "commit", "-qm", "fixture"], dirty_repo)
        (dirty_repo / "target.txt").write_text("dirty\n", encoding="utf-8")
        dirty_home = root / "dirty-home"
        dirty = blocked_run(dirty_repo, dirty_plan, dirty_home)
        checks["dirty_claim_blocks"] = dirty.returncode == 2 and "related_dirty_scope" in dirty.stderr
        checks["dirty_claim_creates_no_roots"] = not (dirty_home / "orchestrator").exists() and not (
            dirty_home / "worktrees"
        ).exists()

    failures.extend(name for name, passed in checks.items() if not passed)
    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
