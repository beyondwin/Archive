#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.kernel import RunKernel, Transition
from cpe_runtime.manifest import create_manifest
from cpe_runtime.packets import build_packet
from cpe_runtime.reconciliation import reconcile


def fixture(root: Path) -> tuple[Path, RunKernel]:
    run_id = "reconcile-fixture"
    plan = root / "plan.md"
    pricing = root / "pricing.json"
    plan.write_text("# plan\n", encoding="utf-8")
    pricing.write_text("{}\n", encoding="utf-8")
    worktree = root / "worktree"
    worktree.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "cpe@example.invalid"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.name", "CPE Fixture"], cwd=worktree, check=True)
    (worktree / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "baseline.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=worktree, check=True)
    subprocess.run(["git", "checkout", "-qb", f"codex/{run_id}"], cwd=worktree, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
    task = {"id": "T1", "title": "reconcile", "dependencies": [], "file_claims": ["owned.txt"], "acceptance_command": "true"}
    manifest = create_manifest(run_id, "interactive", root, worktree, plan, None, [task], pricing, source_head=head)
    draft = build_packet(SimpleNamespace(sources=(), spec_manifest=None), task)
    run_dir = root / "run"
    return run_dir, RunKernel.initialize(run_dir, manifest, [draft])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-reconcile-") as raw:
        run_dir, kernel = fixture(Path(raw))
        kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
        kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
        report = reconcile(run_dir)
        assert report.classification == "clean_incomplete", report
        assert not report.findings, report
        adapter = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_state.py"
        checked = subprocess.run(
            [sys.executable, str(adapter), "--run-dir", str(run_dir), "--check"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert checked.returncode == 0, checked
        assert json.loads(checked.stdout)["classification"] == "clean_incomplete", checked.stdout

        (run_dir / "state.json").write_text("{}\n", encoding="utf-8")
        drift = reconcile(run_dir)
        assert drift.classification == "repairable", drift
        assert [item["code"] for item in drift.findings] == ["snapshot_replay_mismatch"], drift

        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["schema_version"] = "2"
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        legacy = reconcile(run_dir)
        assert legacy.classification == "blocking_drift", legacy
        assert legacy.findings[0]["code"] == "unsupported_schema", legacy
        rejected = subprocess.run(
            [sys.executable, str(adapter), "--state", str(run_dir / "state.json"), "--check"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert rejected.returncode == 2, rejected
        assert json.loads(rejected.stdout)["classification"] == "blocking_drift", rejected.stdout

    print('{"passed": true, "checks": {"clean_incomplete": true, "repairable_snapshot": true, "run_dir_adapter": true, "state_alias_v2_blocked": true}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
