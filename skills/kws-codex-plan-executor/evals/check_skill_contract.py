#!/usr/bin/env python3
"""Check the concise public CPE v3 skill contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True)
    args = parser.parse_args()
    text = Path(args.skill).read_text(encoding="utf-8")
    required = [
        'version: "3.0.0"', "run", "resume", "export", "prompt", "handoff",
        "validate", "reconcile", "repair", "inspect", "unsupported_schema",
        "events.jsonl", "state.json", "gpt-5.6-sol", "gpt-5.6-terra", "spec_refs",
    ]
    forbidden = ["full_spec_on_blocker", "manifest_fallback", "state remains authoritative"]
    checks = {
        "required_contract": all(item in text for item in required),
        "no_removed_contract": all(item not in text for item in forbidden),
        "concise": len(text.split()) < 1200,
    }
    payload = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
