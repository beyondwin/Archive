#!/usr/bin/env python3
"""Execution-runtime regression checks for the CPE v4 task cycle."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from check_scheduler_v4 import assert_first_pass, assert_repairs


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cpe-v4-execution-") as raw:
        root = Path(raw)
        assert_first_pass(root / "first-pass")
        assert_repairs(root / "repairs")
    print(
        json.dumps(
            {
                "passed": True,
                "checks": {
                    "bounded_first_pass": True,
                    "one_repair": True,
                    "two_repairs": True,
                    "third_repair_forbidden": True,
                    "disposable_acceptance": True,
                    "delta_only_repair_review": True,
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
