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
REPO_ROOT = SKILL_ROOT.parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.public_result import (
    trusted_release_repository_root,
    validate_release_evidence_root,
)
from cpe_runtime.quality_v4 import (
    build_v4_release_evidence_payloads,
    canonical_v4_envelope_map,
)
from live_migration.compiler import compile_v4_manifest


def canonical_sha256(payload: object) -> str:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def write_valid_fixture(root: Path, commit: str, tree: str) -> None:
    compiled = compile_v4_manifest(commit=commit, run_id="release-validator-fixture")
    compiled["implementation_tree"] = tree
    compiled["implementation_patch_sha256"] = "a" * 64
    envelope_sha256 = canonical_v4_envelope_map(compiled)
    aggregate = {
        "schema_version": "cpe-quality-aggregate.v4",
        "run_id": compiled["run_id"],
        "manifest_sha256": compiled["manifest_sha256"],
        "implementation_commit": commit,
        "implementation_tree": tree,
        "implementation_patch_sha256": "a" * 64,
        "credentialed_call_count": 17,
        "policy_outcome_count": 7,
        "duplicate_slot_count": 0,
        "pending_slot_count": 0,
        "envelope_sha256": envelope_sha256,
        "release_gate": {
            "passed": True,
            "failures": [],
            "control_completed": 8,
            "candidate_completed": 8,
        },
    }
    dogfood = {
        "schema_version": "cpe.dogfood-result.v4",
        "status": "passed",
        "run_ids_created": 1,
        "model_attempts": 6,
        "max_same_root_repairs": 2,
        "verified_checkpoints": ["a" * 40],
        "elapsed_seconds": 3600,
        "source_checkout_unchanged": True,
        "runtime_patch_required": False,
    }
    payloads = build_v4_release_evidence_payloads(compiled, aggregate, dogfood)
    for name, payload in payloads.items():
        (root / name).write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
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

    with tempfile.TemporaryDirectory(prefix="cpe-v4-release-evidence-") as raw:
        root = Path(raw)
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
        (repo / "code.txt").write_text("reviewed\n", encoding="utf-8")
        subprocess.run(["git", "add", "code.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "reviewed checkpoint"], cwd=repo, check=True)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True, stdout=subprocess.PIPE, check=True
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, text=True, stdout=subprocess.PIPE, check=True
        ).stdout.strip()
        empty = root / "empty"
        empty.mkdir()
        rejected = subprocess.run(
            [
                sys.executable,
                __file__,
                "--evidence-root",
                str(empty),
                "--implementation-commit",
                commit,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert rejected.returncode != 0
        assert "release_evidence_missing" in rejected.stdout
        missing_pin = subprocess.run(
            [sys.executable, __file__, "--evidence-root", str(empty)],
            text=True,
            stdout=subprocess.PIPE,
            check=False,
        )
        assert missing_pin.returncode != 0
        assert "implementation_commit_required" in missing_pin.stdout

        public_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        public_tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        public_valid = root / "public-valid"
        public_valid.mkdir()
        write_valid_fixture(public_valid, public_commit, public_tree)
        public_invocation = subprocess.run(
            [
                sys.executable,
                __file__,
                "--evidence-root",
                str(public_valid),
                "--implementation-commit",
                public_commit,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert public_invocation.returncode == 0, public_invocation.stdout
        valid = root / "valid"
        valid.mkdir()
        write_valid_fixture(valid, commit, tree)
        report = validate_release_evidence_root(valid, commit, repo)
        assert report["passed"] is True, report
        mismatched = validate_release_evidence_root(valid, "d" * 40, repo)
        assert mismatched["passed"] is False
        assert "implementation_commit_invalid" in mismatched["errors"]
        replacements = {
            "checkpoint.json": ('"commit":"' + commit + '"', '"commit":"short"'),
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
            changed = validate_release_evidence_root(valid, commit, repo)
            assert changed["passed"] is False, (filename, changed)
            tampered.write_text(original, encoding="utf-8")

        result_path = valid / "result.json"
        original_result = result_path.read_text(encoding="utf-8")
        result_payload = json.loads(original_result)
        first_envelope = sorted(result_payload["envelope_sha256"])[0]
        result_payload["envelope_sha256"][first_envelope] = "f" * 64
        result_path.write_text(
            json.dumps(result_payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        substituted = validate_release_evidence_root(valid, commit, repo)
        assert substituted["passed"] is False
        assert "launch_envelope_binding_invalid" in substituted["errors"]
        result_path.write_text(original_result, encoding="utf-8")

        # Closed schemas reject a digest-consistent unknown field, including a
        # caller-controlled absolute hidden-oracle path and a forged privacy pass.
        dogfood_path = valid / "dogfood-result.json"
        checkpoint_path = valid / "checkpoint.json"
        privacy_path = valid / "privacy-audit.json"
        original_dogfood = dogfood_path.read_text(encoding="utf-8")
        original_checkpoint = checkpoint_path.read_text(encoding="utf-8")
        original_privacy = privacy_path.read_text(encoding="utf-8")
        dogfood_payload = json.loads(original_dogfood)
        dogfood_payload["debug_note"] = "/private/tmp/oracle/expected.json"
        dogfood_path.write_text(
            json.dumps(dogfood_payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        privacy_payload = json.loads(original_privacy)
        privacy_payload["passed"] = True
        privacy_payload["findings"] = []
        privacy_path.write_text(
            json.dumps(privacy_payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        checkpoint_payload = json.loads(original_checkpoint)
        checkpoint_payload["dogfood_sha256"] = canonical_sha256(dogfood_payload)
        checkpoint_payload["privacy_sha256"] = canonical_sha256(privacy_payload)
        checkpoint_path.write_text(
            json.dumps(checkpoint_payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        hidden_oracle = validate_release_evidence_root(valid, commit, repo)
        assert hidden_oracle["passed"] is False, hidden_oracle
        assert "release_evidence_schema_invalid" in hidden_oracle["errors"]
        assert "privacy_audit_failed" in hidden_oracle["errors"]
        dogfood_path.write_text(original_dogfood, encoding="utf-8")
        checkpoint_path.write_text(original_checkpoint, encoding="utf-8")
        privacy_path.write_text(original_privacy, encoding="utf-8")

        for filename in (
            "checkpoint.json",
            "manifest.json",
            "result.json",
            "privacy-audit.json",
            "dogfood-result.json",
        ):
            path = valid / filename
            original = path.read_text(encoding="utf-8")
            payload = json.loads(original)
            payload["debug_note"] = "safe-looking-extra"
            path.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            closed = validate_release_evidence_root(valid, commit, repo)
            assert closed["passed"] is False, (filename, closed)
            assert "release_evidence_schema_invalid" in closed["errors"]
            path.write_text(original, encoding="utf-8")

        rewritten = root / "rewritten"
        rewritten.mkdir()
        write_valid_fixture(rewritten, "d" * 40, "e" * 40)
        arbitrary = validate_release_evidence_root(rewritten, "d" * 40, repo)
        assert arbitrary["passed"] is False, arbitrary
        assert "implementation_commit_invalid" in arbitrary["errors"], arbitrary
    print(json.dumps({"passed": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
