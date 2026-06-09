#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BUILT_RE = re.compile(r"Built from commit:\s*`?([0-9a-fA-F]{7,40})`?")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_head(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def is_ignored(repo: Path, path: Path) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", str(path.relative_to(repo))], cwd=repo)
    return result.returncode == 0


def changed_outputs(repo: Path) -> bool:
    result = subprocess.run(["git", "status", "--short", "--", "graphify-out"], cwd=repo, text=True, stdout=subprocess.PIPE)
    return bool(result.stdout.strip())


def graph_only_changes_since(repo: Path, built: str | None) -> bool:
    if not built:
        return False
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{built}..HEAD"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return False
    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return bool(changed) and all(path == "graphify-out" or path.startswith("graphify-out/") for path in changed)


def check(repo: Path, graph_report: Path, update_ran: bool) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    head = git_head(repo)
    report_ref = str(graph_report.relative_to(repo)) if graph_report.is_relative_to(repo) else str(graph_report)
    if not graph_report.is_file():
        warnings.append("graphify report not found")
        return {
            "schema_version": "1",
            "checked_at": now_iso(),
            "graph_report": report_ref,
            "graphify_present": False,
            "built_commit": None,
            "head_commit": head,
            "fresh": None,
            "update_required": False,
            "update_evidence": {
                "command": "graphify update .",
                "ran": update_ran,
                "tracked_outputs_changed": False,
                "ignored_outputs_note": "",
            },
            "warnings": warnings,
            "errors": errors,
        }
    text = graph_report.read_text(encoding="utf-8")
    match = BUILT_RE.search(text)
    built = match.group(1) if match else None
    if not built:
        errors.append("Built from commit not found")
    graph_only_commit_after_update = update_ran and graph_only_changes_since(repo, built)
    fresh = bool(built and (head.startswith(built) or graph_only_commit_after_update))
    ignored = is_ignored(repo, repo / "graphify-out")
    tracked_changed = changed_outputs(repo)
    note = "graphify-out is ignored; update evidence is command-only" if ignored and update_ran else ""
    if not fresh and not update_ran:
        errors.append("graphify report is stale and update evidence is missing")
    return {
        "schema_version": "1",
        "checked_at": now_iso(),
        "graph_report": report_ref,
        "graphify_present": True,
        "built_commit": built,
        "head_commit": head,
        "fresh": fresh,
        "update_required": not fresh,
        "update_evidence": {
            "command": "graphify update .",
            "ran": update_ran,
            "tracked_outputs_changed": tracked_changed,
            "graph_only_commit_after_update": graph_only_commit_after_update,
            "ignored_outputs_note": note,
        },
        "warnings": warnings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Graphify report freshness.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--graph-report")
    parser.add_argument("--update-ran", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    report_path = Path(args.graph_report).resolve() if args.graph_report else repo / "graphify-out" / "GRAPH_REPORT.md"
    report = check(repo, report_path, args.update_ran)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
