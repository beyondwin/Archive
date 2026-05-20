from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentrunway.contract import ContractError, build_run_contract, write_contract
from agentrunway.plan_parser import parse_plan


def _write_spec(path: Path) -> None:
    path.write_text(
        "# Design: Example\n\n"
        "## Summary\n\n"
        "Build the feature.\n\n"
        "## Acceptance\n\n"
        "The run SHALL verify the feature.\n",
        encoding="utf-8",
    )


def _write_numbered_spec(path: Path) -> None:
    path.write_text(
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
        encoding="utf-8",
    )


def _write_plan(path: Path, *, spec_ref: str = "S1.1", acceptance: str = "python -m pytest") -> None:
    path.write_text(
        "## Task 1: Example\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Example\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        f"spec_refs: [{spec_ref}]\n"
        "file_claims:\n"
        "  - {path: src/example.py, mode: owned}\n"
        f"acceptance_commands: [{acceptance}]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Implement the example.\n",
        encoding="utf-8",
    )


def test_build_run_contract_records_hashes_tasks_and_manifest(tmp_path: Path, git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    _write_spec(spec)
    _write_plan(plan)
    tasks = parse_plan(plan)

    contract = build_run_contract(
        run_id="run-1",
        workspace_id="workspace-1",
        repo_root=git_repo,
        spec_path=spec,
        plan_path=plan,
        base_commit_sha="abc123",
        tasks=tasks,
        adapter="codex",
        model_profile="default",
        allow_dirty_source=False,
        apply_to_source=False,
    )

    assert contract.run_id == "run-1"
    assert contract.spec["path"] == str(spec)
    assert contract.plan["path"] == str(plan)
    assert contract.spec["manifest_sections"]["S1.1"] == "Summary"
    assert contract.spec["manifest_sections"]["S1.2"] == "Acceptance"
    assert contract.tasks[0]["task_id"] == "task_001"
    assert contract.tasks[0]["spec_refs"] == ["S1.1"]
    assert contract.coverage["unreferenced"] == ["S1", "S1.2"]


def test_contract_rejects_missing_spec_refs(tmp_path: Path, git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    _write_spec(spec)
    _write_plan(plan, spec_ref="S404")

    with pytest.raises(ContractError, match="missing spec_refs: task_001 -> S404"):
        build_run_contract(
            run_id="run-1",
            workspace_id="workspace-1",
            repo_root=git_repo,
            spec_path=spec,
            plan_path=plan,
            base_commit_sha="abc123",
            tasks=parse_plan(plan),
            adapter="codex",
            model_profile="default",
            allow_dirty_source=False,
            apply_to_source=False,
        )


def test_contract_accepts_rootless_numbered_spec_refs(tmp_path: Path, git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    _write_spec(spec)
    _write_plan(plan, spec_ref="S2")

    contract = build_run_contract(
        run_id="run-1",
        workspace_id="workspace-1",
        repo_root=git_repo,
        spec_path=spec,
        plan_path=plan,
        base_commit_sha="abc123",
        tasks=parse_plan(plan),
        adapter="codex",
        model_profile="default",
        allow_dirty_source=False,
        apply_to_source=False,
    )

    assert contract.coverage["covered"] == ["S1.2"]


def test_contract_canonicalizes_bare_numbered_spec_refs(tmp_path: Path, git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    _write_numbered_spec(spec)
    _write_plan(plan, spec_ref="6.3")

    contract = build_run_contract(
        run_id="run-1",
        workspace_id="workspace-1",
        repo_root=git_repo,
        spec_path=spec,
        plan_path=plan,
        base_commit_sha="abc123",
        tasks=parse_plan(plan),
        adapter="codex",
        model_profile="default",
        allow_dirty_source=False,
        apply_to_source=False,
    )

    assert contract.tasks[0]["spec_refs"] == ["S1.6.3"]
    assert contract.coverage["covered"] == ["S1.6.3"]


def test_contract_rejects_empty_acceptance_commands(git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    _write_spec(spec)
    _write_plan(plan, acceptance="")

    with pytest.raises(ContractError, match="task_001 has no acceptance commands"):
        build_run_contract(
            run_id="run-1",
            workspace_id="workspace-1",
            repo_root=git_repo,
            spec_path=spec,
            plan_path=plan,
            base_commit_sha="abc123",
            tasks=parse_plan(plan),
            adapter="codex",
            model_profile="default",
            allow_dirty_source=False,
            apply_to_source=False,
        )


def test_write_contract_creates_immutable_contract_json(tmp_path: Path, git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    run_dir = tmp_path / "run"
    _write_spec(spec)
    _write_plan(plan)
    contract = build_run_contract(
        run_id="run-1",
        workspace_id="workspace-1",
        repo_root=git_repo,
        spec_path=spec,
        plan_path=plan,
        base_commit_sha="abc123",
        tasks=parse_plan(plan),
        adapter="local",
        model_profile="default",
        allow_dirty_source=False,
        apply_to_source=False,
    )

    path = write_contract(run_dir, contract)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path == run_dir / "contract.json"
    assert payload["run_id"] == "run-1"
    assert payload["coverage"]["covered"] == ["S1.1"]


def test_build_run_contract_requires_spec_for_non_local_adapter(tmp_path: Path, git_repo: Path) -> None:
    plan = git_repo / "plan.md"
    _write_plan(plan)
    tasks = parse_plan(plan)

    with pytest.raises(ContractError, match="non-local adapter requires --spec"):
        build_run_contract(
            run_id="run-1",
            workspace_id="workspace-1",
            repo_root=git_repo,
            spec_path=None,
            plan_path=plan,
            base_commit_sha="abc123",
            tasks=tasks,
            adapter="codex",
            model_profile="default",
            allow_dirty_source=False,
            apply_to_source=False,
        )
