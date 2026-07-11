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

    checks["default_has_no_explicit_delegation_intent"] = (
        default_result.returncode == 0
        and default_payload.get("intent", {}).get("explicit_delegation_request") is False
        and default_payload.get("intent", {}).get("delegation_hint") is None
    )
    if not checks["default_has_no_explicit_delegation_intent"]:
        failures.append("default subagents=on should not be treated as explicit user delegation intent")

    parallel_result, parallel_payload = run_args("plan=a.md 병렬")
    checks["nl_parallel_sets_explicit_delegation_intent"] = (
        parallel_result.returncode == 0
        and parallel_payload.get("values", {}).get("subagents") == "on"
        and parallel_payload.get("intent", {}).get("explicit_delegation_request") is True
        and parallel_payload.get("intent", {}).get("delegation_hint") == "병렬"
    )
    if not checks["nl_parallel_sets_explicit_delegation_intent"]:
        failures.append("NL 병렬 should mark explicit delegation intent")

    explicit_result, explicit_payload = run_args("plan=a.md subagents=on")
    checks["explicit_subagents_on_sets_delegation_intent"] = (
        explicit_result.returncode == 0
        and explicit_payload.get("sources", {}).get("subagents") == "subagents=value"
        and explicit_payload.get("intent", {}).get("explicit_delegation_request") is True
        and explicit_payload.get("intent", {}).get("delegation_hint") == "subagents=on"
    )
    if not checks["explicit_subagents_on_sets_delegation_intent"]:
        failures.append("explicit subagents=on should mark explicit delegation intent")

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

    forbidden_inputs = ["model=gpt-5.6-sol", "reasoning=xhigh", "implementer_model=opus", "오푸스로", "gpt-5.5 only"]
    checks["model_overrides_rejected"] = all(
        run_args(item)[0].returncode != 0
        and "fixed to Sol/high" in run_args(item)[0].stderr
        for item in forbidden_inputs
    )
    if not checks["model_overrides_rejected"]:
        failures.append("model overrides and natural-language model hints must be rejected")

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
    )
    if not checks["echo_contains_required_fields"]:
        failures.append("echo line should include plan count, mode, subagents, context mode, and fallback policy")

    cpe = Path(__file__).resolve().parents[1] / "scripts" / "cpe.py"
    run_help = subprocess.run(
        [sys.executable, str(cpe), "run", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    export_help = subprocess.run(
        [sys.executable, str(cpe), "export", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    checks["public_cli_modes_are_explicit"] = (
        run_help.returncode == 0
        and "{interactive,headless}" in run_help.stdout
        and export_help.returncode == 0
        and "{prompt,handoff}" in export_help.stdout
    )
    if not checks["public_cli_modes_are_explicit"]:
        failures.append("public CPE run and export modes should be explicit")
    checks["public_cli_has_no_model_override"] = all(
        token not in run_help.stdout + export_help.stdout
        for token in ("--model", "--reasoning", "--profile")
    )
    if not checks["public_cli_has_no_model_override"]:
        failures.append("public CPE must not expose model or reasoning overrides")

    payload_out = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload_out, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
