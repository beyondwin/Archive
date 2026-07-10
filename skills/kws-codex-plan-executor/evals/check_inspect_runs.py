#!/usr/bin/env python3
from __future__ import annotations
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.inspection import inspect_run, inspect_recent
def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); run = root / "orchestrator" / "r"; run.mkdir(parents=True); (run / "run_manifest.json").write_text('{"schema_version":"2.27.0"}\n')
        assert inspect_run(run)["classification"] == "unsupported_schema"
        assert inspect_recent(root, 5)["unsupported_schema_count"] == 1
    print('{"passed": true}'); return 0
if __name__ == "__main__": raise SystemExit(main())
