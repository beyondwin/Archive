from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentrunway.resolver import (
    ResolutionError,
    read_last_run,
    resolve_run_alias,
    resolve_run_inputs,
    write_last_run,
)


def _write_pair(repo: Path, slug: str, *, date: str = "2026-05-20") -> tuple[Path, Path]:
    specs = repo / "docs" / "superpowers" / "specs"
    plans = repo / "docs" / "superpowers" / "plans"
    specs.mkdir(parents=True, exist_ok=True)
    plans.mkdir(parents=True, exist_ok=True)
    spec = specs / f"{date}-{slug}-design.md"
    plan = plans / f"{date}-{slug}.md"
    spec.write_text("# Design: {slug}\n\n## Summary\n\nSpec.\n".format(slug=slug), encoding="utf-8")
    plan.write_text(
        f"# Plan: {slug}\n\n"
        f"- Design: `{spec.relative_to(repo)}`\n\n"
        "## Task 1\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Example\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1]\n"
        "file_claims:\n"
        "  - {path: example.txt, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n",
        encoding="utf-8",
    )
    return spec, plan


def test_resolve_topic_to_exact_superpowers_pair(git_repo: Path) -> None:
    spec, plan = _write_pair(git_repo, "checkout-flow")

    resolved = resolve_run_inputs(
        repo_root=git_repo,
        plan=None,
        spec=None,
        topic="checkout-flow",
        latest=False,
        adapter="codex",
    )

    assert resolved.plan_path == plan
    assert resolved.spec_path == spec
    assert resolved.adapter == "codex"
    assert resolved.source == "topic"


def test_explicit_plan_can_infer_design_reference(git_repo: Path) -> None:
    spec, plan = _write_pair(git_repo, "billing-ledger")

    resolved = resolve_run_inputs(
        repo_root=git_repo,
        plan=plan,
        spec=None,
        topic=None,
        latest=False,
        adapter="claude",
    )

    assert resolved.plan_path == plan
    assert resolved.spec_path == spec
    assert resolved.source == "explicit_plan"


def test_ambiguous_topic_fails_with_candidates(git_repo: Path) -> None:
    _write_pair(git_repo, "runner-hardening")
    _write_pair(git_repo, "runner-hardening-followup")

    with pytest.raises(ResolutionError) as exc:
        resolve_run_inputs(
            repo_root=git_repo,
            plan=None,
            spec=None,
            topic="runner-hardening",
            latest=False,
            adapter="codex",
        )

    assert "ambiguous topic" in str(exc.value)
    assert len(exc.value.payload["candidates"]) == 2


def test_latest_uses_newest_complete_pair(git_repo: Path) -> None:
    _write_pair(git_repo, "older-topic", date="2026-05-19")
    spec, plan = _write_pair(git_repo, "newer-topic", date="2026-05-20")

    resolved = resolve_run_inputs(
        repo_root=git_repo,
        plan=None,
        spec=None,
        topic=None,
        latest=True,
        adapter="codex",
    )

    assert resolved.plan_path == plan
    assert resolved.spec_path == spec
    assert resolved.source == "latest"


def test_last_run_pointer_is_workspace_scoped(git_repo: Path, isolated_home: Path) -> None:
    write_last_run(git_repo, "run-123")

    assert read_last_run(git_repo) == "run-123"
    workspace_dir = next((isolated_home / "workspaces").glob("*"))
    payload = json.loads((workspace_dir / "last_run.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-123"
    assert resolve_run_alias(git_repo, run_id=None, last=True) == "run-123"
