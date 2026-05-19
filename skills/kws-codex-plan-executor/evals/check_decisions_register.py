#!/usr/bin/env python3
"""Deterministic checks for decisions register updates and rendering."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "update_decisions_register.py"
    failures: list[str] = []
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="codex-decisions-") as temp:
        root = Path(temp)
        state = root / "state.json"
        render = root / "DECISIONS.md"
        state.write_text(json.dumps({"schema_version": "1", "decisions_register": []}) + "\n", encoding="utf-8")

        first = run(
            [
                sys.executable,
                str(script),
                "append",
                "--state",
                str(state),
                "--task",
                "task_2",
                "--decision",
                "Use parser-level spec refs instead of prompt regex matching.",
                "--files",
                "scripts/parse_plan.py,scripts/build_task_packet.py",
                "--render",
                str(render),
            ]
        )
        data = load(state)
        checks["append_first_decision"] = (
            first.returncode == 0
            and len(data.get("decisions_register", [])) == 1
            and data["decisions_register"][0]["id"] == "dec_0001"
            and data["decisions_register"][0]["files"] == [
                "scripts/parse_plan.py",
                "scripts/build_task_packet.py",
            ]
        )
        if not checks["append_first_decision"]:
            failures.append("append should create dec_0001 with parsed files")

        second = run(
            [
                sys.executable,
                str(script),
                "append",
                "--state",
                str(state),
                "--task",
                "task_3",
                "--decision",
                "Build packets from manifest ranges.",
                "--files",
                "scripts/build_task_packet.py",
                "--render",
                str(render),
            ]
        )
        data = load(state)
        checks["append_second_decision"] = (
            second.returncode == 0
            and [item["id"] for item in data.get("decisions_register", [])] == ["dec_0001", "dec_0002"]
        )
        if not checks["append_second_decision"]:
            failures.append("second append should create dec_0002")

        supersede = run(
            [
                sys.executable,
                str(script),
                "supersede",
                "--state",
                str(state),
                "--decision-id",
                "dec_0001",
                "--by-task",
                "task_5",
                "--reason",
                "Task packets now own the mapping.",
                "--render",
                str(render),
            ]
        )
        data = load(state)
        rendered = render.read_text(encoding="utf-8") if render.is_file() else ""
        decisions = data.get("decisions_register", [])
        checks["supersede_prior_decision"] = (
            supersede.returncode == 0
            and len(decisions) == 3
            and decisions[0]["superseded_by"] == "dec_0003"
            and decisions[2]["supersedes"] == "dec_0001"
        )
        if not checks["supersede_prior_decision"]:
            failures.append("supersede should mark prior decision and append a replacement decision")

        active_pos = rendered.find("dec_0002")
        superseded_heading_pos = rendered.find("## Superseded")
        old_pos = rendered.find("dec_0001")
        checks["render_active_first"] = (
            "# Decisions register" in rendered
            and active_pos != -1
            and superseded_heading_pos != -1
            and old_pos > superseded_heading_pos > active_pos
        )
        if not checks["render_active_first"]:
            failures.append("render should list active decisions first and superseded decisions separately")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
