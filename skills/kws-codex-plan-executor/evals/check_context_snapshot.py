#!/usr/bin/env python3
"""Deterministic checks for context snapshot budget metadata."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


def run_snapshot(
    script: Path,
    repo: Path,
    plan_text: str,
    max_chars: int,
    *,
    context_threshold: float | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    plan = repo / "plan.md"
    plan.write_text(plan_text, encoding="utf-8")
    output = repo / "context.json"
    command = [
        sys.executable,
        str(script),
        "--repo-root",
        str(repo),
        "--run-id",
        "context-plan-20260519-143022",
        "--plan",
        "plan.md",
        "--max-chars",
        str(max_chars),
        "--output",
        str(output),
    ]
    if context_threshold is not None:
        command.extend(["--context-threshold", str(context_threshold)])
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def run_snapshot_with_packets(
    script: Path,
    repo: Path,
    *,
    plan_text: str = "# Plan\n\nSmall body.\n",
    max_chars: int | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    plan = repo / "plan.md"
    plan.write_text(plan_text, encoding="utf-8")
    manifest = repo / "spec_manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": "1", "section_order": ["S1"], "sections": {"S1": {"title": "Feature"}}}),
        encoding="utf-8",
    )
    packet_dir = repo / f"task_packets_{hashlib.sha256(plan_text.encode('utf-8')).hexdigest()[:8]}"
    packet_dir.mkdir(exist_ok=True)
    for task_id, chars in (("task_0", 123), ("task_1", 456)):
        (packet_dir / f"{task_id}.json").write_text(
            json.dumps({"task_id": task_id, "context_budget": {"estimated_chars": chars}}),
            encoding="utf-8",
        )
    output = repo / "context-with-packets.json"
    command = [
        sys.executable,
        str(script),
        "--repo-root",
        str(repo),
        "--run-id",
        "context-plan-20260519-143022",
        "--plan",
        "plan.md",
        "--spec-manifest",
        str(manifest),
        "--task-packet-dir",
        str(packet_dir),
        "--output",
        str(output),
    ]
    if max_chars is not None:
        command.extend(["--max-chars", str(max_chars)])
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
    return result, data


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_context_snapshot.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="codex-context-snapshot-") as temp:
        repo = Path(temp)

        small_result, small = run_snapshot(script, repo, "# Plan\n\nSmall body.\n", 1000)
        checks["small_plan_under_budget_green"] = (
            small_result.returncode == 0 and small.get("context_budget", {}).get("status") == "green"
        )
        if not checks["small_plan_under_budget_green"]:
            failures.append("small plan should produce context_budget.status=green")

        near_text = "# Plan\n\n" + ("x" * 80) + "\n"
        near_result, near = run_snapshot(script, repo, near_text, 100)
        checks["source_near_budget_yellow"] = (
            near_result.returncode == 0 and near.get("context_budget", {}).get("status") == "yellow"
        )
        if not checks["source_near_budget_yellow"]:
            failures.append("source above 70% and under max should produce yellow")

        tuned_result, tuned = run_snapshot(script, repo, near_text, 100, context_threshold=0.9)
        checks["context_threshold_tunes_yellow_boundary"] = (
            tuned_result.returncode == 0
            and tuned.get("context_budget", {}).get("status") == "green"
            and tuned.get("context_budget", {}).get("context_threshold") == 0.9
        )
        if not checks["context_threshold_tunes_yellow_boundary"]:
            failures.append("--context-threshold should tune the green/yellow boundary")

        over_text = "# A\n\n" + ("a" * 70) + "\n\n# B\n\n" + ("b" * 70) + "\n"
        over_result, over = run_snapshot(script, repo, over_text, 80)
        over_budget = over.get("context_budget", {})
        checks["source_over_budget_red_with_omissions"] = (
            over_result.returncode == 0
            and over_budget.get("status") == "red"
            and bool(over_budget.get("omitted_sections"))
        )
        if not checks["source_over_budget_red_with_omissions"]:
            failures.append("source over max should produce red with omitted section records")

        repeat_result, repeat = run_snapshot(script, repo, over_text, 80)
        checks["section_hashes_stable"] = (
            repeat_result.returncode == 0
            and repeat.get("basis_hash") == over.get("basis_hash")
            and repeat.get("context_budget", {}).get("included_sections") == over_budget.get("included_sections")
        )
        if not checks["section_hashes_stable"]:
            failures.append("repeated snapshot should produce stable basis and included section metadata")

        packet_result, packet_snapshot = run_snapshot_with_packets(script, repo)
        packet_budget = packet_snapshot.get("context_budget", {})
        checks["packet_index_strategy"] = (
            packet_result.returncode == 0
            and packet_budget.get("active_strategy") == "task_packet"
            and packet_budget.get("packet_count") == 2
            and len(packet_snapshot.get("task_packet_index", [])) == 2
        )
        if not checks["packet_index_strategy"]:
            failures.append("snapshot with task packets should record task_packet strategy and packet index")

        huge_plan = "# Plan\n\n" + ("x" * 5000) + "\n"
        packet_budget_result, packet_budget_snapshot = run_snapshot_with_packets(
            script,
            repo,
            plan_text=huge_plan,
            max_chars=1000,
        )
        packet_budget = packet_budget_snapshot.get("context_budget", {})
        checks["packet_budget_uses_packet_index_not_source_size"] = (
            packet_budget_result.returncode == 0
            and packet_budget.get("active_strategy") == "task_packet"
            and packet_budget.get("status") == "green"
            and packet_budget.get("estimated_chars") == 579
            and packet_budget.get("max_packet_chars") == 456
            and packet_budget.get("omitted_sections") == []
        )
        if not checks["packet_budget_uses_packet_index_not_source_size"]:
            failures.append("task-packet snapshots should budget packet indexes instead of oversized source sections")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
