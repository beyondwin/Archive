#!/usr/bin/env python3
from __future__ import annotations
import json, tempfile, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.projector import RETRY_PHASE_STATES, TASK_TRANSITIONS, initial_state
from cpe_runtime.validation import validate_run
def main() -> int:
    state = initial_state({"run_id": "schema-fixture", "task_graph": []})
    assert state["worktree_revision"] == 0
    assert state["worktree_patch_sha256"] is None
    assert state["active_blockers"] == [] and state["blocker_history"] == []
    assert state["verdicts"] == [] and state["retry_queue"] == []
    assert "ready" not in TASK_TRANSITIONS["blocked"]
    assert RETRY_PHASE_STATES["acceptance"] == "verifying"
    with tempfile.TemporaryDirectory() as raw:
        run = Path(raw); (run / "run_manifest.json").write_text('{"schema_version":"2.27.0"}\n')
        before = (run / "run_manifest.json").read_bytes(); report = validate_run(run)
        assert report.classification == "unsupported_schema" and (run / "run_manifest.json").read_bytes() == before
    print('{"passed": true}'); return 0
if __name__ == "__main__": raise SystemExit(main())
