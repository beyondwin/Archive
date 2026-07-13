#!/usr/bin/env python3
"""Focused schema-4 recovery, authority, refresh, and legacy checks."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI = SKILL_ROOT / "scripts" / "cpe.py"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cpe_runtime.launcher import ChildLauncher  # noqa: E402
from cpe_runtime.queue import QueueEngine  # noqa: E402
from cpe_runtime.store import RunStore  # noqa: E402
from cpe_runtime.worktree import Worktree  # noqa: E402
import cpe as cpe_cli  # noqa: E402
import cpe_runtime.store as store_module  # noqa: E402
from fake_codex import LeanEvalCase  # noqa: E402


class LeanRecoveryTest(LeanEvalCase):
    fixture_prefix = "cpe-lean-recovery-"

    def setUp(self) -> None:
        super().setUp()
        self.invocations = self.root / "invocations.jsonl"
        self.fake_state = self.root / "state.json"
        self.bin_dir = self.install_fake_codex("bin")
        self.env = {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "CODEX_HOME": str(self.home),
            "CPE_FAKE_SCENARIO": "mapping_success",
            "CPE_FAKE_INVOCATION_LOG": str(self.invocations),
            "CPE_FAKE_QUEUE_STATE": str(self.fake_state),
        }

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            check=False,
        )

    def create_engine(self, scenario: str = "mapping_success") -> tuple[RunStore, QueueEngine]:
        store = RunStore.create(
            codex_home=self.home,
            workspace=self.repo,
            specs=[self.repo / "spec-a.md", self.repo / "spec-b.md"],
            plans=[self.repo / "plan-a.md", self.repo / "plan-b.md"],
            program_plan=self.repo / "program.md",
        )
        (self.home / "worktrees").mkdir(exist_ok=True)
        worktree = Worktree.create(
            source=self.repo,
            root=self.home / "worktrees" / store.run_id,
            run_id=store.run_id,
        )
        launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=10,
            terminate_grace_seconds=0.05,
            environ={**self.env, "CPE_FAKE_SCENARIO": scenario},
        )
        return store, QueueEngine(store, worktree, launcher)

    @staticmethod
    def file_snapshot(root: Path) -> tuple[tuple[str, bytes, int, int], ...]:
        return tuple(
            (
                str(path.relative_to(root)),
                path.read_bytes(),
                stat.S_IMODE(path.stat().st_mode),
                path.stat().st_mtime_ns,
            )
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )

    def test_schema3_inspect_is_read_only_and_resume_is_rejected(self) -> None:
        run_id = "legacy-run"
        run = self.home / "orchestrator" / run_id
        run.mkdir(parents=True, mode=0o700)
        (run / "run_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "3",
                    "run_id": run_id,
                    "execution_worktree": "/tmp/legacy-worktree",
                }
            ),
            encoding="utf-8",
        )
        (run / "state.json").write_text(
            json.dumps(
                {
                    "status": "interrupted",
                    "current_task": "T3",
                    "tasks": ["T1", "T2", "T3"],
                }
            ),
            encoding="utf-8",
        )
        before = self.file_snapshot(run)
        inspected = self.cli("inspect", "--run-id", run_id)
        self.assertEqual(inspected.returncode, 0, inspected.stderr or inspected.stdout)
        payload = json.loads(inspected.stdout)
        self.assertEqual(payload["schema_version"], 3)
        self.assertFalse(payload["resume_supported"])
        self.assertEqual(self.file_snapshot(run), before)

        resumed = self.cli("resume", "--run-id", run_id)
        self.assertEqual(resumed.returncode, 1, resumed.stderr)
        self.assertEqual(
            json.loads(resumed.stdout)["failure_code"],
            "legacy_run_requires_historical_cpe",
        )
        self.assertEqual(self.file_snapshot(run), before)

    def test_schema4_inspect_is_bounded_and_source_drift_is_not_implicit(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        original_event_count = len(store.validate_event_chain())
        (self.repo / "spec-a.md").write_text("# changed source\n", encoding="utf-8")
        inspected = self.cli("inspect", "--run-id", store.run_id)
        self.assertEqual(inspected.returncode, 0, inspected.stderr or inspected.stdout)
        payload = json.loads(inspected.stdout)
        self.assertEqual(payload["schema_version"], 4)
        self.assertEqual(payload["generation"], "generation-0001")
        self.assertEqual(payload["total_tasks"], 3)
        self.assertIn("worktree_head", payload)
        self.assertEqual(len(store.validate_event_chain()), original_event_count)
        self.assertEqual(store.document_set()[0].sha256, engine.store.document_set()[0].sha256)
        with mock.patch.object(
            RunStore,
            "read_accepted_publication",
            side_effect=AssertionError("inspect loaded the full publication"),
        ):
            summary = cpe_cli.inspect_schema4(
                RunStore.open(codex_home=self.home, run_id=store.run_id, read_only=True)
            )
        self.assertEqual(summary["total_tasks"], 3)

    def test_authority_resolution_requires_offered_answer_and_preserves_packet(self) -> None:
        store, engine = self.create_engine("mapping_conflict")
        engine.map_program()
        authority_path = "maps/generation-0001/authority-queue.json"
        before = store.read_artifact(authority_path)

        rejected = self.cli(
            "resume",
            "--run-id",
            store.run_id,
            "--authority-id",
            "mapping-conflict-1",
            "--authority-answer",
            "not-an-option",
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertEqual(json.loads(rejected.stdout)["failure_code"], "authority_answer_invalid")
        self.assertEqual(store.read_artifact(authority_path), before)

        self.env["CPE_FAKE_SCENARIO"] = "final_success"
        accepted = self.cli(
            "resume",
            "--run-id",
            store.run_id,
            "--authority-id",
            "mapping-conflict-1",
            "--authority-answer",
            "spec-01",
        )
        self.assertIn(accepted.returncode, {0, 2, 3}, accepted.stderr or accepted.stdout)
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        resolved = [
            event
            for event in reopened.validate_event_chain()
            if event["event_type"] == "authority.resolved"
        ]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(reopened.read_artifact(authority_path), before)

    def test_explicit_refresh_creates_new_generation_and_preserves_first(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        first_program = store.read_artifact("maps/generation-0001/program-map.json")
        (self.repo / "spec-a.md").write_text(
            (self.repo / "spec-a.md").read_text(encoding="utf-8") + "\nNew constraint.\n",
            encoding="utf-8",
        )
        self.env["CPE_FAKE_SCENARIO"] = "refresh_success"
        refreshed = self.cli("resume", "--run-id", store.run_id, "--refresh-inputs")
        self.assertIn(refreshed.returncode, {0, 2, 3}, refreshed.stderr or refreshed.stdout)
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        generation_ids = [
            event["payload"]["generation_id"]
            for event in reopened.validate_event_chain()
            if event["event_type"] == "map.generation_created"
        ]
        self.assertEqual(generation_ids, ["generation-0001", "generation-0002"])
        self.assertEqual(
            reopened.read_artifact("maps/generation-0001/program-map.json"),
            first_program,
        )
        self.assertTrue(
            reopened.read_artifact("maps/generation-0002/program-map.json")
        )
        invocations = [
            json.loads(line)
            for line in self.invocations.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            len([item for item in invocations if item["role"] == "document_mapper"]),
            6,
        )

    def test_refresh_invalidates_changed_brief_and_graph_descendants(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_success"
        self.assertEqual(engine.tick(), "plan-01:T1")
        before_starts = [
            event
            for event in store.validate_event_chain()
            if event["event_type"] == "task.started"
            and event["payload"]["task_id"] == "plan-01:T1"
        ]
        self.assertEqual(len(before_starts), 1)

        (self.repo / "spec-a.md").write_text(
            (self.repo / "spec-a.md").read_text(encoding="utf-8")
            + "\nChanged normative constraint.\n",
            encoding="utf-8",
        )
        self.env["CPE_FAKE_SCENARIO"] = "refresh_success"
        refreshed = self.cli("resume", "--run-id", store.run_id, "--refresh-inputs")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr or refreshed.stdout)
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        starts = [
            event["payload"]["task_id"]
            for event in reopened.validate_event_chain()
            if event["event_type"] == "task.started"
        ]
        self.assertEqual(starts.count("plan-01:T1"), 2)
        latest_generation = [
            event["payload"]
            for event in reopened.validate_event_chain()
            if event["event_type"] == "map.generation_created"
        ][-1]
        self.assertEqual(
            latest_generation["invalidated_task_ids"],
            ["plan-01:T1", "plan-01:T2", "plan-02:T1"],
        )

    def test_keyboard_interrupt_is_durable_and_exits_three(self) -> None:
        store, _ = self.create_engine()
        output = StringIO()
        argv = ["cpe.py", "resume", "--run-id", store.run_id]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(cpe_cli, "_run_engine", side_effect=KeyboardInterrupt),
            mock.patch.dict(os.environ, self.env, clear=True),
            redirect_stdout(output),
        ):
            exit_code = cpe_cli.main()
        self.assertEqual(exit_code, 3)
        self.assertEqual(json.loads(output.getvalue())["status"], "interrupted")
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        self.assertEqual(reopened.validate_event_chain()[-1]["event_type"], "run.interrupted")

    def test_plain_resume_finishes_a_durable_pending_input_revision(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        (self.repo / "spec-a.md").write_text(
            (self.repo / "spec-a.md").read_text(encoding="utf-8")
            + "\nPending refresh constraint.\n",
            encoding="utf-8",
        )
        generation_id, _, _ = store.refresh_inputs()
        self.assertEqual(generation_id, "generation-0002")

        self.env["CPE_FAKE_SCENARIO"] = "refresh_success"
        resumed = self.cli("resume", "--run-id", store.run_id)
        self.assertEqual(resumed.returncode, 0, resumed.stderr or resumed.stdout)
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        generation_ids = [
            event["payload"]["generation_id"]
            for event in reopened.validate_event_chain()
            if event["event_type"] == "map.generation_created"
        ]
        self.assertEqual(generation_ids, ["generation-0001", "generation-0002"])

    def test_mapping_child_interruption_is_publicly_resumable(self) -> None:
        self.env["CPE_FAKE_SCENARIO"] = "mapping_noncompleted_result"
        result = self.cli(
            "run",
            "--spec",
            str(self.repo / "spec-a.md"),
            "--plan",
            str(self.repo / "plan-a.md"),
            "--workspace",
            str(self.repo),
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
        self.assertEqual(payload["status"], "interrupted")
        store = RunStore.open(codex_home=self.home, run_id=payload["run_id"])
        self.assertEqual(store.validate_event_chain()[-1]["event_type"], "run.interrupted")

    def test_mapping_child_process_crash_is_publicly_resumable(self) -> None:
        self.env["CPE_FAKE_SCENARIO"] = "mapping_partial_failure"
        result = self.cli(
            "run",
            "--spec",
            str(self.repo / "spec-a.md"),
            "--plan",
            str(self.repo / "plan-a.md"),
            "--plan",
            str(self.repo / "plan-b.md"),
            "--workspace",
            str(self.repo),
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
        store = RunStore.open(codex_home=self.home, run_id=payload["run_id"])
        self.assertEqual(store.validate_event_chain()[-1]["event_type"], "run.interrupted")

    def test_task_child_timeout_is_publicly_resumable(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        timed_launcher = ChildLauncher(
            schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
            timeout_seconds=0.1,
            terminate_grace_seconds=0.05,
            environ={**self.env, "CPE_FAKE_SCENARIO": "writer_hold"},
        )
        output = StringIO()
        argv = ["cpe.py", "resume", "--run-id", store.run_id]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(cpe_cli, "_launcher", return_value=timed_launcher),
            mock.patch.dict(os.environ, self.env, clear=True),
            redirect_stdout(output),
        ):
            exit_code = cpe_cli.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 3)
        self.assertEqual(payload["status"], "interrupted")
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        self.assertEqual(reopened.validate_event_chain()[-1]["event_type"], "run.interrupted")

    def test_refresh_keyboard_interrupt_removes_uncommitted_revision(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        (self.repo / "spec-a.md").write_text("# interrupted refresh\n", encoding="utf-8")
        original = store_module._atomic_write_new

        def interrupt_revision(path: Path, data: bytes) -> None:
            if "generation-0002" in path.parts:
                raise KeyboardInterrupt
            original(path, data)

        with mock.patch.object(store_module, "_atomic_write_new", interrupt_revision):
            with self.assertRaises(KeyboardInterrupt):
                store.refresh_inputs()
        self.assertFalse((store.paths.inputs / "generation-0002").exists())

    def test_refresh_interrupt_after_snapshot_event_keeps_pending_revision(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        (self.repo / "spec-a.md").write_text("# committed refresh\n", encoding="utf-8")
        original = store.append_event

        def interrupt_after_event(event_type: str, payload: dict[str, object]) -> object:
            result = original(event_type, payload)
            if event_type == "documents.snapshotted":
                raise KeyboardInterrupt
            return result

        with mock.patch.object(store, "append_event", interrupt_after_event):
            with self.assertRaises(KeyboardInterrupt):
                store.refresh_inputs()
        pending = store.pending_input_revision()
        self.assertIsNotNone(pending)
        self.assertEqual(pending[0], "generation-0002")

    def test_generic_runtime_failure_is_recorded_in_durable_state(self) -> None:
        store, _ = self.create_engine()
        output = StringIO()
        argv = ["cpe.py", "resume", "--run-id", store.run_id]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(cpe_cli, "_run_engine", side_effect=ValueError("boom")),
            mock.patch.dict(os.environ, self.env, clear=True),
            redirect_stdout(output),
        ):
            exit_code = cpe_cli.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["state_path"], str(store.paths.manifest))
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        self.assertEqual(reopened.validate_event_chain()[-1]["event_type"], "run.failed")
        self.assertEqual(reopened.replay()["status"], "failed")

    def test_resolving_one_of_multiple_authorities_remains_waiting(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        authority_path = "maps/generation-0001/authority-queue.json"
        for authority_id in ("A0001", "A0002"):
            store.append_event(
                "authority.opened",
                {
                    "authority_id": authority_id,
                    "authority_code": "credential_required",
                    "status": "waiting_authority",
                    "task_ids": ["plan-01:T1"],
                    "artifact_paths": [authority_path],
                },
            )
        store.append_event(
            "authority.resolved",
            {
                "authority_id": "A0001",
                "status": "resolved",
                "resolution_sha256": "a" * 64,
                "artifact_paths": [authority_path],
            },
        )
        state = store.replay()
        self.assertEqual(state["status"], "waiting_authority")
        self.assertEqual(state["authorities"]["A0002"]["status"], "waiting_authority")

    def test_task_authority_packet_is_cpe_owned_and_resolvable(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_authority"
        engine.tick()
        state = store.replay()
        self.assertEqual(state["status"], "waiting_authority")
        packet_path = state["authorities"]["A0001"]["artifact_paths"][0]
        packet = json.loads(store.read_artifact(packet_path).decode("utf-8"))
        self.assertEqual(packet["authority_id"], "A0001")
        self.assertTrue(packet["options"])
        self.env["CPE_FAKE_SCENARIO"] = "final_success"
        resumed = self.cli(
            "resume",
            "--run-id",
            store.run_id,
            "--authority-id",
            "A0001",
            "--authority-answer",
            packet["options"][0],
        )
        self.assertNotEqual(
            json.loads(resumed.stdout)["failure_code"], "authority_packet_invalid"
        )

    def test_refresh_retains_unchanged_predecessor_and_invalidates_descendants(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_success"
        self.assertEqual(engine.tick(), "plan-01:T1")
        (self.repo / "plan-b.md").write_text(
            (self.repo / "plan-b.md").read_text(encoding="utf-8")
            + "\nChanged independent task.\n",
            encoding="utf-8",
        )
        self.env["CPE_FAKE_SCENARIO"] = "refresh_success"
        refreshed = self.cli("resume", "--run-id", store.run_id, "--refresh-inputs")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr or refreshed.stdout)
        reopened = RunStore.open(codex_home=self.home, run_id=store.run_id)
        starts = [
            event["payload"]["task_id"]
            for event in reopened.validate_event_chain()
            if event["event_type"] == "task.started"
        ]
        self.assertEqual(starts.count("plan-01:T1"), 1)
        invalidated = [
            event["payload"].get("invalidated_task_ids", [])
            for event in reopened.validate_event_chain()
            if event["event_type"] == "map.generation_created"
        ][-1]
        self.assertEqual(invalidated, ["plan-02:T1"])

    def test_resume_rejects_branch_reset_that_discards_completed_commit(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_success"
        engine.tick()
        worktree = self.home / "worktrees" / store.run_id
        base = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD^"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        subprocess.run(["git", "-C", str(worktree), "reset", "--hard", base], check=True)
        before = len(self.invocations.read_text(encoding="utf-8").splitlines())
        self.env["CPE_FAKE_SCENARIO"] = "final_success"
        resumed = self.cli("resume", "--run-id", store.run_id)
        self.assertEqual(resumed.returncode, 1)
        after = len(self.invocations.read_text(encoding="utf-8").splitlines())
        self.assertEqual(after, before)

    def test_old_interrupted_status_does_not_mask_new_branch_integrity_failure(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        engine.launcher.environ["CPE_FAKE_SCENARIO"] = "queue_success"
        engine.tick()
        store.append_event(
            "run.interrupted", {"status": "interrupted", "failure_code": "signal"}
        )
        worktree = self.home / "worktrees" / store.run_id
        base = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD^"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        subprocess.run(["git", "-C", str(worktree), "reset", "--hard", base], check=True)
        resumed = self.cli("resume", "--run-id", store.run_id)
        self.assertEqual(resumed.returncode, 1)
        self.assertEqual(json.loads(resumed.stdout)["status"], "failed")

    def test_refresh_supersedes_authority_removed_from_new_generation(self) -> None:
        store, engine = self.create_engine("mapping_conflict")
        engine.map_program()
        self.assertEqual(store.replay()["status"], "waiting_authority")
        (self.repo / "spec-a.md").write_text("# conflict removed\n", encoding="utf-8")
        self.env["CPE_FAKE_SCENARIO"] = "refresh_success"
        refreshed = self.cli("resume", "--run-id", store.run_id, "--refresh-inputs")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr or refreshed.stdout)
        state = RunStore.open(codex_home=self.home, run_id=store.run_id).replay()
        self.assertFalse(
            any(item["status"] == "waiting_authority" for item in state["authorities"].values())
        )

    def test_refresh_reopens_same_logical_authority_for_current_generation(self) -> None:
        store, engine = self.create_engine("mapping_conflict")
        engine.map_program()
        (self.repo / "spec-a.md").write_text("# conflict still current\n", encoding="utf-8")
        generation_id, documents, _ = store.refresh_inputs()
        refreshed = QueueEngine(
            store,
            engine.worktree,
            ChildLauncher(
                schema_path=SKILL_ROOT / "templates" / "child-result-schema.json",
                timeout_seconds=10,
                environ={**self.env, "CPE_FAKE_SCENARIO": "mapping_conflict"},
            ),
            generation_id=generation_id,
            documents=documents,
        )
        refreshed.map_program()
        state = store.replay()
        open_ids = [
            key for key, value in state["authorities"].items()
            if value["status"] == "waiting_authority"
        ]
        self.assertEqual(open_ids, [refreshed._authority_event_id("mapping-conflict-1")])

    def test_logical_authority_ids_with_colons_resolve_in_each_generation(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        engine._generation_number = 2
        engine._generation_id = "generation-0002"
        for index, authority_id in enumerate(
            ("spec:conflict", engine._authority_event_id("spec:conflict")), 1
        ):
            packet_path = f"reports/authority/logical-colon-{index}.json"
            store.put_artifact(
                packet_path,
                json.dumps(
                    {
                        "authority_items": [
                            {"authority_id": authority_id, "options": ["spec"]}
                        ]
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            store.append_event(
                "authority.opened",
                {
                    "authority_id": authority_id,
                    "authority_code": "authoritative_document_conflict",
                    "status": "waiting_authority",
                    "task_ids": ["plan-01:T1"],
                    "artifact_paths": [packet_path],
                },
            )
            cpe_cli.resolve_authority(store, authority_id, "spec")
            self.assertEqual(
                store.replay()["authorities"][authority_id]["status"], "resolved"
            )

    def test_removed_predecessor_task_is_explicitly_invalidated(self) -> None:
        store, engine = self.create_engine()
        engine.map_program()
        event = [
            item for item in store.validate_event_chain()
            if item["event_type"] == "map.generation_created"
        ][-1]
        _, artifacts = store.read_accepted_publication(
            event["payload"]["publication_manifest_path"],
            event["payload"]["publication_manifest_sha256"],
        )
        previous = json.loads(artifacts["maps/generation-0001/program-map.json"])
        retained = []
        published: dict[str, bytes] = {}
        for task in previous["tasks"][:-1]:
            copied = {**task, "predecessor_task_id": task["task_id"]}
            copied["brief_path"] = f"briefs/generation-0002/{task['task_id']}.json"
            retained.append(copied)
            published[copied["brief_path"]] = artifacts[task["brief_path"]]
        engine._generation_id = "generation-0002"
        engine._generation_number = 2
        invalidated = engine._invalidated_generation_tasks(
            {"tasks": retained}, published
        )
        self.assertIn(previous["tasks"][-1]["task_id"], invalidated)

    def test_completed_refresh_uses_generation_keyed_final_evidence(self) -> None:
        self.env["CPE_FAKE_SCENARIO"] = "refresh_success"
        initial = self.cli(
            "run",
            "--spec",
            str(self.repo / "spec-a.md"),
            "--spec",
            str(self.repo / "spec-b.md"),
            "--plan",
            str(self.repo / "plan-a.md"),
            "--plan",
            str(self.repo / "plan-b.md"),
            "--program-plan",
            str(self.repo / "program.md"),
            "--workspace",
            str(self.repo),
        )
        self.assertEqual(initial.returncode, 0, initial.stderr or initial.stdout)
        run_id = json.loads(initial.stdout)["run_id"]
        store = RunStore.open(codex_home=self.home, run_id=run_id)
        first_head = subprocess.run(
            ["git", "-C", str(self.home / "worktrees" / run_id), "rev-parse", "HEAD"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        (self.repo / "program.md").write_text("# refreshed program context\n", encoding="utf-8")
        refreshed = self.cli("resume", "--run-id", run_id, "--refresh-inputs")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr or refreshed.stdout)
        reopened = RunStore.open(codex_home=self.home, run_id=run_id)
        completions = [
            event for event in reopened.validate_event_chain()
            if event["event_type"] == "run.completed"
        ]
        self.assertEqual(len(completions), 2)
        self.assertNotEqual(completions[-1]["payload"]["commit"], first_head)
        self.assertTrue(
            any(
                path.startswith("verification/final/generation-0002/")
                for path in completions[-1]["payload"]["artifact_paths"]
            )
        )


if __name__ == "__main__":
    unittest.main()
