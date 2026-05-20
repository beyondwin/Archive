from __future__ import annotations

from pathlib import Path

from agentrunway.plan_parser import parse_plan


ROOT = Path(__file__).resolve().parents[1]


def test_mvp_fixtures_have_parseable_plans_and_specs() -> None:
    fixture_root = ROOT / "evals" / "fixtures"
    fixtures = {
        "01-single-doc-task",
        "02-two-independent-code-tasks",
        "03-overlapping-file-claims",
        "04-worker-method-audit-missing",
        "05-agentlens-unavailable",
    }
    assert {path.name for path in fixture_root.iterdir() if path.is_dir()} >= fixtures
    for name in fixtures:
        plan = fixture_root / name / "plan.md"
        spec = fixture_root / name / "spec.md"
        assert spec.exists()
        assert parse_plan(plan)


def test_overlapping_claim_fixture_expresses_conflict() -> None:
    tasks = parse_plan(ROOT / "evals" / "fixtures" / "03-overlapping-file-claims" / "plan.md")
    paths = [claim.path for task in tasks for claim in task.file_claims]
    assert paths.count("src/shared.py") == 2
