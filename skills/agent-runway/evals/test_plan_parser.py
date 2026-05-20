from __future__ import annotations

from pathlib import Path

import pytest

from agentrunway.plan_parser import PlanParseError, canonical_hash, parse_plan, parse_spec_manifest


PLAN = """# Auth Plan

## Task 1: Token refresh retry

```yaml agentrunway-task
task_id: task_001
title: Token refresh retry
risk: medium
phase: implementation
dependencies: []
spec_refs: [S2.1]
file_claims:
  - {path: src/auth/session.ts, mode: owned}
  - {path: tests/auth/session.test.ts, mode: owned}
acceptance_commands:
  - npm test -- tests/auth/session.test.ts
resource_keys: []
required_skills: [test-driven-development]
serial: false
```

Implement bounded retry behavior.
"""


def test_parse_plan_extracts_task_block(tmp_path: Path) -> None:
    path = tmp_path / "plan.md"
    path.write_text(PLAN, encoding="utf-8")
    tasks = parse_plan(path)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_id == "task_001"
    assert task.title == "Token refresh retry"
    assert task.file_claims[0].path == "src/auth/session.ts"
    assert task.required_skills == ("test-driven-development",)
    assert "bounded retry" in task.objective


def test_parse_plan_rejects_missing_agentrunway_task_block(tmp_path: Path) -> None:
    path = tmp_path / "plan.md"
    path.write_text("## Task 1: Missing\n\nNo block\n", encoding="utf-8")
    with pytest.raises(PlanParseError, match="missing agentrunway-task"):
        parse_plan(path)


def test_spec_manifest_resolves_numbered_refs(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("# Design\n\n## Runtime\n\nDetails\n\n### Adapter\n\nMore\n", encoding="utf-8")
    manifest = parse_spec_manifest(spec)
    assert manifest["sections"]["S1"]["title"] == "Design"
    assert manifest["sections"]["S1.1"]["title"] == "Runtime"
    assert manifest["sections"]["S1.1.1"]["title"] == "Adapter"


def test_canonical_hash_ignores_trailing_space_and_crlf(tmp_path: Path) -> None:
    left = tmp_path / "left.md"
    right = tmp_path / "right.md"
    left.write_text("a  \r\nb\r\n", encoding="utf-8")
    right.write_text("a\nb\n", encoding="utf-8")
    assert canonical_hash(left) == canonical_hash(right)
