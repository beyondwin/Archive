#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from check_state_schema import base_state


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_state.py"


def run_validator(state: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="cpe-summary-") as temp:
        state_path = Path(temp) / "state.json"
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(state_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    valid = base_state()
    valid["tasks"]["task_0"]["next_task_summary"] = "Rendered task_0 view and validated summary storage."
    valid["context_health"]["hot_tail_summaries"] = [
        {"task_id": "task_0", "summary": "Rendered task_0 view and validated summary storage."}
    ]
    result = run_validator(valid)
    checks["one_line_summary_passes"] = result.returncode == 0
    if not checks["one_line_summary_passes"]:
        failures.append("valid one-line summaries should pass: " + (result.stderr or result.stdout))

    multiline = base_state()
    multiline["tasks"]["task_0"]["next_task_summary"] = "line one\nline two"
    result = run_validator(multiline)
    checks["multiline_summary_fails"] = result.returncode != 0 and "next_task_summary must be one line" in (
        result.stderr + result.stdout
    )
    if not checks["multiline_summary_fails"]:
        failures.append("multiline next_task_summary should fail")

    forbidden = base_state()
    forbidden["tasks"]["task_0"]["next_task_summary"] = "Wrote BEGIN FULL PROMPT into the summary."
    result = run_validator(forbidden)
    checks["forbidden_summary_pattern_fails"] = result.returncode != 0 and "forbidden durable-output pattern" in (
        result.stderr + result.stdout
    )
    if not checks["forbidden_summary_pattern_fails"]:
        failures.append("forbidden durable-output markers should fail in summaries")

    bad_hot_tail = base_state()
    bad_hot_tail["context_health"]["hot_tail_summaries"] = [{"task_id": "task_9", "summary": "Unknown task."}]
    result = run_validator(bad_hot_tail)
    checks["unknown_hot_tail_task_fails"] = result.returncode != 0 and "hot_tail_summaries" in (
        result.stderr + result.stdout
    )
    if not checks["unknown_hot_tail_task_fails"]:
        failures.append("hot-tail summary should reference a known task id")

    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
