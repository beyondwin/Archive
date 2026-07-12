#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from cpe_runtime.model_policy import (
    CORE_ROUTE,
    SCOUT_ROUTE,
    PolicyError,
    launcher_argv,
    policy_payload,
    route_for,
)


def main() -> int:
    checks = {
        "v4_policy_payload": policy_payload() == {
            "version": "cpe.model-policy.v4",
            "core": {"model": "gpt-5.6-sol", "reasoning": "high"},
            "scout": {"model": "gpt-5.6-terra", "reasoning": "high"},
        },
        "core_route": (CORE_ROUTE.model, CORE_ROUTE.reasoning) == ("gpt-5.6-sol", "high"),
        "scout_route": (SCOUT_ROUTE.model, SCOUT_ROUTE.reasoning) == ("gpt-5.6-terra", "high"),
        "core_implementation": route_for("implementation", read_only=False, verdict_capable=True) == CORE_ROUTE,
        "safe_scout": route_for("scout", read_only=True, verdict_capable=False) == SCOUT_ROUTE,
        "launcher": launcher_argv(CORE_ROUTE, Path("/tmp/worktree"), sandbox="workspace-write") == [
            "codex", "exec", "--ignore-user-config", "--json", "--model", "gpt-5.6-sol",
            "-c", 'model_reasoning_effort="high"', "--sandbox", "workspace-write",
            "-C", "/tmp/worktree", "-",
        ],
    }
    for read_only, verdict_capable in ((False, False), (True, True), (False, True)):
        try:
            route_for("scout", read_only=read_only, verdict_capable=verdict_capable)
        except PolicyError:
            continue
        checks[f"unsafe_scout_rejected_{read_only}_{verdict_capable}"] = False
    checks["no_fallback_or_reasoning_downgrade"] = all(
        forbidden not in json.dumps(policy_payload(), sort_keys=True).lower()
        for forbidden in ("fallback", '"medium"', '"low"')
    )
    payload = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
