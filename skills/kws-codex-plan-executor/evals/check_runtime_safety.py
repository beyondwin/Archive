#!/usr/bin/env python3
"""Behavioral regression checks for the CPE v3 merge blockers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from cpe_runtime.evidence import EvidenceError, EvidenceRef, put_json, verify_ref
from cpe_runtime.kernel import Kernel, Transition
from cpe_runtime.manifest import create_manifest, write_manifest
from cpe_runtime.model_policy import CORE_ROUTE, attest_launcher, launcher_argv
from cpe_runtime.validation import validate_run
from cpe_runtime.worker import Worker, WorkerRequest


def raises(expected: type[BaseException], fn) -> None:
    try:
        fn()
    except expected:
        return
    raise AssertionError(f"expected {expected.__name__}")


def make_run(root: Path) -> tuple[Path, Path]:
    workspace = root / "repo"
    worktree = root / "worktree"
    workspace.mkdir()
    worktree.mkdir()
    plan = root / "plan.md"
    spec = root / "spec.md"
    pricing = root / "pricing.json"
    plan.write_text("# Plan\n", encoding="utf-8")
    spec.write_text("# Spec\n", encoding="utf-8")
    pricing.write_text('{"models":{}}\n', encoding="utf-8")
    task = {
        "id": "T1",
        "title": "One",
        "dependencies": [],
        "file_claims": ["result.txt"],
        "spec_refs": ["S1"],
        "acceptance_command": "test -f result.txt",
    }
    run_dir = root / "run"
    manifest = create_manifest("fixture", "interactive", workspace, worktree, plan, spec, [task], pricing)
    write_manifest(run_dir / "run_manifest.json", manifest)
    return run_dir, worktree


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        run_dir, worktree = make_run(root)

        for kind in ("../escape", "/tmp/escape", "bad/name", ""):
            raises(EvidenceError, lambda kind=kind: put_json(run_dir, kind, {"x": 1}))

        outside = root / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        link_dir = run_dir / "artifacts" / "evidence" / "verification"
        link_dir.mkdir(parents=True)
        link = link_dir / "linked.json"
        link.symlink_to(outside)
        ref = EvidenceRef("verification", link.relative_to(run_dir).as_posix(), "0" * 64)
        assert verify_ref(run_dir, ref) == ["evidence path escapes run root"]

        argv = launcher_argv(
            CORE_ROUTE,
            worktree,
            sandbox="workspace-write",
            output_schema=SCRIPT_DIR.parent / "templates" / "worker-result-schema.json",
            output_last_message=root / "last.json",
        )
        assert "--output-schema" in argv and "--output-last-message" in argv
        untrusted = attest_launcher(CORE_ROUTE, argv)
        assert untrusted["verified"] is False
        assert untrusted["actual_model"] is None

        request = WorkerRequest("T1.implementation.1", "implementation", "work", worktree, False, True)
        missing_metadata = Worker(provider=lambda _request, _argv: {
            "status": "completed", "summary": "x", "changed_files": [], "findings": [],
            "evidence_refs": [], "missing_evidence": [], "verification": [],
        }).run(request)
        assert missing_metadata.attestation["verified"] is False

        kernel = Kernel(run_dir)
        raises(ValueError, lambda: kernel.transition(Transition("unknown.event", {})))
        raises(
            ValueError,
            lambda: kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"})),
        )
        kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
        raises(
            ValueError,
            lambda: kernel.transition(
                Transition("task.status_changed", {"from": "pending", "to": "ready"}, task_id="UNKNOWN")
            ),
        )
        raises(
            ValueError,
            lambda: kernel.transition(Transition("run.status_changed", {"from": "running", "to": "completed"})),
        )
        (root / "plan.md").write_text("# drifted plan\n", encoding="utf-8")
        raises(
            ValueError,
            lambda: kernel.transition(Transition("run.status_changed", {"from": "running", "to": "failed"})),
        )

        report = validate_run(run_dir)
        assert report.passed is False
        assert "task_incomplete" in report.errors
        assert "completion_gate_failed" in report.errors

        validate_cli = SCRIPT_DIR / "validate_state.py"
        result = subprocess.run(
            [sys.executable, str(validate_cli), str(run_dir)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "task_incomplete" in result.stdout

        missing_resume = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "cpe.py"), "resume", "--run-id", "does-not-exist"],
            env={**os.environ, "CODEX_HOME": str(root / "home")},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert missing_resume.returncode != 0

    print(json.dumps({"passed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
