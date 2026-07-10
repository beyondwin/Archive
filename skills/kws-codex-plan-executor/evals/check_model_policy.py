#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from cpe_runtime.model_policy import CORE_ROUTE, SCOUT_ROUTE, PolicyError, launcher_argv, route_for


def main() -> int:
    checks = {
        "core_route": (CORE_ROUTE.model, CORE_ROUTE.reasoning) == ("gpt-5.6-sol", "high"),
        "scout_route": (SCOUT_ROUTE.model, SCOUT_ROUTE.reasoning) == ("gpt-5.6-terra", "high"),
        "core_implementation": route_for("implementation", read_only=False, verdict_capable=True) == CORE_ROUTE,
        "safe_scout": route_for("scout", read_only=True, verdict_capable=False) == SCOUT_ROUTE,
        "launcher": launcher_argv(CORE_ROUTE, Path("/tmp/worktree"), sandbox="workspace-write") == [
            "codex", "exec", "--json", "--model", "gpt-5.6-sol",
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
    payload = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
