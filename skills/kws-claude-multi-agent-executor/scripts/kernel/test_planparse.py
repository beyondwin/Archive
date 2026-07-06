#!/usr/bin/env python3
"""Tests for planparse.py — deterministic plan parser (CME v3.0 T4).

Run: python3 test_planparse.py
All tests must be invoked from __main__.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Ensure the kernel package is importable when run directly.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _run(name: str, fn) -> bool:
    try:
        fn()
        print(f"  PASS  {name}")
        return True
    except Exception as e:
        print(f"  FAIL  {name}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Fixture (a): H3 standard 2-task plan with Files blocks and a dependency
# ---------------------------------------------------------------------------

FIXTURE_A = """\
# My Implementation Plan

### Task 1: Set up the base module

**Files:**
- `src/base.py`
- `src/__init__.py`

### Task 2: Add feature

**Depends on:** 1

**Files:**
- `src/feature.py`
"""


def test_fixture_a_h3_standard():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_A)

    assert result["header_level"] == 3, f"expected header_level=3, got {result['header_level']}"
    assert len(result["tasks"]) == 2, f"expected 2 tasks, got {len(result['tasks'])}"
    assert result["errors"] == [], f"expected no errors, got {result['errors']}"

    t1 = result["tasks"][0]
    assert t1["id"] == "task_1", f"t1 id wrong: {t1['id']}"
    assert t1["number"] == 1, f"t1 number wrong: {t1['number']}"
    assert t1["title"] == "Set up the base module", f"t1 title wrong: {t1['title']}"
    assert "src/base.py" in t1["files"], f"t1 files wrong: {t1['files']}"
    assert "src/__init__.py" in t1["files"], f"t1 files wrong: {t1['files']}"
    assert t1["dependencies"] == [], f"t1 dependencies wrong: {t1['dependencies']}"
    assert t1["serial"] is False, f"t1 serial wrong: {t1['serial']}"
    assert t1["resource_key"] is None, f"t1 resource_key wrong: {t1['resource_key']}"
    assert isinstance(t1["body"], str), "t1 body should be a string"
    assert "body" in t1

    t2 = result["tasks"][1]
    assert t2["id"] == "task_2", f"t2 id wrong: {t2['id']}"
    assert t2["number"] == 2, f"t2 number wrong: {t2['number']}"
    assert t2["dependencies"] == [1], f"t2 dependencies wrong: {t2['dependencies']}"
    assert "src/feature.py" in t2["files"]


# ---------------------------------------------------------------------------
# Fixture (b): H2 headers + Korean 수정 파일 alias
# ---------------------------------------------------------------------------

FIXTURE_B = """\
# Plan with Korean Files alias

## Task 1: Korean files test

**수정 파일:**
- `lib/util.py`
- `lib/helper.py`

## Task 2: Second task

**수정 파일:**
- `lib/main.py`
"""


def test_fixture_b_h2_korean_alias():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_B)

    assert result["header_level"] == 2, f"expected header_level=2, got {result['header_level']}"
    assert len(result["tasks"]) == 2, f"expected 2 tasks, got {len(result['tasks'])}"
    assert result["errors"] == [], f"expected no errors, got {result['errors']}"

    t1 = result["tasks"][0]
    assert t1["id"] == "task_1"
    assert "lib/util.py" in t1["files"], f"Korean alias parse failed: {t1['files']}"
    assert "lib/helper.py" in t1["files"]

    t2 = result["tasks"][1]
    assert "lib/main.py" in t2["files"]


# ---------------------------------------------------------------------------
# Fixture (c): Task with no Files block → task_N_missing_files error
# ---------------------------------------------------------------------------

FIXTURE_C = """\
### Task 1: No files here

This task has no Files block at all.

### Task 2: Has files

**Files:**
- `src/ok.py`
"""


def test_fixture_c_missing_files_error():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_C)

    assert len(result["tasks"]) == 2, f"expected 2 tasks, got {len(result['tasks'])}"
    assert "task_1_missing_files" in result["errors"], (
        f"expected task_1_missing_files in errors, got {result['errors']}"
    )
    # Task 2 should parse fine with no error
    assert not any("task_2_missing_files" in e for e in result["errors"]), (
        f"unexpected task_2 error: {result['errors']}"
    )
    t2 = result["tasks"][1]
    assert "src/ok.py" in t2["files"]


# ---------------------------------------------------------------------------
# Fixture (d): ../escape.py → out_of_repo error
# ---------------------------------------------------------------------------

FIXTURE_D = """\
### Task 1: Path escape

**Files:**
- `../escape.py`
- `src/legit.py`
"""


def test_fixture_d_out_of_repo_path():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_D)

    assert len(result["tasks"]) == 1
    out_of_repo_errors = [e for e in result["errors"] if "out_of_repo_path" in e]
    assert out_of_repo_errors, f"expected out_of_repo_path error, got {result['errors']}"
    # The error should name the offending path
    assert any("../escape.py" in e or "escape.py" in e for e in out_of_repo_errors), (
        f"error should mention path: {out_of_repo_errors}"
    )
    # The offending path should NOT appear in files
    t1 = result["tasks"][0]
    assert not any(".." in f for f in t1["files"]), (
        f"out-of-repo path leaked into files: {t1['files']}"
    )
    # The legit file should still be present
    assert "src/legit.py" in t1["files"], f"legit file missing: {t1['files']}"


# ---------------------------------------------------------------------------
# Fixture (e): No task headers at all → no_task_headers error
# ---------------------------------------------------------------------------

FIXTURE_E = """\
# Just a document

