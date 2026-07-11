#!/usr/bin/env python3
"""Cost-free contract checks for the provider-independent live oracle."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


EVALS_ROOT = Path(__file__).resolve().parent
if str(EVALS_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALS_ROOT))

from live_migration.fixtures import MaterializedFixture  # noqa: E402
from live_migration.oracle import (  # noqa: E402
    OracleInputError,
    ProcessEvidence,
    evaluate_slot,
    policy_failure_result,
)


SCHEMA_PATH = EVALS_ROOT / "live-migration" / "worker-result-schema.json"
OUTPUT_FIELDS = {
    "status",
    "summary",
    "finding_ids",
    "fact_ids",
    "block_ids",
    "changed_files",
}


class OracleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        repo = root / "repo"
        oracle_dir = root / "oracle"
        repo.mkdir()
        (repo / ".git").mkdir()
        oracle_dir.mkdir()
        (oracle_dir / "expected.json").write_text(
            json.dumps({"changed_files": ["src/example.py"], "required_ids": []})
        )
        self.fixture = MaterializedFixture(
            repo=repo,
            oracle_dir=oracle_dir,
            contract={
                "mode": "write",
                "allowed_paths": ["src/example.py"],
                "forbidden_paths": ["test_example.py"],
                "acceptance_command": "python3 -m unittest",
                "oracle_kind": "command_and_diff",
                "expected_policy": "core_only",
            },
            seed_commit="a" * 40,
            fixture_sha256="b" * 64,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def slot(self, **updates: object) -> dict[str, object]:
        slot: dict[str, object] = {
            "run_id": "cpe-v3-live-test",
            "treatment_id": "sol_v3",
            "case_id": "single-file implementation",
            "case_slug": "single-file-implementation",
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "outcome_kind": "credentialed_call",
            "expected_policy_failure": False,
            "billing_mode": "chatgpt_subscription",
        }
        slot.update(updates)
        return slot

    def process(self, **updates: object) -> ProcessEvidence:
        values: dict[str, object] = {
            "exit_code": 0,
            "latency_ms": 125,
            "timed_out": False,
            "retry_count": 0,
            "tracked_diff": "diff --git a/src/example.py b/src/example.py\n",
            "cached_diff": "",
            "untracked_files": (),
            "changed_files": ("src/example.py",),
            "acceptance_exit_code": 0,
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "input_tokens": 100,
            "cached_input_tokens": 25,
            "output_tokens": 20,
            "source_drift": False,
            "oracle_drift": False,
        }
        values.update(updates)
        return ProcessEvidence(**values)

    @staticmethod
    def output(**updates: object) -> dict[str, object]:
        output: dict[str, object] = {
            "status": "completed",
            "summary": "Implemented the requested fixture change.",
            "finding_ids": [],
            "fact_ids": [],
            "block_ids": [],
            "changed_files": ["src/example.py"],
        }
        output.update(updates)
        return output

    @staticmethod
    def events(*, model: str = "gpt-5.6-sol", include_model: bool = True, include_usage: bool = True) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        if include_model:
            events.append(
                {
                    "type": "model.attested",
                    "model": model,
                    "reasoning_effort": "high",
                    "source": "codex_session_jsonl",
                    "session_sha256": "a" * 64,
                }
            )
        events.append({"type": "turn.started"})
        if include_usage:
            events.append(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 25,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 5,
                    },
                }
            )
        return events

    def test_worker_schema_contains_only_the_model_final_response(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text())
        self.assertEqual(schema["$id"], "cpe.live-migration.worker-result.v2")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), OUTPUT_FIELDS)
        self.assertEqual(set(schema["properties"]), OUTPUT_FIELDS)
        for field in ("finding_ids", "fact_ids", "block_ids", "changed_files"):
            with self.subTest(field=field):
                self.assertNotIn("uniqueItems", schema["properties"][field])

    def test_runtime_rejects_duplicate_worker_result_values(self) -> None:
        duplicate_values = {
            "finding_ids": ["finding.one", "finding.one"],
            "fact_ids": ["fact.one", "fact.one"],
            "block_ids": ["block.one", "block.one"],
            "changed_files": ["src/example.py", "src/example.py"],
        }
        for field, values in duplicate_values.items():
            with self.subTest(field=field):
                with self.assertRaisesRegex(OracleInputError, rf"^{field} contains duplicates$"):
                    evaluate_slot(
                        self.slot(),
                        self.fixture,
                        self.process(),
                        self.output(**{field: values}),
                        self.events(),
                    )

    def test_subscription_result_uses_trusted_evidence_and_v2_shape(self) -> None:
        result = evaluate_slot(self.slot(), self.fixture, self.process(), self.output(), self.events())
        self.assertEqual(result["schema_version"], "cpe-live-result.v2")
        self.assertEqual(result["outcome_kind"], "credentialed_call")
        self.assertTrue(result["task_completed"])
        self.assertTrue(result["first_pass_success"])
        self.assertTrue(result["review_accurate"])
        self.assertTrue(result["evidence_complete"])
        self.assertFalse(result["critical_regression"])
        self.assertEqual(result["repairs"], 0)
        self.assertEqual(result["context_tokens"], 100)
        self.assertEqual(result["cache_tokens"], 25)
        self.assertEqual(result["output_tokens"], 20)
        self.assertEqual(result["latency_ms"], 125)
        self.assertEqual(result["billing_mode"], "chatgpt_subscription")
        self.assertIsNone(result["cost_usd"])
        self.assertTrue(result["model_attested"])
        self.assertTrue(result["worktree_isolated"])
        self.assertTrue(result["drift_free"])
        self.assertEqual(len(result["evidence_sha256"]), 64)

    def test_every_oracle_kind_has_deterministic_success_and_failure(self) -> None:
        cases = {
            "command_and_diff": ("finding_ids", []),
            "finding_ids": ("finding_ids", ["finding.one"]),
            "fact_ids": ("fact_ids", ["fact.one"]),
            "block_ids": ("block_ids", ["block.one"]),
        }
        for oracle_kind, (field, required_ids) in cases.items():
            with self.subTest(oracle_kind=oracle_kind):
                contract = dict(self.fixture.contract)
                contract["oracle_kind"] = oracle_kind
                oracle_dir = self.fixture.oracle_dir / oracle_kind
                oracle_dir.mkdir()
                (oracle_dir / "expected.json").write_text(
                    json.dumps({"changed_files": ["src/example.py"], "required_ids": required_ids})
                )
                fixture = replace(self.fixture, contract=contract, oracle_dir=oracle_dir)
                passing_output = self.output(**{field: required_ids})
                passing = evaluate_slot(self.slot(), fixture, self.process(), passing_output, self.events())
                self.assertTrue(passing["review_accurate"])
                failing_output = self.output(**{field: ["wrong.id"]})
                failing = evaluate_slot(self.slot(), fixture, self.process(), failing_output, self.events())
                self.assertFalse(failing["review_accurate"])

    def test_expected_block_is_a_completed_credentialed_outcome(self) -> None:
        contract = dict(self.fixture.contract)
        contract.update(
            mode="read_only",
            allowed_paths=[],
            forbidden_paths=["**/*"],
            oracle_kind="block_ids",
            expected_policy="block",
        )
        (self.fixture.oracle_dir / "expected.json").write_text(
            json.dumps({"required_ids": ["security.migration.blocked"]})
        )
        fixture = replace(self.fixture, contract=contract)
        process = self.process(tracked_diff="", changed_files=())
        output = self.output(
            status="blocked",
            summary="Blocked the prohibited security migration.",
            block_ids=["security.migration.blocked"],
            changed_files=[],
        )

        result = evaluate_slot(self.slot(), fixture, process, output, self.events())

        self.assertTrue(result["review_accurate"])
        self.assertTrue(result["evidence_complete"])
        self.assertTrue(result["task_completed"])
        self.assertFalse(result["critical_regression"])

    def test_worker_cannot_self_attest_model_or_git_facts(self) -> None:
        forged = self.output(
            attestation={"model": "gpt-5.6-sol"},
            worktree={"isolated": True},
            critical_regression=False,
        )
        with self.assertRaises(OracleInputError):
            evaluate_slot(self.slot(), self.fixture, self.process(), forged, self.events(model="wrong-model"))
        wrong_model = evaluate_slot(
            self.slot(), self.fixture, self.process(model="wrong-model"), self.output(), self.events(model="wrong-model")
        )
        self.assertFalse(wrong_model["model_attested"])
        self.assertFalse(wrong_model["evidence_complete"])
        self.assertFalse(wrong_model["task_completed"])
        wrong_fixture = replace(self.fixture, repo=self.fixture.repo / "worker-claimed-worktree")
        wrong_worktree = evaluate_slot(
            self.slot(), wrong_fixture, self.process(), self.output(), self.events()
        )
        self.assertFalse(wrong_worktree["worktree_isolated"])
        self.assertFalse(wrong_worktree["evidence_complete"])
        self.assertFalse(wrong_worktree["task_completed"])

    def test_untracked_files_must_be_in_the_trusted_changed_file_inventory(self) -> None:
        incomplete_git_evidence = evaluate_slot(
            self.slot(),
            self.fixture,
            self.process(untracked_files=("unreported.txt",)),
            self.output(),
            self.events(),
        )
        self.assertFalse(incomplete_git_evidence["evidence_complete"])
        self.assertFalse(incomplete_git_evidence["task_completed"])

    def test_tracked_and_cached_diff_paths_must_match_the_changed_file_inventory(self) -> None:
        contradictory_diffs = (
            {"tracked_diff": "diff --git a/test_example.py b/test_example.py\n"},
            {"cached_diff": "diff --git a/test_example.py b/test_example.py\n"},
        )
        for updates in contradictory_diffs:
            with self.subTest(updates=updates):
                result = evaluate_slot(
                    self.slot(),
                    self.fixture,
                    self.process(**updates),
                    self.output(),
                    self.events(),
                )
                self.assertTrue(result["critical_regression"])
                self.assertFalse(result["evidence_complete"])
                self.assertFalse(result["task_completed"])

    def test_missing_or_inconsistent_model_and_usage_events_fail_evidence(self) -> None:
        missing_model = evaluate_slot(
            self.slot(), self.fixture, self.process(model=None, reasoning_effort=None), self.output(), self.events(include_model=False)
        )
        missing_usage = evaluate_slot(
            self.slot(),
            self.fixture,
            self.process(input_tokens=None, cached_input_tokens=None, output_tokens=None),
            self.output(),
            self.events(include_usage=False),
        )
        inconsistent_usage = evaluate_slot(
            self.slot(), self.fixture, self.process(output_tokens=21), self.output(), self.events()
        )
        for result in (missing_model, missing_usage, inconsistent_usage):
            self.assertFalse(result["evidence_complete"])
            self.assertFalse(result["task_completed"])

    def test_forbidden_write_and_fixture_drift_are_critical_regressions(self) -> None:
        forbidden = evaluate_slot(
            self.slot(),
            self.fixture,
            self.process(changed_files=("test_example.py",)),
            self.output(changed_files=["test_example.py"]),
            self.events(),
        )
        drifted = evaluate_slot(
            self.slot(), self.fixture, self.process(source_drift=True), self.output(), self.events()
        )
        self.assertTrue(forbidden["critical_regression"])
        self.assertFalse(forbidden["task_completed"])
        self.assertTrue(forbidden["drift_free"])
        self.assertTrue(drifted["critical_regression"])
        self.assertFalse(drifted["task_completed"])
        self.assertFalse(drifted["drift_free"])

    def test_read_only_cases_require_clean_tracked_cached_and_untracked_state(self) -> None:
        contract = dict(self.fixture.contract)
        contract.update(
            mode="read_only",
            allowed_paths=[],
            forbidden_paths=["**/*"],
            oracle_kind="fact_ids",
        )
        (self.fixture.oracle_dir / "expected.json").write_text(json.dumps({"required_ids": ["fact.one"]}))
        fixture = replace(self.fixture, contract=contract)
        clean = self.process(tracked_diff="", changed_files=())
        output = self.output(fact_ids=["fact.one"], changed_files=[])
        self.assertTrue(evaluate_slot(self.slot(), fixture, clean, output, self.events())["task_completed"])
        for process in (
            replace(clean, tracked_diff="diff"),
            replace(clean, cached_diff="diff"),
            replace(clean, untracked_files=("note.txt",)),
        ):
            with self.subTest(process=process):
                result = evaluate_slot(self.slot(), fixture, process, output, self.events())
                self.assertTrue(result["critical_regression"])
                self.assertFalse(result["task_completed"])

    def test_retry_count_controls_first_pass_success(self) -> None:
        result = evaluate_slot(
            self.slot(), self.fixture, self.process(retry_count=2), self.output(), self.events()
        )
        self.assertTrue(result["task_completed"])
        self.assertFalse(result["first_pass_success"])
        self.assertEqual(result["repairs"], 2)

    def test_terminated_process_exit_code_is_scored_as_failure(self) -> None:
        result = evaluate_slot(
            self.slot(), self.fixture, self.process(exit_code=-9), self.output(), self.events()
        )
        self.assertFalse(result["task_completed"])

    def test_policy_failure_result_is_terra_only_and_has_no_provider_usage(self) -> None:
        terra = self.slot(
            treatment_id="terra_scout",
            model="gpt-5.6-terra",
            outcome_kind="expected_policy_failure",
            expected_policy_failure=True,
            policy_reason={"code": "terra_write_capability_forbidden", "required_role": "read_only_scout"},
            matrix_policy_sha256="c" * 64,
        )
        result = policy_failure_result(terra, "d" * 64)
        self.assertEqual(result["schema_version"], "cpe-live-result.v2")
        self.assertEqual(result["outcome_kind"], "expected_policy_failure")
        self.assertTrue(result["expected_policy_failure"])
        for field in ("context_tokens", "cache_tokens", "output_tokens", "latency_ms", "cost_usd"):
            self.assertNotIn(field, result)
        with self.assertRaises(OracleInputError):
            policy_failure_result(self.slot(), "d" * 64)


if __name__ == "__main__":
    unittest.main()
