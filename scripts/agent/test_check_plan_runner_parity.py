from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def assert_ready_outcome_survives_hostile_git_environment(
        self,
        provider: str,
    ) -> None:
        fixture = json.loads(PARITY.FIXTURE.read_text(encoding="utf-8"))
        scenario = next(
            item
            for item in fixture["scenarios"]
            if item["id"] == "ordered-two-plan-ready"
        )
        hostile_global = self.root / "hostile-global.gitconfig"
        hostile_global.write_text(
            "[user]\n"
            "\tname = Hostile Global\n"
            "\temail = hostile-global@example.test\n"
            "[init]\n"
            "\tdefaultObjectFormat = sha256\n",
            encoding="utf-8",
        )
        hostile = {
            "EMAIL": "hostile-email@example.test",
            "GIT_AUTHOR_NAME": "Hostile Author",
            "GIT_AUTHOR_EMAIL": "hostile-author@example.test",
            "GIT_AUTHOR_DATE": "2037-12-31T23:59:59+00:00",
            "GIT_COMMITTER_NAME": "Hostile Committer",
            "GIT_COMMITTER_EMAIL": "hostile-committer@example.test",
            "GIT_COMMITTER_DATE": "2038-01-01T00:00:00+00:00",
            "GIT_DEFAULT_HASH": "sha256",
            "GIT_CONFIG_GLOBAL": str(hostile_global),
            "GIT_CONFIG_SYSTEM": str(hostile_global),
            "GIT_CONFIG_NOSYSTEM": "0",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "user.name",
            "GIT_CONFIG_VALUE_0": "Hostile Inline",
            "GIT_CONFIG_KEY_1": "user.email",
            "GIT_CONFIG_VALUE_1": "hostile-inline@example.test",
            "GIT_DIR": str(self.root / "hostile.git"),
            "GIT_WORK_TREE": str(self.root / "hostile-worktree"),
            "GIT_INDEX_FILE": str(self.root / "hostile-index"),
            "GIT_OBJECT_DIRECTORY": str(self.root / "hostile-objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(
                self.root / "hostile-alternates"
            ),
            "GIT_COMMON_DIR": str(self.root / "hostile-common"),
            "GIT_CEILING_DIRECTORIES": str(self.root),
        }
        with mock.patch.dict(os.environ, hostile):
            try:
                actual = PARITY.run_provider(
                    provider,
                    scenario,
                    self.root / "parity",
                )
            except PARITY.ParityFailure as error:
                self.fail(f"hostile Git environment escaped sealing: {error}")

        self.assertEqual(
            actual,
            {
                "exit": 0,
                "status": "ready_for_integration",
                "plan_statuses": ["implemented", "implemented"],
                "handoff_heads": [
                    "bd543a5d1bb6df4281554f9203fbe5cb7092d603",
                    "f73c30696405350ab1ae7902906b14c2ef332a27",
                ],
                "verification_set_digest": (
                    "efbbd878b2b01230cd635bf195785a177"
                    "f97e1477a35cf0b1096d39ea0845755"
                ),
                "required_receipt_count": 1,
                "session_action": None,
                "integration": "not_observed",
            },
        )

    def test_codex_disposable_setup_ignores_hostile_git_environment(self) -> None:
        self.assert_ready_outcome_survives_hostile_git_environment("codex")

    def test_claude_disposable_setup_ignores_hostile_git_environment(self) -> None:
        self.assert_ready_outcome_survives_hostile_git_environment("claude")

    def test_recovery_reports_only_the_external_root_action(self) -> None:
        healthy = [
            {
                "action": "clean-interrupted",
                "session_action": "fresh",
            },
            {
                "action": "implemented",
                "session_action": "resume",
                "session_id": "provider-private-and-ignored",
            },
        ]
        self.assertEqual(
            PARITY._validate_recovery_evidence("healthy-resume", healthy),
            "resume_root",
        )

        stalled = [
            {
                "action": "stalled",
                "session_action": "fresh",
            },
            {
                "action": "implemented",
                "session_action": "fresh",
                "stream_event": "provider-private-and-ignored",
            },
        ]
        self.assertEqual(
            PARITY._validate_recovery_evidence(
                "stalled-fresh-strategy", stalled
            ),
            "fresh_root",
        )

    def test_external_parity_output_excludes_provider_private_structure(self) -> None:
        handoff_one = self.put(
            "plan_handoff",
            {
                "plan_index": 0,
                "head_commit": "1" * 40,
                "verification_set_digest": "2" * 64,
                "provider_private": {"session_id": "not-a-parity-field"},
            },
        )
        accepted_set = self.put(
            "run_verification_set",
            {
                "kind": "commands",
                "candidate_head": self.head,
                "commands": [self.final_set["commands"][0]],
                "private_review_shape": {"findings": ["not-compared"]},
            },
        )
        handoff_two = self.put(
            "plan_handoff",
            {
                "plan_index": 1,
                "head_commit": self.head,
                "verification_set_digest": accepted_set["digest"],
                "private_finalization_shape": {"review_receipt": "not-compared"},
            },
        )
        state = {
            "status": "ready_for_integration",
            "integration": "not_observed",
            "plans": [
                {
                    "status": "implemented",
                    "handoff_digest": handoff_one["digest"],
                },
                {
                    "status": "implemented",
                    "handoff_digest": handoff_two["digest"],
                },
            ],
            "artifact_refs": [handoff_one, accepted_set, handoff_two],
            "sessions": [{"session_id": "not-compared"}],
            "task_ledger": [{"status": "reported_done"}],
            "finalization": {"review_head": "not-compared"},
        }

        self.assertEqual(
            PARITY._external_outcome(
                exit_code=0,
                state=state,
                run_root=self.run_root,
                session_action="resume_root",
            ),
            {
                "exit": 0,
                "status": "ready_for_integration",
                "plan_statuses": ["implemented", "implemented"],
                "handoff_heads": ["1" * 40, self.head],
                "verification_set_digest": hashlib.sha256(
                    canonical(
                        {
                            "candidate_head": self.head,
                            "commands": self.final_set["commands"],
                        }
                    )
                ).hexdigest(),
                "required_receipt_count": 1,
                "session_action": "resume_root",
                "integration": "not_observed",
            },
        )

    def test_expected_outcome_rejects_valid_but_different_heads_and_digest(
        self,
    ) -> None:
        expected = {
            "exit": 0,
            "status": "ready_for_integration",
            "plan_statuses": ["implemented", "implemented"],
            "handoff_heads": ["1" * 40, "2" * 40],
            "verification_set_digest": "3" * 64,
            "required_receipt_count": 1,
            "session_action": None,
            "integration": "not_observed",
        }
        differences = {
            "heads": dict(
                expected,
                handoff_heads=["4" * 40, "5" * 40],
            ),
            "digest": dict(
                expected,
                verification_set_digest="6" * 64,
            ),
        }
        for field, different in differences.items():
            with self.subTest(field=field), self.assertRaisesRegex(
                PARITY.ParityFailure,
                "expectation mismatch",
            ):
                PARITY._require_expected_outcome(
                    "codex",
                    expected,
                    different,
                )

    def test_active_root_fixtures_are_version_two_external_contracts(self) -> None:
        contract = json.loads(PARITY.CONTRACT.read_text(encoding="utf-8"))
        fixture = json.loads(PARITY.FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(contract["contract_version"], 2)
        self.assertEqual(contract["state_format_version"], 2)
        self.assertEqual(
            contract["parity_fields"],
            [
                "exit",
                "status",
                "plan_statuses",
                "handoff_heads",
                "verification_set_digest",
                "required_receipt_count",
                "session_action",
                "integration",
            ],
        )
        self.assertNotIn("task_statuses", contract)
        self.assertEqual(fixture["fixture_version"], 2)
        by_id = {scenario["id"]: scenario for scenario in fixture["scenarios"]}
        self.assertEqual(
            by_id["healthy-resume"]["fake_sequence"][0],
            "clean-interrupted",
        )
        for scenario in fixture["scenarios"]:
            self.assertNotIn("finalized", scenario["fake_sequence"])
            self.assertIn("expected_handoff_heads", scenario)
            self.assertIn("expected_verification_set_digest", scenario)
            self.assertEqual(
                list(PARITY._expected(scenario)),
                contract["parity_fields"],
            )
            self.assertFalse(
                {
                    "expected_task_statuses",
                    "expected_failure",
                    "expected_all_required_receipts",
                    "expected_final_head_equal",
                    "expected_review_outcome",
                    "expected_review_approved",
                }
                & scenario.keys()
            )

    def test_parity_stall_lease_allows_provider_startup_jitter(self) -> None:
        self.assertGreaterEqual(PARITY.PARITY_STALL_SECONDS, 1.5)
        self.assertLess(PARITY.PARITY_STALL_SECONDS, 2.0)

    def test_fake_codex_home_is_private_bounded_and_self_contained(self) -> None:
        ambient = self.root / "ambient-codex-home"
        ambient.mkdir()
        (ambient / "auth.json").write_text(
            json.dumps({"OPENAI_API_KEY": "must-not-copy"}), encoding="utf-8"
        )
        environment = {
            "CODEX_HOME": str(ambient),
            "OPENAI_API_KEY": "must-not-copy",
            "PATH": os.environ["PATH"],
        }

        codex_home = PARITY._prepare_fake_codex_environment(
            self.root / "scenario", environment
        )

        self.assertEqual(codex_home, self.root / "scenario" / "fake-codex-home")
        self.assertEqual(environment["CODEX_HOME"], str(codex_home))
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertEqual(stat.S_IMODE(codex_home.stat().st_mode), 0o700)
        relative_files = {
            path.relative_to(codex_home)
            for path in codex_home.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            relative_files,
            {Path("auth.json"), *PARITY.CODEX_SDD_RELATIVE_PATHS},
        )
        for path in relative_files:
            target = codex_home / path
            self.assertFalse(target.is_symlink())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertGreater(target.stat().st_size, 0)
            self.assertLessEqual(target.stat().st_size, PARITY.FAKE_FILE_LIMIT)
            self.assertNotIn("must-not-copy", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
