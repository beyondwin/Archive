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
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.plan_compiler import CompileBlocked, compile_run


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


def compile_block_category(repo: Path, plan: Path) -> str | None:
    try:
        compile_run(plan=plan, spec=None, docs=(), workspace=repo, mode="interactive")
    except CompileBlocked as exc:
        return exc.category
    return None


def public_blocked(result: subprocess.CompletedProcess[str], marker: str) -> bool:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return (
        result.returncode != 0
        and payload.get("status") == "blocked"
        and marker in (result.stdout + result.stderr)
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
        checks["missing_files_blocks"] = public_blocked(missing, "preflight")
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
        checks["unsafe_command_blocks"] = public_blocked(dangerous, "requires operator review")
        checks["unsafe_command_creates_no_roots"] = not (dangerous_home / "orchestrator").exists() and not (
            dangerous_home / "worktrees"
        ).exists()

        for label, command in (
            ("newline_git_push", "echo safe\ngit push origin main"),
            ("newline_rm_rf", "echo safe\nrm -rf /tmp/cpe-readiness-fixture"),
        ):
            command_repo = root / f"{label}-repo"
            initialize_repo(command_repo)
            (command_repo / "target.txt").write_text("target\n", encoding="utf-8")
            command_plan = command_repo / "plan.md"
            command_plan.write_text(
                header
                + f"## Task 1: {label}\n\n**Files:**\n- Modify: `target.txt`\n\nVerification:\n```bash\n{command}\n```\n",
                encoding="utf-8",
            )
            run(["git", "add", "."], command_repo)
            run(["git", "commit", "-qm", "fixture"], command_repo)
            checks[f"{label}_blocks"] = compile_block_category(command_repo, command_plan) == "operator_review_required"

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
        checks["dirty_claim_blocks"] = public_blocked(dirty, "claimed task paths already contain source changes")
        checks["dirty_claim_creates_no_roots"] = not (dirty_home / "orchestrator").exists() and not (
            dirty_home / "worktrees"
        ).exists()

        spaced_repo = root / "spaced-repo"
        initialize_repo(spaced_repo)
        spaced_target = spaced_repo / "docs" / "my file.md"
        spaced_target.parent.mkdir()
        spaced_target.write_text("clean\n", encoding="utf-8")
        spaced_plan = spaced_repo / "plan.md"
        spaced_plan.write_text(
            header
            + "## Task 1: Spaced Path\n\n**Files:**\n- Modify: `docs/my file.md`\n\nVerification:\n```bash\ntrue\n```\n",
            encoding="utf-8",
        )
        run(["git", "add", "."], spaced_repo)
        run(["git", "commit", "-qm", "fixture"], spaced_repo)
        spaced_target.write_text("dirty\n", encoding="utf-8")
        checks["dirty_spaced_claim_blocks"] = compile_block_category(spaced_repo, spaced_plan) == "related_dirty_scope"

        rename_repo = root / "rename-repo"
        initialize_repo(rename_repo)
        rename_docs = rename_repo / "docs"
        rename_docs.mkdir()
        old_target = rename_docs / "old file.md"
        old_target.write_text("clean\n", encoding="utf-8")
        rename_plan = rename_repo / "plan.md"
        rename_plan.write_text(
            header
            + "## Task 1: Renamed Path\n\n**Files:**\n- Modify: `docs/new file.md`\n\nVerification:\n```bash\ntrue\n```\n",
            encoding="utf-8",
        )
        run(["git", "add", "."], rename_repo)
        run(["git", "commit", "-qm", "fixture"], rename_repo)
        run(["git", "mv", "docs/old file.md", "docs/new file.md"], rename_repo)
        checks["dirty_rename_claim_blocks"] = compile_block_category(rename_repo, rename_plan) == "related_dirty_scope"

    failures.extend(name for name, passed in checks.items() if not passed)
    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
