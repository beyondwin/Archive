#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "append_trajectory_event.py"


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cpe-trajectory-") as temp:
        root = Path(temp)
        path = root / "trajectory.jsonl"
        for event in ("task_started", "verification_passed"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--trajectory",
                    str(path),
                    "--event",
                    event,
                    "--task-id",
                    "task_0",
                    "--state-ref",
                    "~/.codex/orchestrator/run/state.json",
                    "--summary",
                    f"{event} for /Users/example/secret",
                    "--evidence-ref",
                    "/Users/example/.codex/orchestrator/run/obs.json",
                    "--context-status",
                    "green",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0:
                failures.append("append_trajectory_event failed: " + result.stderr)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        checks["jsonl_valid_and_seq_increments"] = [row["seq"] for row in rows] == [1, 2]
        if not checks["jsonl_valid_and_seq_increments"]:
            failures.append("trajectory seq should increment")
        checks["required_fields_present"] = all(
            key in rows[0]
            for key in ("schema_version", "seq", "event", "at", "task_id", "state_ref", "summary", "evidence_refs", "context_budget")
        )
        if not checks["required_fields_present"]:
            failures.append("trajectory events should include required fields")
        text = path.read_text(encoding="utf-8")
        checks["home_paths_redacted"] = "/Users/example" not in text and "~/" in text
        if not checks["home_paths_redacted"]:
            failures.append("trajectory should redact home paths")
        checks["raw_prompt_absent"] = "raw_prompt" not in rows[0]
        if not checks["raw_prompt_absent"]:
            failures.append("trajectory should not include raw prompts")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
