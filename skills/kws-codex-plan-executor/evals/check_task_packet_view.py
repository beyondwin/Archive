#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_task_packet_view.py"


def base_packet() -> dict:
    return {
        "schema_version": "1",
        "task_id": "task_0",
        "task_title": "Render packet",
        "task_body": "Build the human-readable packet renderer.",
        "files": ["skills/kws-codex-plan-executor/scripts/render_task_packet_view.py"],
        "acceptance": {
            "has_acceptance_criteria": True,
            "command": "python3 evals/check_task_packet_view.py",
            "source": "plan.acceptance",
            "honest_substitute_allowed": False,
        },
        "spec": {"mode": "slice", "section_ids": ["S1"], "fallback_used": False},
        "decisions_register": {"included": [{"id": "dec_1"}], "omitted_count": 0},
        "write_policy": {
            "allowed_write_globs": ["skills/kws-codex-plan-executor/scripts/render_task_packet_view.py"],
            "forbidden_write_globs": [".git/**", "graphify-out/**"],
        },
        "unit_manifest": {"forbidden_write_globs": [".git/**", "graphify-out/**"]},
        "context_budget": {"estimated_chars": 1200, "max_chars": 60000, "status": "green"},
    }


def run_renderer(root: Path, packet: dict) -> tuple[subprocess.CompletedProcess[str], str]:
    packet_path = root / "packet.json"
    output_path = root / "packet.md"
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--task-packet", str(packet_path), "--output", str(output_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    text = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
    return result, text


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="cpe-task-view-") as temp:
        root = Path(temp)
        result, text = run_renderer(root, base_packet())
        checks["renders_core_sections"] = (
            result.returncode == 0
            and "# Task task_0: Render packet" in text
            and "## 읽을 파일" in text
            and "## 작업" in text
            and "## AC" in text
            and "## 검증" in text
            and "## 금지사항" in text
            and "python3 evals/check_task_packet_view.py" in text
            and ".git/**" in text
            and "decisions included: 1" in text
        )
        if not checks["renders_core_sections"]:
            failures.append("renderer should produce all required human-view sections")

        missing_acceptance = base_packet()
        missing_acceptance["acceptance"]["command"] = None
        missing_acceptance["acceptance"]["honest_substitute_allowed"] = True
        result, text = run_renderer(root, missing_acceptance)
        checks["missing_acceptance_is_explicit"] = result.returncode == 0 and "honest substitute required" in text
        if not checks["missing_acceptance_is_explicit"]:
            failures.append("missing acceptance command should render an explicit honest-substitute marker")

        fallback = base_packet()
        fallback["spec"]["mode"] = "full"
        fallback["spec"]["section_ids"] = ["*"]
        fallback["spec"]["fallback_used"] = True
        fallback["spec"]["mapping"] = {"suggested_plan_patch": 'spec_refs: ["S3"]'}
        result, text = run_renderer(root, fallback)
        checks["full_spec_fallback_visible"] = result.returncode == 0 and "full spec fallback" in text
        if not checks["full_spec_fallback_visible"]:
            failures.append("full-spec fallback should be visible in the markdown view")
        checks["full_spec_fallback_view_has_patch"] = (
            result.returncode == 0
            and "Suggested plan patch" in text
            and text.count("full spec fallback") == 1
        )
        if not checks["full_spec_fallback_view_has_patch"]:
            failures.append("task packet view should show suggested plan patch without repeating full spec body")

        malformed = base_packet()
        del malformed["write_policy"]
        result, _ = run_renderer(root, malformed)
        checks["malformed_packet_fails"] = result.returncode != 0 and "write_policy" in result.stderr
        if not checks["malformed_packet_fails"]:
            failures.append("malformed packet should fail with the missing field name")

    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
