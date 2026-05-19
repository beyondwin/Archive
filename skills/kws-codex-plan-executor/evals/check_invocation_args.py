#!/usr/bin/env python3
"""Deterministic checks for invocation argument parsing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_args(args_text: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "parse_invocation_args.py"
    result = subprocess.run(
        [sys.executable, str(script), "--args", args_text],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}
    return result, payload


def main() -> int:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    default_result, default_payload = run_args("plan=a.md")
    checks["default_subagents_on"] = (
        default_result.returncode == 0
        and default_payload.get("values", {}).get("subagents") == "on"
        and default_payload.get("sources", {}).get("subagents") == "default"
    )
    if not checks["default_subagents_on"]:
        failures.append("subagents should default to on")

    result, payload = run_args("plan=a.md spec=s.md 순차")
    checks["sequential_sets_parallel_off"] = (
        result.returncode == 0
        and payload.get("values", {}).get("plan") == "a.md"
        and payload.get("values", {}).get("spec") == "s.md"
        and payload.get("values", {}).get("parallel") == "off"
        and payload.get("values", {}).get("subagents") == "on"
    )
    if not checks["sequential_sets_parallel_off"]:
        failures.append("순차 should resolve parallel=off while preserving explicit plan/spec and default subagents=on")

    opus_result, opus = run_args("오푸스로")
    checks["korean_particle_stripped_opus"] = (
        opus_result.returncode == 0 and opus.get("values", {}).get("implementer_model") == "opus"
    )
    if not checks["korean_particle_stripped_opus"]:
        failures.append("오푸스로 should resolve implementer_model=opus after particle stripping")

    conflict_result, _ = run_args("subagents=off 병렬")
    checks["explicit_nl_conflict_halts"] = (
        conflict_result.returncode != 0 and "conflict" in (conflict_result.stderr + conflict_result.stdout).lower()
    )
    if not checks["explicit_nl_conflict_halts"]:
        failures.append("explicit subagents=off plus NL 병렬 should halt with conflict")

    unknown_result, _ = run_args("unknown=value")
    checks["unknown_key_fails"] = (
        unknown_result.returncode != 0 and "unknown argument key" in (unknown_result.stderr + unknown_result.stdout)
    )
    if not checks["unknown_key_fails"]:
        failures.append("unknown key=value should fail clearly")

    echo_result, echo_payload = run_args("plan=p.md 병렬 슬라이스")
    echo = echo_payload.get("echo", "")
    checks["echo_contains_required_fields"] = (
        echo_result.returncode == 0
        and "Parsed: 1 plan [p]" in echo
        and "mode=interactive" in echo
        and "subagents=on" in echo
        and "context_mode=sliced" in echo
        and "manifest_fallback=full_spec_on_blocker" in echo
    )
    if not checks["echo_contains_required_fields"]:
        failures.append("echo line should include plan count, mode, subagents, context mode, and fallback policy")

    payload_out = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload_out, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
