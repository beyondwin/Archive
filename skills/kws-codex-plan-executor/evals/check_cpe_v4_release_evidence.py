#!/usr/bin/env python3
"""Public validator CLI and cost-free CPE v4 release transaction self-check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.public_result import (
    trusted_release_repository_root,
    validate_release_evidence_root,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root")
    parser.add_argument("--implementation-commit")
    args = parser.parse_args()
    if args.evidence_root:
        if not args.implementation_commit:
            print(json.dumps({"passed": False, "errors": ["implementation_commit_required"]}))
            return 1
        report = validate_release_evidence_root(
            Path(args.evidence_root),
            args.implementation_commit,
            trusted_release_repository_root(Path(__file__)),
        )
        print(json.dumps(report, sort_keys=True))
        return 0 if report["passed"] else 1

    from check_release_transaction_v4 import main as check_release_transaction

    return check_release_transaction()


if __name__ == "__main__":
    raise SystemExit(main())
