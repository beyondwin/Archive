from __future__ import annotations

from pathlib import Path

from agentrunway.plan_lint import lint_plan


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _spec(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "design.md",
        "# Design\n\n## Summary\n\nContext.\n\n## API\n\nDetails.\n",
    )


def _valid_plan() -> str:
    fence = "```yaml agentrunway" + "-task"
    return (
        "# Demo Implementation Plan\n\n"
        "### Task 1: First\n\n"
        f"{fence}\n"
        "task_id: task_001\n"
        "title: First\n"
        "risk: medium\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1]\n"
        "file_claims:\n"
        "  - {path: src/example.py, mode: owned}\n"
        "acceptance_commands: [python -m pytest tests/test_example.py -v]\n"
        "required_skills: [using-superpowers, test-driven-development]\n"
        "serial: true\n"
        "```\n\n"
        "Implement the first task.\n"
    )


def test_valid_plan_has_no_errors(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", _valid_plan())
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert result.ok is True
    assert result.errors == []


def test_lint_result_includes_comparable_task_metadata_report(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan()
        + (
            "\n### Task 2: Followup\n\n"
            "```yaml agentrunway-task\n"
            "task_id: task_002\n"
            "title: Followup\n"
            "risk: high\n"
            "phase: verification\n"
            "dependencies: [task_001]\n"
            "spec_refs: [S1.1]\n"
            "file_claims:\n"
            "  - {path: src/example.py, mode: read_only}\n"
            "acceptance_commands: [python -m pytest]\n"
            "required_skills: [verification-before-completion]\n"
            "serial: false\n"
            "```\n\n"
            "Verify the first task.\n"
        ),
    )

    payload = lint_plan(plan_path=plan, spec_path=_spec(tmp_path)).to_dict()

    report = payload["metadata_report"]
    assert report["summary"] == {
        "task_count": 2,
        "tasks_with_spec_refs": 2,
        "tasks_with_file_claims": 2,
        "tasks_with_acceptance_commands": 2,
        "dependency_edges": 1,
        "serial_tasks": 1,
        "high_risk_tasks": 1,
    }
    first, second = report["tasks"]
    assert first["task_id"] == "task_001"
    assert first["spec_refs"] == ["S1"]
    assert first["canonical_spec_refs"] == ["S1"]
    assert first["spec_ref_resolutions"] == [
        {"input_ref": "S1", "canonical_ref": "S1", "status": "resolved", "suggestion": None}
    ]
    assert first["acceptance_command_count"] == 1
    assert first["file_claim_count"] == 1
    assert second["task_id"] == "task_002"
    assert second["dependencies"] == ["task_001"]
    assert second["required_skills"] == ["verification-before-completion"]


def test_missing_task_block_is_error(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", "# Plan\n\n### Task 1: Missing\n")
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert result.ok is False
    assert any(item.code == "missing_task_block" for item in result.errors)


def test_unknown_dependency_is_error(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace("dependencies: []", "dependencies: [task_999]"),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "unknown_dependency" for item in result.errors)


def test_missing_acceptance_command_for_owned_file_is_error(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace(
            "acceptance_commands: [python -m pytest tests/test_example.py -v]",
            "acceptance_commands: []",
        ),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "missing_acceptance_commands" for item in result.errors)


def test_forbidden_owned_path_is_error(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace("src/example.py", "graphify-out/GRAPH_REPORT.md"),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "forbidden_owned_path" for item in result.errors)


def test_dot_prefixed_forbidden_owned_paths_are_errors(tmp_path: Path) -> None:
    for forbidden_path in (".git/config", ".agentrunway/run.json"):
        plan = _write(
            tmp_path / "plan.md",
            _valid_plan().replace("src/example.py", forbidden_path),
        )
        result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

        assert any(item.code == "forbidden_owned_path" for item in result.errors)


def test_empty_plan_is_error(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", "# Empty plan\n")
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert result.ok is False
    assert any(item.code == "missing_task_block" for item in result.errors)


def test_implementation_task_without_file_claims_is_error(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace(
            "file_claims:\n"
            "  - {path: src/example.py, mode: owned}\n",
            "file_claims: []\n",
        ),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "missing_file_claims" for item in result.errors)


def test_glob_owned_claim_overlap_is_error_when_unordered(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace("src/example.py", "src/**")
        + (
            "\n### Task 2: Second\n\n"
            "```yaml agentrunway-task\n"
            "task_id: task_002\n"
            "title: Second\n"
            "risk: high\n"
            "phase: implementation\n"
            "dependencies: []\n"
            "spec_refs: [S1]\n"
            "file_claims:\n"
            "  - {path: src/foo.py, mode: owned}\n"
            "acceptance_commands: [python -m pytest tests/test_example.py -v]\n"
            "required_skills: [using-superpowers, test-driven-development]\n"
            "serial: true\n"
            "```\n\n"
            "Implement the second task.\n"
        ),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "owned_claim_conflict" for item in result.errors)


def test_dependency_ordered_owned_claim_overlap_is_allowed(tmp_path: Path) -> None:
    plan = _write(
        tmp_path / "plan.md",
        _valid_plan().replace("src/example.py", "src/**").replace("risk: medium", "risk: high")
        + (
            "\n### Task 2: Second\n\n"
            "```yaml agentrunway-task\n"
            "task_id: task_002\n"
            "title: Second\n"
            "risk: medium\n"
            "phase: implementation\n"
            "dependencies: [task_001]\n"
            "spec_refs: [S1]\n"
            "file_claims:\n"
            "  - {path: src/foo.py, mode: owned}\n"
            "acceptance_commands: [python -m pytest tests/test_example.py -v]\n"
            "required_skills: [using-superpowers, test-driven-development]\n"
            "serial: true\n"
            "```\n\n"
            "Implement the second task.\n"
        ),
    )
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert result.ok is True


def test_broad_owned_glob_requires_high_risk(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("src/example.py", "src/**"))
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "broad_glob_requires_high_risk" for item in result.errors)


def test_invalid_risk_is_error(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("risk: medium", "risk: banana"))
    result = lint_plan(plan_path=plan, spec_path=_spec(tmp_path))

    assert any(item.code == "invalid_risk" for item in result.errors)


def test_rootless_numbered_spec_refs_resolve(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "numbered.md",
        "# Design\n\n"
        + "".join(
            f"## {index}. Section\n\nDetails.\n\n"
            + ("### 10.3 Plan Lint\n\nDetails.\n\n" if index == 10 else "")
            for index in range(1, 13)
        ),
    )
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("spec_refs: [S1]", "spec_refs: [S10.3, S12]"))
    result = lint_plan(plan_path=plan, spec_path=spec)

    assert result.ok is True


def test_bare_numbered_spec_refs_resolve(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "trust-hardening.md",
        "# AgentRunway Trust Hardening\n\n"
        "## 1. Overview\n\n"
        "Overview text.\n\n"
        "## 2. Runner\n\n"
        "Runner text.\n\n"
        "## 3. Workers\n\n"
        "Worker text.\n\n"
        "## 4. Review\n\n"
        "Review text.\n\n"
        "## 5. Verification\n\n"
        "Verification text.\n\n"
        "## 6. Spec References\n\n"
        "Spec reference text.\n\n"
        "### 6.1 Manifest\n\n"
        "Manifest text.\n\n"
        "### 6.2 Contract\n\n"
        "Contract text.\n\n"
        "### 6.3 Canonical Resolver\n\n"
        "Resolver text.\n",
    )
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("spec_refs: [S1]", "spec_refs: [6.3]"))

    errors = lint_plan(plan_path=plan, spec_path=spec).errors

    assert not [error for error in errors if error.code == "unresolved_spec_ref"]


