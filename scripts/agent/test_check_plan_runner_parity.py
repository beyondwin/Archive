from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("check-plan-runner-parity.py")
SPEC = importlib.util.spec_from_file_location("check_plan_runner_parity", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PARITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARITY)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class ParityInvariantTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.run_root = self.root / "run"
        self.worktree = self.root / "worktree"
        self.run_root.mkdir()
        self.worktree.mkdir()
        self.head = "a" * 40
        executable = Path("/usr/bin/true").resolve()
        metadata = executable.stat()
        executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        self.identity = {
            "argv": ["/usr/bin/true"],
            "candidate_head": self.head,
            "command_role": "final",
            "cwd": str(self.worktree),
            "environment_fingerprint": "b" * 64,
            "executable_identity": {
                "path": str(executable),
                "sha256": executable_digest,
                "mode": metadata.st_mode,
                "size": metadata.st_size,
            },
            "input_digest": "c" * 64,
            "worktree_digest": "d" * 64,
        }
        self.final_set = {
            "kind": "commands",
            "candidate_head": self.head,
            "commands": [
                {
                    "command_id": "required",
                    "command_role": "final",
                    "argv": ["/usr/bin/true"],
                    "cwd": ".",
                    "input_digest": "c" * 64,
                    "deadline_seconds": 10,
                }
            ],
        }
        self.set_ref = self.put("final_verification_set", self.final_set)
        self.receipt = {
            "schema_version": 1,
            "identity": self.identity,
            "identity_digest": hashlib.sha256(canonical(self.identity)).hexdigest(),
            "outcome": "success",
            "exit_code": 0,
            "process": {},
            "stdout_tail": "",
            "stderr_tail": "",
        }
        self.receipt_ref = self.put("verification_receipt", self.receipt)
        self.review = {
            "status": "reviewed",
            "candidate_head": self.head,
            "review_head": self.head,
            "verification_set_digest": self.set_ref["digest"],
            "open_findings": [],
            "open_obligation_ids": [],
            "no_applicable_verification_approved": False,
        }
        self.review_ref = self.put("final_review_receipt", self.review)
        self.handoff = {
            "status": "ready_for_integration",
            "candidate_head": self.head,
            "review_head": self.head,
            "verification_set_digest": self.set_ref["digest"],
            "verification_receipts": [self.receipt_ref],
            "review_receipt": self.review_ref,
            "integration": "not_observed",
        }
        self.handoff_ref = self.put("branch_handoff", self.handoff)
        self.state = {
            "status": "ready_for_integration",
            "integration": "not_observed",
            "artifact_refs": [
                self.set_ref,
                self.receipt_ref,
                self.review_ref,
                self.handoff_ref,
            ],
            "finalization": {
                "candidate_head": self.head,
                "review_head": self.head,
                "verification_set_digest": self.set_ref["digest"],
            },
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def put(self, kind: str, payload: object) -> dict[str, str]:
        encoded = canonical(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        relative = Path("artifacts") / kind / f"{digest}.json"
        target = self.run_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        return {
            "kind": kind,
            "digest": digest,
            "relative_path": str(relative),
        }

    def test_ready_evidence_requires_every_command_and_matching_handoff(self) -> None:
        summary = PARITY._validate_ready_evidence(
            self.state, self.run_root, self.worktree, self.head
        )
        self.assertEqual(summary["required_receipt_count"], 1)
        self.assertTrue(summary["all_required_receipts"])
        self.assertTrue(summary["final_head_equal"])
        self.assertTrue(summary["review_approved"])

        empty_set = dict(self.final_set, commands=[])
        empty_ref = self.put("final_verification_set", empty_set)
        broken = dict(self.state)
        broken["artifact_refs"] = [
            empty_ref,
            self.receipt_ref,
            self.review_ref,
            self.handoff_ref,
        ]
        broken["finalization"] = dict(
            self.state["finalization"], verification_set_digest=empty_ref["digest"]
        )
        with self.assertRaisesRegex(PARITY.ParityFailure, "nonempty"):
            PARITY._validate_ready_evidence(
                broken, self.run_root, self.worktree, self.head
            )

        wrong_head_set = dict(self.final_set, candidate_head="9" * 40)
        wrong_head_ref = self.put("final_verification_set", wrong_head_set)
        wrong_head = dict(self.state)
        wrong_head["artifact_refs"] = [
            wrong_head_ref,
            self.receipt_ref,
            self.review_ref,
            self.handoff_ref,
        ]
        wrong_head["finalization"] = dict(
            self.state["finalization"],
            verification_set_digest=wrong_head_ref["digest"],
        )
        with self.assertRaisesRegex(PARITY.ParityFailure, "command set HEAD"):
            PARITY._validate_ready_evidence(
                wrong_head, self.run_root, self.worktree, self.head
            )

    def test_receipt_reference_and_executable_identity_are_fail_closed(self) -> None:
        normalized = PARITY._normalized_receipts(
            self.state, self.run_root, self.worktree
        )
        self.assertEqual(normalized[0]["outcome"], "success")

        receipt_path = self.run_root / self.receipt_ref["relative_path"]
        receipt_path.write_bytes(canonical(dict(self.receipt, outcome="failed")))
        with self.assertRaisesRegex(PARITY.ParityFailure, "digest"):
            PARITY._normalized_receipts(self.state, self.run_root, self.worktree)

        receipt_path.write_bytes(canonical(self.receipt))
        bad_identity = dict(self.identity)
        bad_identity["executable_identity"] = dict(
            self.identity["executable_identity"], unexpected=True
        )
        bad_receipt = dict(
            self.receipt,
            identity=bad_identity,
            identity_digest=hashlib.sha256(canonical(bad_identity)).hexdigest(),
        )
        bad_ref = self.put("verification_receipt", bad_receipt)
        broken = dict(self.state, artifact_refs=[bad_ref])
        with self.assertRaisesRegex(PARITY.ParityFailure, "executable identity"):
            PARITY._normalized_receipts(broken, self.run_root, self.worktree)

    def test_recovery_binds_exact_session_and_changed_strategy_packet(self) -> None:
        healthy = [
            {
                "action": "interrupted",
                "session_action": "fresh",
                "session_id": "00000000-0000-4000-8000-000000000001",
                "required_strategy_change": False,
                "packet_digest": "e" * 64,
            },
            {
                "action": "implemented",
                "session_action": "resume",
                "session_id": "00000000-0000-4000-8000-000000000001",
                "required_strategy_change": False,
                "packet_digest": "f" * 64,
            },
        ]
        self.assertEqual(
            PARITY._validate_recovery_evidence("healthy-resume", healthy),
            "resume",
        )
        healthy[1]["session_id"] = "00000000-0000-4000-8000-000000000002"
        with self.assertRaisesRegex(PARITY.ParityFailure, "exact captured"):
            PARITY._validate_recovery_evidence("healthy-resume", healthy)

        stalled = [
            {
                "action": "stalled",
                "session_action": "fresh",
                "session_id": "00000000-0000-4000-8000-000000000001",
                "required_strategy_change": False,
                "packet_digest": "e" * 64,
            },
            {
                "action": "implemented",
                "session_action": "fresh",
                "session_id": "00000000-0000-4000-8000-000000000002",
                "required_strategy_change": True,
                "packet_digest": "f" * 64,
            },
        ]
        self.assertEqual(
            PARITY._validate_recovery_evidence(
                "stalled-fresh-strategy", stalled
            ),
            "fresh",
        )
        stalled[1]["required_strategy_change"] = False
        with self.assertRaisesRegex(PARITY.ParityFailure, "changed-strategy"):
            PARITY._validate_recovery_evidence(
                "stalled-fresh-strategy", stalled
            )
        stalled[1]["required_strategy_change"] = True
        stalled[1]["packet_digest"] = stalled[0]["packet_digest"]
        with self.assertRaisesRegex(PARITY.ParityFailure, "distinct packet"):
            PARITY._validate_recovery_evidence(
                "stalled-fresh-strategy", stalled
            )

    def test_parity_stall_lease_allows_provider_startup_jitter(self) -> None:
        self.assertGreaterEqual(PARITY.PARITY_STALL_SECONDS, 1.5)
        self.assertLess(PARITY.PARITY_STALL_SECONDS, 2.0)


if __name__ == "__main__":
    unittest.main()
