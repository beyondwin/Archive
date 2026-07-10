#!/usr/bin/env python3
from __future__ import annotations
import json, tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.worker import Worker, WorkerRequest
from cpe_runtime.scheduler import run_tasks
from cpe_runtime.model_policy import CORE_ROUTE
def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); (root / "run_manifest.json").write_text('{"schema_version":"3","run_id":"x"}\n')
        def provider(request, argv):
            assert argv[argv.index("--model") + 1] == CORE_ROUTE.model
            return {"status": "completed", "summary": request.attempt_id, "changed_files": [], "findings": [], "evidence_refs": [], "missing_evidence": [], "verification": []}
        worker = Worker(provider=provider)
        result = run_tasks([{"id": "T1"}, {"id": "T2"}], worker, root)
        assert result["completed"] == ["T1", "T2"]
    print('{"passed": true}'); return 0
if __name__ == "__main__": raise SystemExit(main())
