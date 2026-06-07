#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_progress_ledger.py"


def run_update(state_path: Path, *args: str) -> dict:
    subprocess.run([sys.executable, str(SCRIPT), "--state", str(state_path), "--task-id", "task_0", *args], check=True)
    return json.loads(state_path.read_text(encoding="utf-8"))


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cpe-progress-") as temp:
        state_path = Path(temp) / "state.json"
        state_path.write_text(json.dumps({"schema_version": "1"}), encoding="utf-8")
        state = run_update(state_path, "--progress-made", "--next-action", "Run GREEN verification.")
        entry = state["progress_ledger"]["task_0"]
        checks["progress_resets_stall"] = entry["progress_made"] is True and entry["stall_count"] == 0
        if not checks["progress_resets_stall"]:
            failures.append("progress made should reset stall count")

        state = run_update(state_path, "--root-signature", "pytest:timeout", "--next-action", "Retry once.")
        state = run_update(state_path, "--root-signature", "pytest:timeout", "--next-action", "Retry once.")
        entry = state["progress_ledger"]["task_0"]
        checks["same_root_increments_stall"] = entry["stall_count"] == 2 and entry["last_root_signature"] == "pytest:timeout"
        if not checks["same_root_increments_stall"]:
            failures.append("same root failure should increment stall count")
        checks["threshold_sets_operator_need"] = entry["needs_operator"] is True
        if not checks["threshold_sets_operator_need"]:
            failures.append("stall threshold should mark needs_operator")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
