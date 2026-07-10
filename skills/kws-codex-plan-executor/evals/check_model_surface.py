#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def main() -> int:
    skill = Path(__file__).resolve().parents[1]
    script_dir = skill / "scripts"
    sys.path.insert(0, str(script_dir))
    module = ast.parse((script_dir / "cpe_runtime" / "model_policy.py").read_text(encoding="utf-8"))
    routes = []
    for node in module.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "Route":
                name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else ""
                routes.append(name)
    active = [
        script_dir / "cpe_runtime" / "model_policy.py",
        script_dir / "parse_invocation_args.py",
        script_dir / "cpe_runtime" / "prompt_export.py",
        skill / "templates" / "fresh-session-prompt.txt",
        skill / "evals" / "static_prompt_runner.py",
        skill / "evals" / "check_prompt.py",
        skill / "evals" / "fixtures" / "01-prompt-only.yaml",
        skill / "evals" / "fixtures" / "03-continuation.yaml",
    ]
    legacy = ("gpt-5.5", "gpt-5.3-codex-spark", "spark-scout-bullets", "luna", "xhigh", "opus", "max")
    violations = []
    for path in active:
        text = path.read_text(encoding="utf-8").lower()
        if path.name == "parse_invocation_args.py":
            text = text.split("forbidden_model_hints", 1)[0] + text.split("forbidden_model_hints", 1)[1].split("}", 1)[-1]
        for token in legacy:
            if token in text:
                violations.append(f"{path.relative_to(skill)}:{token}")
    checks = {
        "exactly_two_route_constants": sorted(routes) == ["CORE_ROUTE", "SCOUT_ROUTE"],
        "legacy_tokens_absent_from_active_surface": not violations,
    }
    payload = {"passed": all(checks.values()), "checks": checks, "violations": violations}
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
