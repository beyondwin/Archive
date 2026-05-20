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
