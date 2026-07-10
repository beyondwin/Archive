#!/usr/bin/env python3
from __future__ import annotations
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cpe_runtime.validation import validate_run
def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        run = Path(raw); (run / "run_manifest.json").write_text('{"schema_version":"2.27.0"}\n')
        assert validate_run(run).errors == ["unsupported_schema"]
    print('{"passed": true}'); return 0
if __name__ == "__main__": raise SystemExit(main())
