#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.public_result import validate_release_evidence_root


def canonical_sha256(payload: object) -> str:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def write_valid_fixture(root: Path) -> None:
    manifest = {
        "schema_version": "cpe-quality-manifest.v4",
        "implementation_commit": "b" * 40,
        "implementation_tree": "c" * 40,
        "credentialed_call_count": 17,
        "policy_outcome_count": 7,
    }
    result = {
        "schema_version": "cpe-quality-result.v4",
        "implementation_commit": "b" * 40,
        "implementation_tree": "c" * 40,
        "manifest_sha256": canonical_sha256(manifest),
        "credentialed_call_count": 17,
        "policy_outcome_count": 7,
        "release_gate": {"passed": True},
    }
    privacy = {"schema_version": "cpe.privacy-audit.v4", "passed": True, "findings": []}
    dogfood = {
        "schema_version": "cpe.dogfood-result.v4",
        "run_ids_created": 1,
        "model_attempts": 6,
        "max_same_root_repairs": 2,
        "verified_checkpoints": ["a" * 40],
        "elapsed_seconds": 3600,
        "source_checkout_unchanged": True,
        "runtime_patch_required": False,
    }
    checkpoint = {
        "schema_version": "cpe.code-checkpoint.v4",
        "commit": "b" * 40,
        "tree": "c" * 40,
        "manifest_sha256": canonical_sha256(manifest),
        "result_sha256": canonical_sha256(result),
        "privacy_sha256": canonical_sha256(privacy),
        "dogfood_sha256": canonical_sha256(dogfood),
    }
    for name, payload in {
        "checkpoint.json": checkpoint,
        "manifest.json": manifest,
        "result.json": result,
        "privacy-audit.json": privacy,
        "dogfood-result.json": dogfood,
    }.items():
        (root / name).write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root")
    args = parser.parse_args()
    if args.evidence_root:
        report = validate_release_evidence_root(Path(args.evidence_root))
        print(json.dumps(report, sort_keys=True))
        return 0 if report["passed"] else 1

    with tempfile.TemporaryDirectory(prefix="cpe-v4-release-evidence-") as raw:
        root = Path(raw)
        empty = root / "empty"
        empty.mkdir()
        rejected = subprocess.run(
            [sys.executable, __file__, "--evidence-root", str(empty)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert rejected.returncode != 0
        assert "release_evidence_missing" in rejected.stdout
        valid = root / "valid"
        valid.mkdir()
        write_valid_fixture(valid)
        report = validate_release_evidence_root(valid)
        assert report["passed"] is True, report
        replacements = {
            "checkpoint.json": ('"commit":"' + "b" * 40 + '"', '"commit":"short"'),
            "manifest.json": ('"credentialed_call_count":17', '"credentialed_call_count":16'),
            "result.json": ('"passed":true', '"passed":false'),
            "privacy-audit.json": ('"passed":true', '"passed":false'),
            "dogfood-result.json": ('"model_attempts":6', '"model_attempts":7'),
        }
        for filename, (before, after) in replacements.items():
            tampered = valid / filename
            original = tampered.read_text(encoding="utf-8")
            assert before in original, (filename, before)
            tampered.write_text(original.replace(before, after, 1), encoding="utf-8")
            changed = validate_release_evidence_root(valid)
            assert changed["passed"] is False, (filename, changed)
            tampered.write_text(original, encoding="utf-8")
    print(json.dumps({"passed": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
