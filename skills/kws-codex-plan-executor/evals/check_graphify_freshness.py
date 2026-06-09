#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_graphify_freshness.py"


def init_repo(repo: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Eval\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def write_report(repo: Path, commit: str) -> None:
    out = repo / "graphify-out"
    out.mkdir()
    (out / "GRAPH_REPORT.md").write_text(
        "# Graph Report\n\n## Graph Freshness\n- Built from commit: `" + commit[:8] + "`\n",
        encoding="utf-8",
    )


def run_check(repo: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = repo / "report.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--output", str(output), *extra],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def main() -> int:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cpe-graphify-") as temp:
        repo = Path(temp)
        head = init_repo(repo)
        write_report(repo, head)
        result, data = run_check(repo)
        checks["fresh_report_passes"] = result.returncode == 0 and data.get("fresh") is True
        if not checks["fresh_report_passes"]:
            failures.append("fresh graph report should pass")

    with tempfile.TemporaryDirectory(prefix="cpe-graphify-") as temp:
        repo = Path(temp)
        init_repo(repo)
        write_report(repo, "0" * 40)
        result, data = run_check(repo)
        checks["stale_report_detected"] = (
            result.returncode != 0 and data.get("fresh") is False and data.get("update_required") is True
        )
        if not checks["stale_report_detected"]:
            failures.append("stale graph report should require update")

    with tempfile.TemporaryDirectory(prefix="cpe-graphify-") as temp:
        repo = Path(temp)
        head = init_repo(repo)
        write_report(repo, head)
        subprocess.run(["git", "add", "graphify-out/GRAPH_REPORT.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "commit graphify output"], cwd=repo, check=True)
        result, data = run_check(repo, "--update-ran")
        checks["graph_only_commit_after_update_is_fresh"] = (
            result.returncode == 0
            and data.get("fresh") is True
            and data.get("update_required") is False
            and data.get("update_evidence", {}).get("graph_only_commit_after_update") is True
        )
        if not checks["graph_only_commit_after_update_is_fresh"]:
            failures.append("graphify-only commits after update should remain fresh for source corpus")

    with tempfile.TemporaryDirectory(prefix="cpe-graphify-") as temp:
        repo = Path(temp)
        init_repo(repo)
        result, data = run_check(repo)
        checks["missing_report_classified"] = (
            result.returncode == 0 and data.get("graphify_present") is False and data.get("warnings")
        )
        if not checks["missing_report_classified"]:
            failures.append("missing graph report should be classified as a warning")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