No tasks defined here. Only prose.
"""


def test_fixture_e_no_task_headers():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_E)

    assert "no_task_headers" in result["errors"], (
        f"expected no_task_headers error, got {result['errors']}"
    )
    assert result["tasks"] == []


# ---------------------------------------------------------------------------
# Fixture (f): serial: true and Resource Key annotations
# ---------------------------------------------------------------------------

FIXTURE_F = """\
### Task 1: Serial task

serial: true

**Resource Key:** db-port-5432

**Files:**
- `src/db.py`

### Task 2: Normal task

**Files:**
- `src/api.py`
"""


def test_fixture_f_serial_and_resource_key():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_F)

    assert result["errors"] == [], f"unexpected errors: {result['errors']}"
    t1 = result["tasks"][0]
    assert t1["serial"] is True, f"t1 serial wrong: {t1['serial']}"
    assert t1["resource_key"] == "db-port-5432", f"t1 resource_key wrong: {t1['resource_key']}"

    t2 = result["tasks"][1]
    assert t2["serial"] is False, f"t2 serial wrong: {t2['serial']}"
    assert t2["resource_key"] is None, f"t2 resource_key wrong: {t2['resource_key']}"


# ---------------------------------------------------------------------------
# Fixture (g): yaml waygent-task block with file_claims
# ---------------------------------------------------------------------------

FIXTURE_G = """\
### Task 1: YAML task with file_claims

```yaml waygent-task
task_id: task_1
title: YAML task with file_claims
file_claims:
  - src/yaml_file.py
  - src/another.py
```
"""


def test_fixture_g_yaml_file_claims():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_G)

    assert result["errors"] == [] or not any("missing_files" in e for e in result["errors"]), (
        f"unexpected missing_files error: {result['errors']}"
    )
    t1 = result["tasks"][0]
    assert "src/yaml_file.py" in t1["files"], f"yaml file_claims not parsed: {t1['files']}"
    assert "src/another.py" in t1["files"]


# ---------------------------------------------------------------------------
# Fixture (h): dependencies as ints (not strings)
# ---------------------------------------------------------------------------

FIXTURE_H = """\
### Task 1: First

**Files:**
- `src/a.py`

### Task 2: Second depends on first

**Depends on:** 1

**Files:**
- `src/b.py`

### Task 3: Third depends on first and second

**Depends on:** 1, 2

**Files:**
- `src/c.py`
"""


def test_fixture_h_dependencies_are_ints():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_H)

    assert result["errors"] == [], f"unexpected errors: {result['errors']}"
    t2 = result["tasks"][1]
    assert t2["dependencies"] == [1], f"t2 dependencies should be [1], got {t2['dependencies']}"
    assert all(isinstance(d, int) for d in t2["dependencies"]), (
        f"dependencies should be ints: {t2['dependencies']}"
    )

    t3 = result["tasks"][2]
    assert t3["dependencies"] == [1, 2], f"t3 dependencies wrong: {t3['dependencies']}"


# ---------------------------------------------------------------------------
# Fixture (i): Acceptance Criteria shell block
# ---------------------------------------------------------------------------

FIXTURE_I = """\
### Task 1: With acceptance criteria

**Files:**
- `src/tested.py`

## Acceptance Criteria

```bash
pytest src/tested.py
```
"""


def test_fixture_i_acceptance_criteria():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_I)

    t1 = result["tasks"][0]
    assert t1["acceptance"] is not None, "acceptance should be populated"
    assert "pytest" in t1["acceptance"], f"acceptance content wrong: {t1['acceptance']}"


# ---------------------------------------------------------------------------
# Fixture (j): absolute path → out_of_repo error
# ---------------------------------------------------------------------------

FIXTURE_J = """\
### Task 1: Absolute path

**Files:**
- `/etc/passwd`
- `src/safe.py`
"""


def test_fixture_j_absolute_path_out_of_repo():
    from scripts.kernel import planparse  # type: ignore

    result = planparse.parse(FIXTURE_J)

    out_of_repo_errors = [e for e in result["errors"] if "out_of_repo_path" in e]
    assert out_of_repo_errors, f"expected out_of_repo_path error for absolute path, got {result['errors']}"
    t1 = result["tasks"][0]
    assert not any(f.startswith("/") for f in t1["files"]), (
        f"absolute path leaked into files: {t1['files']}"
    )


# ---------------------------------------------------------------------------
# Main: run all test functions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        ("fixture_a: H3 standard 2-task plan + Files", test_fixture_a_h3_standard),
        ("fixture_b: H2 + Korean 수정 파일 alias", test_fixture_b_h2_korean_alias),
        ("fixture_c: missing Files block → errors", test_fixture_c_missing_files_error),
        ("fixture_d: ../escape.py → out_of_repo error", test_fixture_d_out_of_repo_path),
        ("fixture_e: no task headers → no_task_headers", test_fixture_e_no_task_headers),
        ("fixture_f: serial + resource_key annotations", test_fixture_f_serial_and_resource_key),
        ("fixture_g: yaml waygent-task file_claims", test_fixture_g_yaml_file_claims),
        ("fixture_h: dependencies are ints", test_fixture_h_dependencies_are_ints),
        ("fixture_i: acceptance criteria shell block", test_fixture_i_acceptance_criteria),
        ("fixture_j: absolute path → out_of_repo error", test_fixture_j_absolute_path_out_of_repo),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        if _run(name, fn):
            passed += 1
        else:
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
