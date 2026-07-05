#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from normalize_cpe_run import normalize  # noqa: E402


RUBRIC_KEYS = ("safety", "context", "delegation_efficiency", "evidence", "validator_maintainability")
EXPECTED_LOCAL_FALLBACK_REASON = "spawn_agent tool policy requires explicit user delegation intent"


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"run_id": path.parent.name, "lifecycle_outcome": "invalid", "_load_error": True}
    return payload if isinstance(payload, dict) else {"run_id": path.parent.name, "_load_error": True}


def state_paths(codex_home: Path, include_finished: bool) -> list[Path]:
    paths = sorted((codex_home / "orchestrator").glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if include_finished:
        return paths
    result: list[Path] = []
    for path in paths:
        state = load_json(path)
        if state.get("lifecycle_outcome") not in {"finished", "failed", "blocked"}:
            result.append(path)
    return result


def grade_counts(normalized: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "green_count": sum(1 for item in normalized if item.get("run_quality_report_class") == "green"),
        "green_with_info_count": sum(1 for item in normalized if item.get("run_quality_report_class") == "green-with-info"),
        "yellow_count": sum(1 for item in normalized if item.get("run_quality_report_class") == "yellow"),
        "red_count": sum(
            1
            for item in normalized
            if item.get("run_quality_report_class") == "red" or item.get("completion_passed") is False
        ),
    }


def taxonomy_count(item: dict[str, Any], key: str) -> int:
    taxonomy = item.get("followup_taxonomy")
    if not isinstance(taxonomy, dict):
        return 0
    value = taxonomy.get(key)
    return len(value) if isinstance(value, list) else 0


def expected_local_fallback_count(item: dict[str, Any]) -> int:
    followups = item.get("open_followups")
    if not isinstance(followups, list) or "delegation_policy_expected_local_fallback" not in followups:
        return 0
    reasons = item.get("dispatch_decision_reasons")
    if not isinstance(reasons, dict):
        return 0
    return int(reasons.get(EXPECTED_LOCAL_FALLBACK_REASON, 0) > 0)


def worst_grade(values: list[str]) -> str:
    if "red" in values:
        return "red"
    if "yellow" in values:
        return "yellow"
    return "green"


def build_report(run_dirs: list[Path]) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        state = load_json(run_dir / "state.json")
        item = normalize(state)
        item["state_path"] = str(run_dir / "state.json")
        runs.append(item)
    counts = grade_counts(runs)
    summary = {
        "run_count": len(runs),
        "finished_passed_count": sum(
            1 for item in runs if item.get("terminal_state") == "finished" and item.get("completion_passed") is True
        ),
        **counts,
        "full_spec_fallback_count": sum(int(item.get("full_spec_fallback_count") or 0) for item in runs),
        "expected_local_fallback_count": sum(expected_local_fallback_count(item) for item in runs),
        "actionable_followup_count": sum(taxonomy_count(item, "actionable_followups") for item in runs),
        "informational_followup_count": sum(taxonomy_count(item, "informational_followups") for item in runs),
    }
    rubric = {
        "safety": "red" if counts["red_count"] else "green",
        "context": "yellow" if summary["full_spec_fallback_count"] else "green",
        "delegation_efficiency": (
            "yellow"
            if any(
                "delegation_policy_prevented_all_delegation"
                in (item.get("followup_taxonomy", {}).get("actionable_followups") or [])
                for item in runs
            )
            else ("green-with-info" if summary["expected_local_fallback_count"] else "green")
        ),
        "evidence": worst_grade(["yellow" if not item.get("verification_evidence_classes") else "green" for item in runs]),
        "validator_maintainability": "green",
    }
    return {"schema_version": "1", "summary": summary, "rubric": rubric, "runs": runs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze recent CPE runs into an operational-quality rubric.")
    parser.add_argument("--codex-home", required=True)
    parser.add_argument("--recent", type=int, default=5)
    parser.add_argument("--include-finished", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    paths = state_paths(Path(args.codex_home).expanduser(), include_finished=args.include_finished)
    if not args.include_finished:
        paths = paths[: args.recent]
    report = build_report([path.parent for path in paths])
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
