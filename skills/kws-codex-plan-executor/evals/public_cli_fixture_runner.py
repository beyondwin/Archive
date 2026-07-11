#!/usr/bin/env python3
"""Run stimulus-only cases through the public CPE command."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parent
SKILL_DIR = EVAL_DIR.parent
CASES = EVAL_DIR / "public-cli-cases.json"
CPE = SKILL_DIR / "scripts" / "cpe.py"
VALIDATE = SKILL_DIR / "scripts" / "validate_state.py"
RECONCILE = SKILL_DIR / "scripts" / "reconcile_state.py"
REPAIR = SKILL_DIR / "scripts" / "repair_runs.py"


def _run(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _git(repo: Path, *args: str) -> str:
    result = _run(["git", *args], repo)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def _changed(repo: Path) -> list[str]:
    return sorted(line[3:] for line in _git(repo, "status", "--short", "--untracked-files=all").splitlines() if len(line) > 3)


def _diffs(repo: Path) -> dict[str, object]:
    return {
        "tracked_diff": _git(repo, "diff", "--binary"),
        "cached_diff": _git(repo, "diff", "--cached", "--binary"),
        "untracked_files": sorted(
            line for line in _git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if line
        ),
    }


def _case(case: dict[str, object], root: Path) -> dict[str, object]:
    case_id = str(case["id"])
    repo = root / "repo"
    home = root / "codex-home"
    bin_dir = root / "bin"
    repo.mkdir(parents=True)
    home.mkdir()
    bin_dir.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "CPE Fixture")
    plan = repo / "plan.md"
    plan.write_text(str(case["plan"]), encoding="utf-8")
    (repo / "README.md").write_text("public CPE fixture\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")
    fake_case = root / "fake-case.json"
    fake_case.write_text(json.dumps(case.get("fake") or {}, sort_keys=True) + "\n", encoding="utf-8")
    fake_binary = bin_dir / "codex"
    shutil.copyfile(EVAL_DIR / "fake_codex.py", fake_binary)
    fake_binary.chmod(0o755)
    env = {
        **os.environ,
        "CODEX_HOME": str(home),
        "CPE_FAKE_CASE_FILE": str(fake_case),
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
    }
    command = str(case["command"])
    setup_argv: list[str] | None = None
    setup_result: subprocess.CompletedProcess[str] | None = None
    setup_payload: dict[str, object] = {}
    run_id = ""
    state_path: str | None = None
    if command in {"resume", "validate", "reconcile", "repair"}:
        setup_argv = [
            sys.executable, str(CPE), "run", "--plan", str(plan),
            "--workspace", str(repo), "--mode", str(case.get("setup_mode") or "interactive"),
        ]
        setup_result = _run(setup_argv, SKILL_DIR, env)
        try:
            setup_payload = json.loads(setup_result.stdout)
        except json.JSONDecodeError:
            setup_payload = {}
        run_id = str(setup_payload.get("run_id") or "")
        raw_state_path = setup_payload.get("state_path")
        state_path = str(raw_state_path) if isinstance(raw_state_path, str) else None
    if command == "run":
        argv = [
            sys.executable, str(CPE), "run", "--plan", str(plan),
            "--workspace", str(repo), "--mode", str(case.get("mode") or "interactive"),
        ]
    elif command == "export":
        argv = [
            sys.executable, str(CPE), "export", "--plan", str(plan),
            "--workspace", str(repo), "--mode", str(case.get("mode") or "prompt"),
        ]
    elif command == "resume":
        argv = [sys.executable, str(CPE), "resume", "--run-id", run_id]
    elif command == "validate":
        argv = [sys.executable, str(VALIDATE), state_path or str(root / "missing-state.json")]
    elif command == "reconcile":
        argv = [sys.executable, str(RECONCILE), "--state", state_path or str(root / "missing-state.json"), "--check"]
    elif command == "repair":
        argv = [sys.executable, str(REPAIR), "--state", state_path or str(root / "missing-state.json"), "--dry-run"]
    else:
        raise ValueError(f"unsupported public case command: {command}")
    completed = _run(argv, SKILL_DIR, env)
    payload: dict[str, object] = {}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {}
    run_dirs = sorted((home / "orchestrator").glob("*")) if (home / "orchestrator").is_dir() else []
    run_id = str(payload.get("run_id") or run_id or (run_dirs[-1].name if run_dirs else ""))
    worktree = home / "worktrees" / run_id if run_id else None
    changed = _changed(worktree) if worktree and worktree.is_dir() else _changed(repo)
    diffs = _diffs(worktree) if worktree and worktree.is_dir() else _diffs(repo)
    success_labels = {
        "export": "exported",
        "validate": "validated",
        "reconcile": "reconciled",
        "repair": "repair_planned",
    }
    status = str(payload.get("status") or (success_labels.get(command) if completed.returncode == 0 else "unknown"))
    return {
        "id": case_id,
        "command": command,
        "argv": argv,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "status": status,
        "run_id": run_id or None,
        "state_path": payload.get("state_path") or state_path,
        "entrypoint": argv[1],
        "setup_argv": setup_argv,
        "setup_exit_code": setup_result.returncode if setup_result else None,
        "setup_status": setup_payload.get("status") if setup_result else None,
        "changed_files": changed,
        **diffs,
        "public_entrypoint_invoked": argv[1] in {str(CPE), str(VALIDATE), str(RECONCILE), str(REPAIR)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with open(CASES, encoding="utf-8") as handle:
        payload = json.load(handle)
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise SystemExit("public CLI cases are empty")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        return 0
    results: list[dict[str, object]] = []
    for case in cases:
        if not isinstance(case, dict):
            raise SystemExit("public CLI case is not an object")
        with tempfile.TemporaryDirectory(prefix=f"cpe-public-{case.get('id', 'case')}-") as raw:
            results.append(_case(case, Path(raw)))
    (output_dir / "results.json").write_text(json.dumps({"schema_version": "1", "results": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
