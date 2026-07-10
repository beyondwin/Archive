#!/usr/bin/env python3
from __future__ import annotations
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.reconciliation import reconcile
from cpe_runtime.manifest import create_manifest, write_manifest
def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); plan = root / "plan.md"; pricing = root / "pricing.json"
        plan.write_text("# plan\n", encoding="utf-8"); pricing.write_text("{}\n", encoding="utf-8")
        worktree = root / "worktree"; worktree.mkdir()
        run = root / "run"
        manifest = create_manifest("x", "interactive", root, worktree, plan, None, [{"id": "T1", "acceptance_command": "true"}], pricing)
        write_manifest(run / "run_manifest.json", manifest)
        (run / "events.jsonl").write_text("", encoding="utf-8")
        (run / "state.json").write_text("{}\n", encoding="utf-8")
        report = reconcile(run)
        assert report.classification == "blocking_drift"
        assert any(item["code"] == "snapshot_replay_mismatch" for item in report.findings)
    print('{"passed": true}'); return 0
if __name__ == "__main__": raise SystemExit(main())
