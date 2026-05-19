#!/usr/bin/env python3
"""Deterministic checks for Markdown spec manifest generation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run_manifest(script: Path, spec_text: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    with tempfile.TemporaryDirectory(prefix="codex-spec-manifest-") as temp:
        root = Path(temp)
        spec = root / "spec.md"
        output = root / "manifest.json"
        spec.write_text(spec_text, encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                str(spec),
                "--output",
                str(output),
                "--fallback-policy",
                "full_spec_on_blocker",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
        return result, data


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_spec_manifest.py"
    failures: list[str] = []
    checks: dict[str, bool] = {}

    plain_result, plain = run_manifest(script, "plain spec body\nsecond line\n")
    checks["no_heading_document_section"] = (
        plain_result.returncode == 0
        and plain.get("section_order") == ["S0"]
        and plain.get("sections", {}).get("S0", {}).get("title") == "document"
        and plain.get("sections", {}).get("S0", {}).get("level") == 0
    )
    if not checks["no_heading_document_section"]:
        failures.append("no-heading spec should create one S0 document section")

    heading_text = "# Feature\n\nintro\n## Child\n\nchild\n# Next\n"
    heading_result, heading = run_manifest(script, heading_text)
    sections = heading.get("sections", {})
    checks["heading_ids_stable"] = heading_result.returncode == 0 and heading.get("section_order") == [
        "S1",
        "S1.1",
        "S2",
    ]
    if not checks["heading_ids_stable"]:
        failures.append("heading hierarchy should produce S1, S1.1, S2")

    s1_text = "# Feature\n\nintro\n## Child\n\nchild\n"
    checks["section_metadata_complete"] = (
        sections.get("S1", {}).get("title") == "Feature"
        and sections.get("S1", {}).get("level") == 1
        and sections.get("S1", {}).get("line_start") == 1
        and sections.get("S1", {}).get("line_end") == 6
        and sections.get("S1", {}).get("chars") == len(s1_text)
        and sections.get("S1", {}).get("sha256") == sha256(s1_text)
    )
    if not checks["section_metadata_complete"]:
        failures.append("sections must record title, level, line range, chars, and sha256")

    fenced_result, fenced = run_manifest(script, "```md\n# Hidden\n```\n# Visible\n")
    checks["fenced_headings_ignored"] = (
        fenced_result.returncode == 0
        and fenced.get("section_order") == ["S1"]
        and fenced.get("sections", {}).get("S1", {}).get("title") == "Visible"
    )
    if not checks["fenced_headings_ignored"]:
        failures.append("headings inside fenced code blocks should be ignored")

    checks["task_to_sections_empty"] = heading_result.returncode == 0 and heading.get("task_to_sections") == {}
    if not checks["task_to_sections_empty"]:
        failures.append("new manifests should start with task_to_sections={}")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
