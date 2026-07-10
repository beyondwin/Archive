#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path
def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        out = Path(raw) / "plan.json"; result = subprocess.run([sys.executable, str(Path(__file__).with_name("live_model_migration.py")), "--dry-run", "--budget-usd", "50", "--output", str(out)], text=True, capture_output=True); payload = json.loads(out.read_text())
        assert result.returncode == 0 and payload["treatment_count"] == 4 and payload["case_count"] == 8
    print('{"passed": true}'); return 0
if __name__ == "__main__": raise SystemExit(main())
