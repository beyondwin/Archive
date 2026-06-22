#!/usr/bin/env python3
"""Check CPE routing against the current Superpowers workflow contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run_audit(superpowers_root: Path, skill_root: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = skill_root / "scripts" / "audit_superpowers_compatibility.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--superpowers-root",
            str(superpowers_root),
            "--skill-root",
            str(skill_root),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
    return result, payload


def copy_superpowers_fixture(source: Path, destination: Path) -> None:
    required = [
        "brainstorming",
        "writing-plans",
        "subagent-driven-development",
        "verification-before-completion",
    ]
    for name in required:
        src = source / name
        dst = destination / name
        shutil.copytree(src, dst)


def main() -> int:
    skill_root = Path(__file__).resolve().parents[1]
    default_superpowers = Path.home() / ".codex" / "skills"
    failures: list[str] = []
    checks: dict[str, bool] = {}

    result, payload = run_audit(default_superpowers, skill_root)
    directions = payload.get("directions", {}) if isinstance(payload, dict) else {}
    contracts = payload.get("required_contracts", {}) if isinstance(payload, dict) else {}

    checks["audit_passes_current_superpowers"] = result.returncode == 0 and payload.get("passed") is True
    if not checks["audit_passes_current_superpowers"]:
        failures.append("current Superpowers compatibility audit should pass")

    checks["thin_bridge_wins"] = (
        payload.get("recommended_direction") == "thin_stateful_bridge"
        and directions.get("thin_stateful_bridge", {}).get("rank") == 1
    )
    if not checks["thin_bridge_wins"]:
        failures.append("thin_stateful_bridge should be the recommended direction")

    checks["alternatives_rank_lower"] = (
        directions.get("cpe_primary", {}).get("rank", 0) > 1
        and directions.get("superpowers_native_only", {}).get("rank", 0) > 1
    )
    if not checks["alternatives_rank_lower"]:
        failures.append("cpe_primary and superpowers_native_only should rank below the thin bridge")

    for key in (
        "brainstorming_hard_gate",
        "writing_plans_header",
        "subagent_review_loop",
        "verification_before_completion",
    ):
        checks[f"contract_{key}"] = contracts.get(key) is True
        if not checks[f"contract_{key}"]:
            failures.append(f"required Superpowers contract missing: {key}")

    checks["explains_tradeoffs"] = all(
        isinstance(directions.get(name, {}).get("why_not_best"), list)
        for name in ("cpe_primary", "superpowers_native_only")
    )
    if not checks["explains_tradeoffs"]:
        failures.append("audit should explain why losing directions are not best")

    with tempfile.TemporaryDirectory(prefix="cpe-superpowers-compat-") as temp:
        fixture_root = Path(temp) / "skills"
        copy_superpowers_fixture(default_superpowers, fixture_root)
        brainstorming = fixture_root / "brainstorming" / "SKILL.md"
        brainstorming.write_text(
            brainstorming.read_text(encoding="utf-8").replace("<HARD-GATE>", "<SOFT-GATE>", 1),
            encoding="utf-8",
        )
        missing_result, missing_payload = run_audit(fixture_root, skill_root)
        checks["missing_required_contract_fails"] = (
            missing_result.returncode != 0
            and missing_payload.get("passed") is False
            and missing_payload.get("required_contracts", {}).get("brainstorming_hard_gate") is False
        )
        if not checks["missing_required_contract_fails"]:
            failures.append("audit should fail when a required Superpowers contract is missing")

    payload_out = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload_out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
