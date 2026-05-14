#!/usr/bin/env python3
"""Deterministic checks for state.tasks.<id>.method_audit."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any


EXECUTABLE_REQUIRED = ["test-driven-development", "verification-before-completion", "code-review-pass"]
DOCS_ONLY_REQUIRED = ["verification-before-completion"]


def _is_docs_only(task: dict[str, Any]) -> bool:
    files = task.get("files", [])
    files_test = task.get("files_test")
    if files_test == []:
        return True
    if files_test is None and files and all(f.endswith(".md") for f in files):
        return True
    return False


def _required_for(task: dict[str, Any]) -> list[str]:
    return DOCS_ONLY_REQUIRED if _is_docs_only(task) else EXECUTABLE_REQUIRED


def _audit_task(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("status") != "COMPLETE":
        return {"task_audited": False, "reason": "not_complete"}
    audit = task.get("method_audit") or {}
    required = set(_required_for(task))
    applied = {entry.get("skill") for entry in (audit.get("applied") or [])}
    waived = {entry.get("skill") for entry in (audit.get("waived") or [])}
    missing = sorted(required - applied - waived)
    return {
        "task_audited": True,
        "required": sorted(required),
        "applied": sorted(applied),
        "waived": sorted(waived),
        "missing": missing,
        "passed": missing == [],
    }


def _make_state(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2",
        "active_plan": "plan1",
        "tasks": {"task_0": task},
    }


FIXTURES = {
    "applied_with_evidence": {
        "input": {
            "status": "COMPLETE",
            "risk": "mid",
            "files": ["src/foo.py"],
            "files_test": ["tests/test_foo.py"],
            "method_audit": {
                "required": EXECUTABLE_REQUIRED,
                "applied": [
                    {"skill": "test-driven-development",
                     "evidence": {"red": "pytest tests/test_foo.py::test_bar",
                                  "green": "pytest tests/test_foo.py::test_bar",
                                  "tests": ["tests/test_foo.py::test_bar"]}},
                    {"skill": "verification-before-completion",
                     "evidence": {"commands_run": ["pytest", "ruff check"]}},
                    {"skill": "code-review-pass",
                     "evidence": {"findings_count": 0,
                                  "residual_risk": "no shared state touched"}},
                ],
                "missing": [],
                "waived": [],
            },
        },
        "expect_passed": True,
    },
    "missing_tdd_on_executable": {
        "input": {
            "status": "COMPLETE",
            "risk": "mid",
            "files": ["src/foo.py"],
            "files_test": ["tests/test_foo.py"],
            "method_audit": {
                "applied": [
                    {"skill": "verification-before-completion",
                     "evidence": {"commands_run": ["pytest"]}},
                    {"skill": "code-review-pass",
                     "evidence": {"findings_count": 0}},
                ],
                "waived": [],
            },
        },
        "expect_passed": False,
        "expect_missing": ["test-driven-development"],
    },
    "docs_only_waived": {
        "input": {
            "status": "COMPLETE",
            "risk": "low",
            "files": ["docs/runbook.md"],
            "files_test": [],
            "method_audit": {
                "applied": [
                    {"skill": "verification-before-completion",
                     "evidence": {"commands_run": ["markdownlint docs/runbook.md"]}},
                ],
                "waived": [
                    {"skill": "test-driven-development", "reason": "docs-only-task"},
                    {"skill": "code-review-pass", "reason": "docs-only-task"},
                ],
            },
        },
        "expect_passed": True,
    },
    "mid_risk_no_verification": {
        "input": {
            "status": "COMPLETE",
            "risk": "mid",
            "files": ["src/foo.py"],
            "files_test": ["tests/test_foo.py"],
            "method_audit": {
                "applied": [
                    {"skill": "test-driven-development",
                     "evidence": {"red": "x", "green": "x", "tests": ["x"]}},
                ],
                "waived": [],
            },
        },
        "expect_passed": False,
        "expect_missing": ["code-review-pass", "verification-before-completion"],
    },
}


def run() -> int:
    failures: list[str] = []
    for name, case in FIXTURES.items():
        result = _audit_task(case["input"])
        if not result.get("task_audited"):
            failures.append(f"{name}: task not audited ({result})")
            continue
        if result["passed"] != case["expect_passed"]:
            failures.append(f"{name}: expected passed={case['expect_passed']}, got {result}")
            continue
        if not case["expect_passed"]:
            if result["missing"] != case["expect_missing"]:
                failures.append(f"{name}: expected missing={case['expect_missing']}, got {result['missing']}")
    if failures:
        print(json.dumps({"passed": False, "failures": failures}, indent=2))
        return 1
    print(json.dumps({"passed": True, "fixtures": list(FIXTURES.keys())}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run())
