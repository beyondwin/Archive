#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_prompt_cache.py"


def run_audit(root: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = root / "audit.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--skill-root", str(root), "--output", str(output)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def write_template(root: Path, text: str) -> None:
    path = root / "templates" / "fresh-session-prompt.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    refs = root / "references"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "verifier-prompt.md").write_text(text, encoding="utf-8")


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-cache-audit-") as temp:
        root = Path(temp)
        write_template(root, "plain prompt without markers\n")
        result, data = run_audit(root)
        checks["missing_markers_fail"] = result.returncode != 0 and data.get("passed") is False
        if not checks["missing_markers_fail"]:
            failures.append("templates without cache markers should fail")

    with tempfile.TemporaryDirectory(prefix="cpe-cache-audit-") as temp:
        root = Path(temp)
        write_template(
            root,
            "<!-- CPE_CACHE_STABLE_PREFIX_START -->\n"
            "Stable instructions {{STATE_PATH}}\n"
            "<!-- CPE_CACHE_STABLE_PREFIX_END -->\n"
            "<!-- CPE_CACHE_HOT_TAIL_START -->\n"
            "Dynamic tail\n",
        )
        result, data = run_audit(root)
        violations = json.dumps(data.get("dynamic_marker_violations", []), ensure_ascii=False)
        checks["dynamic_placeholder_in_stable_prefix_fails"] = (
            result.returncode != 0 and "{{STATE_PATH}}" in violations
        )
        if not checks["dynamic_placeholder_in_stable_prefix_fails"]:
            failures.append("dynamic placeholder inside stable prefix should fail")

    with tempfile.TemporaryDirectory(prefix="cpe-cache-audit-") as temp:
        root = Path(temp)
        before = (
            "<!-- CPE_CACHE_STABLE_PREFIX_START -->\n"
            "Stable instructions\n"
            "<!-- CPE_CACHE_STABLE_PREFIX_END -->\n"
            "<!-- CPE_CACHE_HOT_TAIL_START -->\n"
            "Task one\n"
        )
        write_template(root, before)
        result_one, first = run_audit(root)
        write_template(root, before.replace("Task one", "Task two with a different run id"))
        result_two, second = run_audit(root)
        name = "templates/fresh-session-prompt.txt"
        checks["hot_tail_change_keeps_stable_hash"] = (
            result_one.returncode == 0
            and result_two.returncode == 0
            and first["stable_prefix_hashes"][name] == second["stable_prefix_hashes"][name]
        )
        if not checks["hot_tail_change_keeps_stable_hash"]:
            failures.append("hot-tail-only changes should not alter stable-prefix hash")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
