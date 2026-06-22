#!/usr/bin/env python3
"""Score CPE execution routing against the installed Superpowers contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_SKILLS = {
    "brainstorming": "brainstorming/SKILL.md",
    "writing_plans": "writing-plans/SKILL.md",
    "subagent_driven_development": "subagent-driven-development/SKILL.md",
    "verification_before_completion": "verification-before-completion/SKILL.md",
}

CRITERIA = (
    "superpowers_alignment",
    "state_recoverability",
    "implementation_quality",
    "operator_cost",
    "mode_coverage",
    "migration_risk",
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def has_all(text: str, tokens: tuple[str, ...]) -> bool:
    return all(token in text for token in tokens)


def load_superpowers(root: Path) -> dict[str, str]:
    return {name: read_text(root / rel) for name, rel in REQUIRED_SKILLS.items()}


def load_cpe(skill_root: Path) -> str:
    files = [
        "SKILL.md",
        "README.md",
        "ARCHITECTURE.md",
        "references/mode-contracts.md",
        "references/execution-cycle.md",
        "references/state-schema.md",
        "references/subagent-run-store.md",
        "references/pre-dispatch-pipeline.md",
    ]
    return "\n".join(read_text(skill_root / item) for item in files)


def required_contracts(superpowers: dict[str, str]) -> dict[str, bool]:
    brainstorming = superpowers["brainstorming"]
    writing = superpowers["writing_plans"]
    subagent = superpowers["subagent_driven_development"]
    verification = superpowers["verification_before_completion"]
    return {
        "brainstorming_hard_gate": has_all(
            brainstorming,
            (
                "<HARD-GATE>",
                "Do NOT invoke any implementation skill",
                "presented a design and the user has approved it",
                "invoke writing-plans skill",
            ),
        ),
        "writing_plans_header": has_all(
            writing,
            (
                "Every plan MUST start with this header",
                "REQUIRED SUB-SKILL",
                "subagent-driven-development",
                "executing-plans",
                "No Placeholders",
            ),
        ),
        "subagent_review_loop": has_all(
            subagent,
            (
                "fresh implementer subagent per task",
                "task reviewer",
                "final code reviewer",
                "progress ledger",
                "review-package",
            ),
        ),
        "verification_before_completion": has_all(
            verification,
            (
                "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE",
                "Evidence before claims",
                "RUN: Execute the FULL command",
            ),
        ),
    }


def cpe_contracts(cpe_text: str) -> dict[str, bool]:
    return {
        "stateful_runs": has_all(
            cpe_text,
            ("~/.codex/orchestrator/<run_id>/state.json", "context_health", "completion_audit"),
        ),
        "mode_coverage": has_all(cpe_text, ("interactive", "headless", "prompt", "handoff", "resume=latest")),
        "task_packets": has_all(cpe_text, ("task packet", "current_task_packet_path", "subagent_strategy")),
        "safety_gates": has_all(
            cpe_text,
            ("Do not implement from `main`", "TASK EXECUTION CONTRACT", "test-driven-development"),
        ),
        "audit_tools": has_all(cpe_text, ("prompt_audit", "graphify_audit", "validate_state.py")),
    }


def score_direction(
    name: str,
    superpowers_ok: bool,
    cpe_ok: bool,
    cpe: dict[str, bool],
) -> tuple[dict[str, int], list[str], list[str]]:
    if name == "cpe_primary":
        scores = {
            "superpowers_alignment": 2 if superpowers_ok else 1,
            "state_recoverability": 5 if cpe["stateful_runs"] else 2,
            "implementation_quality": 3 if cpe["safety_gates"] else 2,
            "operator_cost": 2,
            "mode_coverage": 5 if cpe["mode_coverage"] else 2,
            "migration_risk": 4 if cpe_ok else 2,
        }
        strengths = ["preserves CPE state, prompt, headless, resume, and audit behavior"]
        why_not = [
            "duplicates the current Superpowers implementation and review loop",
            "keeps CPE responsible for behavior that Superpowers now specifies more directly",
        ]
        return scores, strengths, why_not

    if name == "superpowers_native_only":
        scores = {
            "superpowers_alignment": 5 if superpowers_ok else 1,
            "state_recoverability": 2,
            "implementation_quality": 5 if superpowers_ok else 2,
            "operator_cost": 4,
            "mode_coverage": 2,
            "migration_risk": 2,
        }
        strengths = ["matches the current Superpowers implementation loop directly"]
        why_not = [
            "drops CPE prompt, handoff, headless, resume, and run-inspection surfaces too abruptly",
            "does not preserve CPE state artifacts needed for audit and recovery",
        ]
        return scores, strengths, why_not

    scores = {
        "superpowers_alignment": 5 if superpowers_ok else 1,
        "state_recoverability": 5 if cpe["stateful_runs"] else 2,
        "implementation_quality": 5 if superpowers_ok and cpe["safety_gates"] else 2,
        "operator_cost": 4,
        "mode_coverage": 5 if cpe["mode_coverage"] else 2,
        "migration_risk": 5 if cpe_ok else 2,
    }
    strengths = [
        "uses current Superpowers execution contracts for approved implementation plans",
        "keeps CPE state, prompt, handoff, headless, resume, and audit infrastructure",
        "reduces duplicated orchestration without removing existing safety gates",
    ]
    return scores, strengths, []


def rank_directions(directions: dict[str, dict[str, Any]]) -> None:
    ordered = sorted(
        directions.items(),
        key=lambda item: (
            -item[1]["total"],
            -item[1]["scores"]["superpowers_alignment"],
            -item[1]["scores"]["implementation_quality"],
            -item[1]["scores"]["migration_risk"],
            item[0],
        ),
    )
    for index, (name, _) in enumerate(ordered, start=1):
        directions[name]["rank"] = index


def build_payload(superpowers_root: Path, skill_root: Path) -> dict[str, Any]:
    superpowers = load_superpowers(superpowers_root)
    cpe_text = load_cpe(skill_root)
    required = required_contracts(superpowers)
    cpe = cpe_contracts(cpe_text)
    superpowers_ok = all(required.values())
    cpe_ok = all(cpe.values())

    directions: dict[str, dict[str, Any]] = {}
    for name in ("cpe_primary", "superpowers_native_only", "thin_stateful_bridge"):
        scores, strengths, why_not = score_direction(name, superpowers_ok, cpe_ok, cpe)
        directions[name] = {
            "scores": scores,
            "total": sum(scores[criterion] for criterion in CRITERIA),
            "strengths": strengths,
            "why_not_best": why_not,
        }

    rank_directions(directions)
    winner = min(directions, key=lambda key: directions[key]["rank"])
    passed = superpowers_ok and cpe_ok and winner == "thin_stateful_bridge"
    return {
        "schema_version": "1",
        "passed": passed,
        "superpowers_root": str(superpowers_root),
        "skill_root": str(skill_root),
        "required_contracts": required,
        "cpe_contracts": cpe,
        "criteria": list(CRITERIA),
        "directions": directions,
        "winner": winner,
        "recommended_direction": winner,
        "explanation": (
            "Use CPE as a thin stateful bridge: prefer current Superpowers execution for "
            "approved interactive implementation plans while retaining CPE state, prompt, "
            "handoff, headless, resume, and audit surfaces."
        )
        if winner == "thin_stateful_bridge"
        else "Required contracts are missing; do not change the routing default yet.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--superpowers-root", required=True, help="Directory containing Superpowers skill folders")
    parser.add_argument("--skill-root", required=True, help="kws-codex-plan-executor skill root")
    args = parser.parse_args()

    payload = build_payload(Path(args.superpowers_root), Path(args.skill_root))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
