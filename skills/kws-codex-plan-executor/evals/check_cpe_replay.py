#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "normalize_cpe_run.py"


def finished_state(run_dir: Path) -> dict:
    return {
        "schema_version": "1",
        "run_id": "synthetic-run",
        "mode": "interactive",
        "run_dir": str(run_dir),
        "state_path": str(run_dir / "state.json"),
        "lifecycle_outcome": "finished",
        "completion_audit": {
            "passed": True,
            "prompt_to_artifact_checklist": ["implemented requested files"],
            "verification_evidence": ["python3 evals/check_task_packet.py"],
            "residual_risk": [
                {
                    "owner": "operator",
                    "class": "external_credentials",
                    "summary": "Deploy requires VM_PUBLIC_IP.",
                    "blocks_release": False,
                }
            ],
        },
        "run_quality": {
            "grade": "yellow",
            "score": 90,
            "open_followups": ["full_spec_fallback_present"],
            "context_quality": {"full_spec_fallback_count": 1},
            "verification_quality": {"completion_audit_passed": True},
        },
        "tasks": {"task_1": {"fallback_spec_used": True}},
        "dispatch_decisions": [
            {
                "task_id": "task_1",
                "decision": "local_fallback",
                "reason": "adaptive_policy_local_fast_path_small_scope",
            }
        ],
        "prompt_audit": {"passed": True, "dynamic_marker_violations": []},
        "graphify_audit": {"fresh": True, "errors": [], "warnings": []},
        "plan_executability_audit": {"grade": "yellow", "fixable_issue_count": 1, "blocking_issue_count": 0},
        "timestamps": {
            "started_at": "2026-07-01T00:00:00Z",
            "updated_at": "2026-07-01T00:01:00Z",
            "completed_at": "2026-07-01T00:01:00Z",
        },
    }


def run_replay(state_path: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--state", str(state_path), *extra],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}
    return result, data


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-replay-") as temp:
        run_dir = Path(temp) / "run"
        run_dir.mkdir()
        state_path = run_dir / "state.json"
        state = finished_state(run_dir)
        state_path.write_text(json.dumps(state), encoding="utf-8")

        result, replay = run_replay(state_path)
        checks["finished_yellow_replay_normalizes"] = (
            result.returncode == 0
            and replay.get("completion_passed") is True
            and replay.get("run_quality_grade") == "yellow"
            and replay.get("full_spec_fallback_count") == 1
            and replay.get("residual_risk_classes") == ["external_credentials"]
            and replay.get("plan_executability", {}).get("fixable_issue_count") == 1
        )
        if not checks["finished_yellow_replay_normalizes"]:
            failures.append("finished yellow state should normalize into stable replay fields")

        final_output = run_dir / "final.md"
        final_output.write_text("token sk-test and /Users/example and BEGIN FULL PROMPT", encoding="utf-8")
        result, replay = run_replay(state_path, "--final-output", str(final_output))
        checks["forbidden_patterns_detected"] = (
            result.returncode == 0
            and replay.get("forbidden_patterns_found") == ["sk-", "absolute_home_path", "full_prompt"]
        )
        if not checks["forbidden_patterns_detected"]:
            failures.append("normalized replay should flag forbidden durable output patterns")

        output_path = run_dir / "replay.json"
        result, replay = run_replay(state_path, "--output", str(output_path))
        checks["output_file_matches_stdout"] = (
            result.returncode == 0
            and output_path.is_file()
            and json.loads(output_path.read_text(encoding="utf-8")) == replay
        )
        if not checks["output_file_matches_stdout"]:
            failures.append("--output should write the same deterministic replay payload as stdout")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