def test_metadata_report_includes_canonical_spec_refs(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "trust-hardening.md",
        "# AgentRunway Trust Hardening\n\n"
        "## 1. Overview\n\n"
        "Overview text.\n\n"
        "## 2. Runner\n\n"
        "Runner text.\n\n"
        "## 3. Workers\n\n"
        "Worker text.\n\n"
        "## 4. Review\n\n"
        "Review text.\n\n"
        "## 5. Verification\n\n"
        "Verification text.\n\n"
        "## 6. Spec References\n\n"
        "Spec reference text.\n\n"
        "### 6.1 Manifest\n\n"
        "Manifest text.\n\n"
        "### 6.2 Contract\n\n"
        "Contract text.\n\n"
        "### 6.3 Canonical Resolver\n\n"
        "Resolver text.\n",
    )
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("spec_refs: [S1]", "spec_refs: [6.3]"))

    task = lint_plan(plan_path=plan, spec_path=spec).to_dict()["metadata_report"]["tasks"][0]

    assert task["spec_refs"] == ["6.3"]
    assert task["canonical_spec_refs"] == ["S1.6.3"]
    assert task["spec_ref_resolutions"] == [
        {"input_ref": "6.3", "canonical_ref": "S1.6.3", "status": "resolved", "suggestion": None}
    ]


def test_unresolved_numbered_spec_refs_include_canonical_suggestion(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "trust-hardening.md",
        "# AgentRunway Trust Hardening\n\n"
        "## 1. Overview\n\n"
        "Overview text.\n\n"
        "## 2. Runner\n\n"
        "Runner text.\n\n"
        "## 3. Workers\n\n"
        "Worker text.\n\n"
        "## 4. Review\n\n"
        "Review text.\n\n"
        "## 5. Verification\n\n"
        "Verification text.\n\n"
        "## 6. Spec References\n\n"
        "Spec reference text.\n\n"
        "### 6.1 Manifest\n\n"
        "Manifest text.\n\n"
        "### 6.2 Contract\n\n"
        "Contract text.\n\n"
        "### 6.3 Canonical Resolver\n\n"
        "Resolver text.\n",
    )
    plan = _write(tmp_path / "plan.md", _valid_plan().replace("spec_refs: [S1]", "spec_refs: [6.30]"))

    result = lint_plan(plan_path=plan, spec_path=spec)

    assert any(
        error.message == "unresolved_spec_ref task=task_001 ref=6.30 suggestion=S1.6.3"
        for error in result.errors
    )
