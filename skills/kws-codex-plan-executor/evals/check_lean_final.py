#!/usr/bin/env python3
"""Focused document-audit and single terminal-integration checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "lean-fixtures"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime import contracts  # noqa: E402
from cpe_runtime.launcher import ChildLauncher  # noqa: E402
from cpe_runtime.queue import QueueEngine  # noqa: E402
from cpe_runtime.store import RunStore  # noqa: E402
from cpe_runtime.worktree import Worktree  # noqa: E402


class LeanFinalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-lean-final-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.home.mkdir(mode=0o700)
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "cpe@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "CPE Eval"],
            check=True,
        )
        for name in ("spec-a.md", "spec-b.md", "plan-a.md", "plan-b.md", "program.md"):
            shutil.copyfile(FIXTURES / name, self.repo / name)
        (self.repo / "AGENTS.md").write_text(
            "# Repository Instructions\n\nUse strict TDD and one final verification.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "fixture base"],
            check=True,
        )
        self.invocation_log = self.root / "final-invocations.jsonl"
        self.fake_state = self.root / "final-state.json"
        self.verification_log = self.root / "verification-invocations.jsonl"
        self.bin_dir = self.root / "fake-bin"
        self.bin_dir.mkdir()
        fake_codex = self.bin_dir / "codex"
        source = (SKILL_ROOT / "evals" / "fake_codex.py").read_text(encoding="utf-8")
        lines = source.splitlines()
        lines[0] = f"#!{sys.executable}"
        fake_codex.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fake_codex.chmod(0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_engine(self, scenario: str) -> tuple[RunStore, QueueEngine]:
        store = RunStore.create(
            codex_home=self.home,
            workspace=self.repo,
            specs=[self.repo / "spec-a.md", self.repo / "spec-b.md"],
            plans=[self.repo / "plan-a.md", self.repo / "plan-b.md"],
            program_plan=self.repo / "program.md",
        )
        worktree = Worktree.create(
            source=self.repo,
            root=self.root / f"worktree-{scenario}",
            run_id=f"final-{scenario}",
        )
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=10,
            environ={
                **os.environ,
                "PATH": str(self.bin_dir),
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_SCENARIO": "mapping_success",
                "CPE_FAKE_INVOCATION_LOG": str(self.invocation_log),
                "CPE_FAKE_QUEUE_STATE": str(self.fake_state),
                "CPE_FAKE_VERIFICATION_LOG": str(self.verification_log),
            },
        )
        engine = QueueEngine(store, worktree, launcher)
        engine.map_program()
        launcher.environ["CPE_FAKE_SCENARIO"] = scenario
        return store, engine

    def invocations(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.invocation_log.read_text(encoding="utf-8").splitlines()
        ]

    def verification_invocations(self) -> list[dict[str, object]]:
        if not self.verification_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.verification_log.read_text(encoding="utf-8").splitlines()
        ]

    def test_final_artifact_contracts_exist(self) -> None:
        self.assertTrue(
            hasattr(contracts, "validate_document_audit"),
            "strict document-audit validator is missing",
        )
        self.assertTrue(
            hasattr(contracts, "validate_terminal_artifact"),
            "strict terminal-artifact validator is missing",
        )

    def test_each_document_audits_scoped_evidence_before_one_terminal_pass(self) -> None:
        store, engine = self.create_engine("final_success")
        base = engine.worktree.base_commit

        state = engine.run_until_terminal()

        self.assertEqual(state["status"], "completed")
        self.assertTrue(store.paths.result.is_file())
        documents = store.document_set()
        invocations = self.invocations()
        auditors = [item for item in invocations if item["role"] == "document_auditor"]
        self.assertEqual(
            [item["item_id"] for item in auditors],
            [doc.document_id for doc in documents],
        )
        program, selected = engine._program_context()
        task_by_id = {str(task["task_id"]): task for task in program["tasks"]}
        snapshots = {
            doc.document_id: str((store.paths.root / doc.snapshot_path).resolve())
            for doc in documents
        }
        for invocation in auditors:
            document_id = str(invocation["item_id"])
            inputs = set(invocation["input_paths"])
            self.assertIn(snapshots[document_id], inputs)
            self.assertFalse(
                {path for key, path in snapshots.items() if key != document_id} & inputs
            )
            relevant = {
                str(selected[str(task["brief_path"])])
                for task in task_by_id.values()
                if document_id in task["document_ids"]
            }
            unrelated = {
                str(selected[str(task["brief_path"])])
                for task in task_by_id.values()
                if document_id not in task["document_ids"]
            }
            self.assertTrue(relevant <= inputs)
            self.assertFalse(unrelated & inputs)

        plan_one = next(item for item in auditors if item["item_id"] == "plan-01")
        task_diffs = {
            Path(path).name: Path(path).read_text(encoding="utf-8")
            for path in plan_one["input_paths"]
            if "/diffs/plan-01-" in path
        }
        self.assertNotIn(
            "cpe-plan-01-T2.txt", task_diffs["plan-01-plan-01-T1.patch"]
        )
        self.assertNotIn(
            "cpe-plan-02-T1.txt", task_diffs["plan-01-plan-01-T2.patch"]
        )

        integrators = [
            item for item in invocations if item["role"] == "program_final_integrator"
        ]
        self.assertEqual(len(integrators), 1)
        whole = [Path(path) for path in integrators[0]["input_paths"] if "whole.patch" in path]
        self.assertEqual(len(whole), 1)
        revision = engine.worktree.head()
        self.assertEqual(
            whole[0].read_text(encoding="utf-8"), engine.worktree.diff(base, revision)
        )
        terminal = json.loads(store.paths.result.read_text(encoding="utf-8"))
        self.assertEqual(terminal["revision"], revision)
        self.assertEqual(set(terminal["auditor_verdicts"]), {doc.document_id for doc in documents})
        handoff_path = (
            store.paths.root
            / f"verification/final/{revision}/integration-handoff.json"
        )
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        self.assertEqual(handoff["producer"], "cpe_launcher")
        self.assertEqual(handoff_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(self.verification_invocations()), 1)

    def test_blocked_auditor_prevents_integrator_and_completion(self) -> None:
        store, engine = self.create_engine("final_auditor_blocked")

        state = engine.run_until_terminal()

        self.assertEqual(state["status"], "final_audit")
        self.assertFalse(store.paths.result.exists())
        roles = [item["role"] for item in self.invocations()]
        self.assertEqual(roles.count("document_auditor"), 5)
        self.assertNotIn("program_final_integrator", roles)

    def test_stale_integrator_revision_is_rejected_without_terminal_result(self) -> None:
        store, engine = self.create_engine("final_stale_commit")

        with self.assertRaisesRegex(ValueError, "final integrator revision"):
            engine.run_until_terminal()

        self.assertFalse(store.paths.result.exists())
        self.assertFalse(
            any(event["event_type"] == "run.completed" for event in store.validate_event_chain())
        )

    def test_failed_terminal_cannot_complete_from_completed_child_handoff(self) -> None:
        store, engine = self.create_engine("final_failed_terminal")

        with self.assertRaisesRegex(ValueError, "quality verdict is not pass"):
            engine.run_until_terminal()

        self.assertFalse(store.paths.result.exists())
        self.assertFalse(
            any(
                event["event_type"] == "run.completed"
                for event in store.validate_event_chain()
            )
        )

    def test_child_cannot_forge_launcher_owned_integration_handoff(self) -> None:
        store, engine = self.create_engine("final_forged_handoff")

        with self.assertRaisesRegex(ValueError, "forge.*integration handoff"):
            engine.run_until_terminal()

        self.assertFalse(store.paths.result.exists())
        self.assertFalse(
            any(
                event["event_type"] == "integration.reported"
                for event in store.validate_event_chain()
            )
        )

    def test_integration_fix_invalidates_all_final_evidence_and_repeats_once(self) -> None:
        store, engine = self.create_engine("final_integration_fix")

        state = engine.run_until_terminal()

        self.assertEqual(state["status"], "completed")
        roles = [item["role"] for item in self.invocations()]
        self.assertEqual(roles.count("integration_fix_agent"), 1)
        self.assertEqual(roles.count("document_auditor"), 10)
        self.assertEqual(roles.count("program_final_integrator"), 2)
        audit_revisions = {
            event["payload"]["commit"]
            for event in store.validate_event_chain()
            if event["event_type"] == "audit.reported"
        }
        self.assertEqual(len(audit_revisions), 2)
        self.assertEqual(len(self.verification_invocations()), 2)
        self.assertEqual(
            json.loads(store.paths.result.read_text(encoding="utf-8"))["revision"],
            engine.worktree.head(),
        )

    def test_interrupted_integrator_reuses_completed_audits_on_resume(self) -> None:
        store, engine = self.create_engine("final_integrator_crash")

        with self.assertRaisesRegex(ValueError, "Codex child exited"):
            engine.run_until_terminal()
        first_roles = [item["role"] for item in self.invocations()]
        self.assertEqual(first_roles.count("document_auditor"), 5)
        self.assertEqual(first_roles.count("program_final_integrator"), 1)
        self.assertFalse(store.paths.result.exists())

        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "final_success"
        state = engine.run_until_terminal()
        self.assertEqual(state["status"], "completed")
        roles = [item["role"] for item in self.invocations()]
        self.assertEqual(roles.count("document_auditor"), 5)
        self.assertEqual(roles.count("program_final_integrator"), 2)
        self.assertEqual(len(self.verification_invocations()), 1)

    def test_post_ingest_integrator_crash_reconciles_without_reverification(self) -> None:
        store, engine = self.create_engine("final_success")
        original_put = store.put_artifact
        interrupted = False

        def interrupt_before_result(relative_path: str, data: bytes) -> Path:
            nonlocal interrupted
            if relative_path.endswith("/integration-result.json") and not interrupted:
                interrupted = True
                raise RuntimeError("deterministic post-ingest interruption")
            return original_put(relative_path, data)

        store.put_artifact = interrupt_before_result  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "post-ingest interruption"):
            engine.run_until_terminal()
        store.put_artifact = original_put  # type: ignore[method-assign]

        state = engine.run_until_terminal()
        self.assertEqual(state["status"], "completed")
        roles = [item["role"] for item in self.invocations()]
        self.assertEqual(roles.count("program_final_integrator"), 1)
        self.assertEqual(len(self.verification_invocations()), 1)

    def test_post_ingest_change_request_preserves_fix_on_resume(self) -> None:
        store, engine = self.create_engine("final_integration_fix")
        original_put = store.put_artifact
        interrupted = False

        def interrupt_before_result(relative_path: str, data: bytes) -> Path:
            nonlocal interrupted
            if relative_path.endswith("/integration-result.json") and not interrupted:
                interrupted = True
                raise RuntimeError("deterministic change-request interruption")
            return original_put(relative_path, data)

        store.put_artifact = interrupt_before_result  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "change-request interruption"):
            engine.run_until_terminal()
        store.put_artifact = original_put  # type: ignore[method-assign]

        state = engine.run_until_terminal()
        self.assertEqual(state["status"], "completed")
        roles = [item["role"] for item in self.invocations()]
        self.assertEqual(roles.count("program_final_integrator"), 2)
        self.assertEqual(roles.count("integration_fix_agent"), 1)
        self.assertEqual(len(self.verification_invocations()), 2)

    def test_post_ingest_pass_with_finding_is_fail_closed(self) -> None:
        store, engine = self.create_engine("final_pass_with_finding")
        original_put = store.put_artifact
        interrupted = False

        def interrupt_before_result(relative_path: str, data: bytes) -> Path:
            nonlocal interrupted
            if relative_path.endswith("/integration-result.json") and not interrupted:
                interrupted = True
                raise RuntimeError("deterministic contradictory pass interruption")
            return original_put(relative_path, data)

        store.put_artifact = interrupt_before_result  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "contradictory pass interruption"):
            engine.run_until_terminal()
        store.put_artifact = original_put  # type: ignore[method-assign]

        with self.assertRaisesRegex(ValueError, "passing final integration"):
            engine.run_until_terminal()
        self.assertFalse(store.paths.result.exists())
        self.assertEqual(len(self.verification_invocations()), 1)

    def test_integrator_timeout_gets_one_durable_retry(self) -> None:
        store, engine = self.create_engine("final_integrator_timeout")
        engine.launcher.timeout_seconds = 0.1

        with self.assertRaisesRegex(TimeoutError, "timed out"):
            engine.run_until_terminal()

        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "final_success"
        state = engine.run_until_terminal()
        self.assertEqual(state["status"], "completed")
        roles = [item["role"] for item in self.invocations()]
        self.assertEqual(roles.count("program_final_integrator"), 2)
        self.assertEqual(len(self.verification_invocations()), 1)

    def test_interrupted_integration_fix_reconciles_without_duplicate_writer(self) -> None:
        store, engine = self.create_engine("final_integration_fix")
        original_append = engine._append_task_result
        interrupted = False

        def interrupt_before_task_report(*args: object, **kwargs: object) -> None:
            nonlocal interrupted
            if kwargs.get("task_id") == "program:integration" and not interrupted:
                interrupted = True
                raise RuntimeError("deterministic integration-fix interruption")
            original_append(*args, **kwargs)  # type: ignore[arg-type]

        engine._append_task_result = interrupt_before_task_report  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "integration-fix interruption"):
            engine.run_until_terminal()
        engine._append_task_result = original_append  # type: ignore[method-assign]

        state = engine.run_until_terminal()
        self.assertEqual(state["status"], "completed")
        roles = [item["role"] for item in self.invocations()]
        self.assertEqual(roles.count("integration_fix_agent"), 1)
        self.assertEqual(roles.count("program_final_integrator"), 2)
        integration_state = state["tasks"]["program:integration"]
        self.assertNotIn("active_attempt", integration_state)
        self.assertEqual(len(integration_state["attempts"]), 1)
        self.assertEqual(integration_state["attempts"][0]["status"], "completed")

    def test_audit_and_terminal_artifact_validators_are_exact_and_revision_bound(self) -> None:
        revision = "a" * 40
        audit = {
            "schema_version": 1,
            "document_id": "spec-01",
            "source_sha256": "b" * 64,
            "revision": revision,
            "coverage_verdicts": {"spec-01:R1": "pass"},
            "missing_requirements": [],
            "conflicts": [],
            "verdict": "pass",
        }
        self.assertEqual(
            contracts.validate_document_audit(
                audit,
                document_id="spec-01",
                source_sha256="b" * 64,
                revision=revision,
                requirement_ids=("spec-01:R1",),
            ),
            audit,
        )
        with self.assertRaises(ValueError):
            contracts.validate_document_audit(
                {**audit, "revision": "c" * 40},
                document_id="spec-01",
                source_sha256="b" * 64,
                revision=revision,
                requirement_ids=("spec-01:R1",),
            )

        terminal = {
            "schema_version": 1,
            "quality_verdict": "pass",
            "revision": revision,
            "auditor_verdicts": {"spec-01": "pass"},
            "verification": [
                {
                    "command": "python3 evals/check_lean_final.py",
                    "exit_code": 0,
                    "output_path": (
                        f"verification/final/{revision}/commands/command-01.log"
                    ),
                }
            ],
            "authority_open": [],
            "residual_limitations": [],
            "whole_diff_sha256": "d" * 64,
        }
        self.assertEqual(
            contracts.validate_terminal_artifact(
                terminal,
                revision=revision,
                auditor_document_ids=("spec-01",),
                verification_commands=("python3 evals/check_lean_final.py",),
            ),
            terminal,
        )
        with self.assertRaises(ValueError):
            contracts.validate_terminal_artifact(
                {**terminal, "unexpected": True},
                revision=revision,
                auditor_document_ids=("spec-01",),
                verification_commands=("python3 evals/check_lean_final.py",),
            )
        with self.assertRaises(ValueError):
            contracts.validate_terminal_artifact(
                {
                    **terminal,
                    "verification": [
                        {
                            "command": "python3 evals/check_lean_final.py",
                            "exit_code": 0,
                            "output_path": (
                                "verification/final/"
                                f"{'c' * 40}/commands/command-01.log"
                            ),
                        }
                    ],
                },
                revision=revision,
                auditor_document_ids=("spec-01",),
                verification_commands=("python3 evals/check_lean_final.py",),
            )


if __name__ == "__main__":
    unittest.main()
