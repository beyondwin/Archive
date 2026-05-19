#!/usr/bin/env python3
"""Deterministic checks for compact task packet generation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def write_json(path: Path, payload: dict | list) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_packet(root: Path, plan: dict, spec_text: str, manifest: dict, task_id: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_task_packet.py"
    plan_json = root / "plan.json"
    spec = root / "spec.md"
    manifest_path = root / "spec_manifest.json"
    decisions = root / "decisions_register.json"
    output = root / f"{task_id}.json"
    write_json(plan_json, plan)
    spec.write_text(spec_text, encoding="utf-8")
    write_json(manifest_path, manifest)
    write_json(decisions, [])
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--plan-json",
            str(plan_json),
            "--task-id",
            task_id,
            "--spec",
            str(spec),
            "--spec-manifest",
            str(manifest_path),
            "--decisions",
            str(decisions),
            "--output",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def plan_for(task: dict) -> dict:
    return {"plan": "plan.md", "mode": "interactive", "tasks": [task]}


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    spec_text = "# Feature\n\nfeature text\n# Auth Session\n\nauth session text\n"
    manifest = {
        "schema_version": "1",
        "spec_path": "spec.md",
        "fallback_policy": "full_spec_on_blocker",
        "sections": {
            "S1": {"id": "S1", "title": "Feature", "level": 1, "line_start": 1, "line_end": 3, "chars": 24, "sha256": "x"},
            "S2": {"id": "S2", "title": "Auth Session", "level": 1, "line_start": 4, "line_end": 6, "chars": 31, "sha256": "y"},
        },
        "section_order": ["S1", "S2"],
        "task_to_sections": {},
    }

    with tempfile.TemporaryDirectory(prefix="codex-task-packet-") as temp:
        root = Path(temp)
        explicit_task = {
            "id": "task_0",
            "title": "Add feature",
            "body": "Task body",
            "files": ["scripts/feature.py"],
            "depends_on": [],
            "spec_refs": ["S1"],
            "has_acceptance_criteria": True,
        }
        explicit_result, explicit = run_packet(root, plan_for(explicit_task), spec_text, manifest, "task_0")
        checks["explicit_refs_exact"] = (
            explicit_result.returncode == 0
            and explicit.get("spec", {}).get("section_ids") == ["S1"]
            and explicit.get("spec", {}).get("fallback_used") is False
            and "feature text" in explicit.get("spec", {}).get("text", "")
            and "auth session text" not in explicit.get("spec", {}).get("text", "")
        )
        if not checks["explicit_refs_exact"]:
            failures.append("explicit spec_refs should map to exact manifest sections")

        heuristic_task = {
            "id": "task_1",
            "title": "Auth wiring",
            "body": "Task body",
            "files": ["src/auth/session.py"],
            "depends_on": [],
            "spec_refs": [],
            "has_acceptance_criteria": False,
        }
        heuristic_result, heuristic = run_packet(root, plan_for(heuristic_task), spec_text, manifest, "task_1")
        checks["file_title_heuristic"] = (
            heuristic_result.returncode == 0
            and heuristic.get("spec", {}).get("section_ids") == ["S2"]
            and "auth session text" in heuristic.get("spec", {}).get("text", "")
        )
        if not checks["file_title_heuristic"]:
            failures.append("file path components should map src/auth/session.py to Auth Session")

        fallback_task = {
            "id": "task_2",
            "title": "Other",
            "body": "Task body",
            "files": ["src/billing/invoice.py"],
            "depends_on": [],
            "spec_refs": [],
            "has_acceptance_criteria": False,
        }
        fallback_result, fallback = run_packet(root, plan_for(fallback_task), spec_text, manifest, "task_2")
        checks["fallback_full_spec"] = (
            fallback_result.returncode == 0
            and fallback.get("spec", {}).get("section_ids") == ["*"]
            and fallback.get("spec", {}).get("fallback_used") is True
            and "feature text" in fallback.get("spec", {}).get("text", "")
            and "auth session text" in fallback.get("spec", {}).get("text", "")
        )
        if not checks["fallback_full_spec"]:
            failures.append("unmapped task should use full-spec fallback marker")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
