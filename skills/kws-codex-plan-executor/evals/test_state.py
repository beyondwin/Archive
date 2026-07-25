"""Focused contract tests for the format-5 durability capsule."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.state import (
    CONTRACT_VERSION,
    FORMAT_VERSION,
    DocumentSource,
    GitIdentity,
    RunLock,
    RunManifest,
    RunState,
    RunStore,
    read_legacy_format,
    snapshot_documents,
    validate_resume_capsule,
)


class StateContractTests(unittest.TestCase):
    """The public state boundary accepts opaque files and structural facts only."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.codex_home = self.base / "codex-home"
        self.run_id = "cpe-0123456789abcdef"
        self.root = self.codex_home / "cpe-v3" / "runs" / self.run_id
        self.sources = self.base / "sources"
        self.sources.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_bytes(self, name: str, payload: bytes) -> Path:
        path = self.sources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def snapshot_one_document(self) -> tuple:
        return snapshot_documents(
            run_root=self.root,
            sources=(DocumentSource(self.write_bytes("plan.md", b"# Plan\n")),),
        )

    def manifest(self, records: tuple) -> RunManifest:
        return RunManifest(
            format_version=5,
            contract_version=3,
            run_id=self.run_id,
            source_repository=str(self.sources),
            base_commit="a" * 40,
            branch=f"codex/{self.run_id}",
            worktree=str(self.base / "worktree"),
            documents=records,
            superpowers_skill="executing-plans",
            git_identity=GitIdentity(
                author_name="CPE Author",
                author_email="author@example.test",
                committer_name="CPE Committer",
                committer_email="committer@example.test",
            ),
            sandbox="danger-full-access",
            approval_policy="operator-required",
            integration_policy="not-observed",
            remote_action_policy="prohibited",
            created_at="2026-07-25T00:00:00+00:00",
        )

    def state(self) -> RunState:
        return RunState(
            status="prepared",
            controller_session_id=None,
            controller_generation=0,
            fresh_fallback_used=False,
            active_pid=None,
            active_process_group=None,
            last_observed_head="a" * 40,
            tracked_clean=True,
            untracked_present=False,
            status_digest="b" * 64,
            last_process_class=None,
            last_exit_code=None,
            resume_capsule=None,
            blocker=None,
            updated_at="2026-07-25T00:00:00+00:00",
        )

    def create_store(self) -> RunStore:
        return RunStore.create(
            codex_home=self.codex_home,
            manifest=self.manifest(self.snapshot_one_document()),
            state=self.state(),
        )

    def replace_with_external_byte_identical_symlink(self, path: Path) -> None:
        external = self.base / f"external-{path.name}"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)

    def valid_state_payload(self) -> dict[str, object]:
        return self.state().to_payload()

    def write_legacy_payload(
        self,
        run_id: str,
        payload: object,
    ) -> Path:
        root = self.codex_home / "orchestrator" / run_id
        root.mkdir(parents=True)
        state = root / "state.json"
        state.write_text(json.dumps(payload), encoding="utf-8")
        return state

    def test_snapshots_opaque_documents_in_global_order(self) -> None:
        records = snapshot_documents(
            run_root=self.root,
            sources=(
                DocumentSource(self.write_bytes("a/shared.md", b"# Design\n")),
                DocumentSource(self.write_bytes("b/shared.md", b"not a task list")),
                DocumentSource(self.write_bytes("c/shared.md", b"\xff\x00opaque")),
                DocumentSource(self.write_bytes("incident.txt", b"[broken](missing.md)")),
            ),
        )
        self.assertEqual(
            [Path(record.snapshot_path).name for record in records],
            [
                "document-001-shared.md",
                "document-002-shared.md",
                "document-003-shared.md",
                "document-004-incident.txt",
            ],
        )
        self.assertEqual(
            [Path(record.snapshot_path).read_bytes() for record in records],
            [b"# Design\n", b"not a task list", b"\xff\x00opaque", b"[broken](missing.md)"],
        )
        self.assertEqual([record.order for record in records], [1, 2, 3, 4])

    def test_snapshot_rejects_unsafe_or_empty_input_identities(self) -> None:
        document = self.write_bytes("document.md", b"content")
        directory = self.sources / "directory"
        directory.mkdir()
        symlink = self.sources / "link.md"
        symlink.symlink_to(document)
        hard_link = self.sources / "hard-link.md"
        os.link(document, hard_link)
        cases = (
            (),
            (DocumentSource(Path("relative.md")),),
            (DocumentSource(symlink),),
            (DocumentSource(directory),),
            (DocumentSource(document), DocumentSource(document)),
            (DocumentSource(document), DocumentSource(hard_link)),
        )
        for number, sources in enumerate(cases, start=1):
            with self.subTest(sources=sources):
                with self.assertRaisesRegex(ValueError, "input"):
                    snapshot_documents(
                        run_root=self.base / f"invalid-{number}",
                        sources=sources,
                    )

    def test_state_rejects_semantic_workflow_fields(self) -> None:
        payload = self.valid_state_payload()
        payload["completed_task_ids"] = []
        with self.assertRaisesRegex(ValueError, "format-5 state"):
            RunStore.validate_state_payload(payload)

    def test_approved_interfaces_have_exact_payloads_and_derived_store_root(self) -> None:
        manifest = self.manifest(self.snapshot_one_document())
        state = self.state()
        self.assertEqual(
            set(manifest.to_payload()),
            {
                "format_version", "contract_version", "run_id", "source_repository",
                "base_commit", "branch", "worktree", "documents", "superpowers_skill",
                "git_identity", "sandbox", "approval_policy", "integration_policy",
                "remote_action_policy", "created_at",
            },
        )
        self.assertEqual(
            set(state.to_payload()),
            {
                "status", "controller_session_id", "controller_generation",
                "fresh_fallback_used", "active_pid", "active_process_group",
                "last_observed_head", "tracked_clean", "untracked_present",
                "status_digest", "last_process_class", "last_exit_code",
                "resume_capsule", "blocker", "updated_at",
            },
        )
        store = RunStore.create(self.codex_home, manifest, state)
        self.assertEqual(store.root, self.root.resolve())
        self.assertEqual(RunStore.open(self.codex_home, self.run_id).state, state)

    def test_open_rejects_manifest_for_a_different_run_id(self) -> None:
        store = self.create_store()
        payload = json.loads(store.manifest_path.read_text(encoding="utf-8"))
        payload["run_id"] = "cpe-fedcba9876543210"
        store.manifest_path.chmod(0o600)
        store.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "run identity"):
            RunStore.open(self.codex_home, self.run_id)

    def test_open_rejects_external_byte_identical_manifest_symlink(self) -> None:
        store = self.create_store()
        self.replace_with_external_byte_identical_symlink(store.manifest_path)

        with self.assertRaisesRegex(ValueError, "run state is unavailable"):
            RunStore.open(self.codex_home, self.run_id)

    def test_open_rejects_external_byte_identical_state_symlink(self) -> None:
        store = self.create_store()
        self.replace_with_external_byte_identical_symlink(store.state_path)

        with self.assertRaisesRegex(ValueError, "run state is unavailable"):
            RunStore.open(self.codex_home, self.run_id)

    def test_open_rejects_fifo_state_without_blocking(self) -> None:
        store = self.create_store()
        store.state_path.unlink()
        os.mkfifo(store.state_path, mode=0o600)
        child = (
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from cpe_runtime.state import RunStore\n"
            "try:\n"
            "    RunStore.open(Path(sys.argv[2]), sys.argv[3])\n"
            "except ValueError:\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit('FIFO state was accepted')\n"
        )
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(Path(__file__).resolve().parents[1] / "scripts"),
                    str(self.codex_home),
                    self.run_id,
                ],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("RunStore.open blocked on a FIFO for 1.0 seconds")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_manifest_validator_rejects_missing_and_additional_fields(self) -> None:
        payload = self.manifest(self.snapshot_one_document()).to_payload()
        for invalid in (
            {**payload, "completed_task_ids": []},
            {key: value for key, value in payload.items() if key != "created_at"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "format-5 manifest"):
                    RunStore.validate_manifest_payload(invalid)

    def test_state_contract_has_exact_keys_and_generation_relation(self) -> None:
        payload = self.valid_state_payload()
        self.assertEqual(
            set(payload),
            {
                "status",
                "controller_session_id",
                "controller_generation",
                "fresh_fallback_used",
                "active_pid",
                "active_process_group",
                "last_observed_head",
                "tracked_clean",
                "untracked_present",
                "status_digest",
                "last_process_class",
                "last_exit_code",
                "resume_capsule",
                "blocker",
                "updated_at",
            },
        )
        for status in (
            "prepared", "running", "interrupted", "blocked", "failed", "handed_off",
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    RunStore.validate_state_payload({**payload, "status": status})["status"],
                    status,
                )
        for changed in (
            {**payload, "controller_generation": 2},
            {**payload, "controller_generation": 1},
            {**payload, "status": "completed"},
            {**payload, "last_observed_head": "wrong"},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ValueError, "format-5 state"):
                    RunStore.validate_state_payload(changed)
        fallback = {**payload, "controller_generation": 1, "fresh_fallback_used": True}
        self.assertEqual(RunStore.validate_state_payload(fallback), fallback)

    def test_manifest_is_read_only_after_creation(self) -> None:
        store = self.create_store()
        self.assertEqual(stat.S_IMODE(store.manifest_path.stat().st_mode), 0o400)
        with self.assertRaises(PermissionError):
            store.manifest_path.write_text("changed", encoding="utf-8")

    def test_store_persists_only_contract_artifacts_with_private_modes(self) -> None:
        store = self.create_store()
        self.assertEqual(stat.S_IMODE(store.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(store.state_path.stat().st_mode), 0o600)
        self.assertEqual(set(json.loads(store.manifest_path.read_text(encoding="utf-8"))), {
            "format_version", "contract_version", "run_id", "source_repository",
            "base_commit", "branch", "worktree", "documents", "superpowers_skill",
            "git_identity", "sandbox", "approval_policy", "integration_policy",
            "remote_action_policy", "created_at",
        })
        store.write_handoff({"claim": "interrupted"})
        self.assertEqual(stat.S_IMODE(store.handoff_path.stat().st_mode), 0o600)
        store.save_state(replace(self.state(), status="running"))
        self.assertEqual(
            json.loads(store.state_path.read_text(encoding="utf-8"))["status"],
            "running",
        )
        self.assertFalse(list(store.root.glob(".*.tmp")))

    def test_store_rejects_artifacts_other_than_input_snapshots(self) -> None:
        records = self.snapshot_one_document()
        (self.root / "unexpected.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "prepared run root"):
            RunStore.create(
                codex_home=self.codex_home,
                manifest=self.manifest(records),
                state=self.state(),
            )

    def test_store_rejects_undeclared_input_symlink_to_declared_snapshot(self) -> None:
        records = self.snapshot_one_document()
        (self.root / "inputs" / "undeclared-link.md").symlink_to(
            records[0].snapshot_path,
        )
        with self.assertRaisesRegex(ValueError, "manifest documents"):
            RunStore.create(
                codex_home=self.codex_home,
                manifest=self.manifest(records),
                state=self.state(),
            )

    def test_run_lock_refuses_a_second_writer(self) -> None:
        store = self.create_store()
        with store.lock() as lock:
            self.assertIsInstance(lock.fileno(), int)
            self.assertEqual(stat.S_IMODE(store.lock_path.stat().st_mode), 0o600)
            with self.assertRaises(BlockingIOError):
                with store.lock():
                    pass

    def test_failed_run_lock_contender_closes_its_descriptor(self) -> None:
        store = self.create_store()
        contender = store.lock()
        contender_descriptor: int | None = None
        try:
            with store.lock():
                contender_descriptor = os.open(os.devnull, os.O_RDONLY)
                os.close(contender_descriptor)
                with self.assertRaises(BlockingIOError):
                    contender.__enter__()

            self.assertIsNone(contender.descriptor)
            with self.assertRaisesRegex(RuntimeError, "run lock is not held"):
                contender.fileno()
            with self.assertRaises(OSError):
                os.fstat(contender_descriptor)
        finally:
            for descriptor in {contender_descriptor, contender.descriptor} - {None}:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            contender.descriptor = None

    def test_resume_capsule_bounds_are_structural_only(self) -> None:
        valid = {
            "head_commit": "a" * 40,
            "worktree_status_digest": "b" * 64,
            "note": "continue from the existing worktree",
            "evidence_refs": ["evidence/result.txt"],
        }
        self.assertEqual(validate_resume_capsule(valid)["note"], valid["note"])
        invalid = dict(valid, note="x" * 2049)
        with self.assertRaisesRegex(ValueError, "resume capsule"):
            validate_resume_capsule(invalid)
        non_ascii = dict(valid, note="가" * 683)
        with self.assertRaisesRegex(ValueError, "resume capsule"):
            validate_resume_capsule(non_ascii)

    def test_legacy_reader_uses_only_root_format_and_preserves_bytes(self) -> None:
        for format_version in range(1, 5):
            with self.subTest(format_version=format_version):
                run_id = f"cpe-{format_version:016x}"
                state = self.write_legacy_payload(
                    run_id,
                    {
                        "format_version": format_version,
                        "nested": {"format_version": 99},
                        "opaque": ["legacy", {"tasks": ["unparsed"]}],
                    },
                )
                before = (
                    state.read_bytes(),
                    stat.S_IMODE(state.stat().st_mode),
                    state.stat().st_mtime_ns,
                )

                detected, run_root = read_legacy_format(self.codex_home, run_id)

                after = (
                    state.read_bytes(),
                    stat.S_IMODE(state.stat().st_mode),
                    state.stat().st_mtime_ns,
                )
                self.assertEqual(detected, format_version)
                self.assertEqual(run_root, state.parent.resolve())
                self.assertEqual(after, before)

    def test_legacy_reader_rejects_symlink_oversize_and_non_root_version(self) -> None:
        external = self.base / "external-legacy.json"
        external.write_text('{"format_version":3}', encoding="utf-8")
        symlink_id = "cpe-1000000000000000"
        symlink_root = self.codex_home / "orchestrator" / symlink_id
        symlink_root.mkdir(parents=True)
        (symlink_root / "state.json").symlink_to(external)
        oversize_id = "cpe-2000000000000000"
        self.write_legacy_payload(
            oversize_id,
            {"format_version": 3, "padding": "x" * (64 * 1024)},
        )
        nested_id = "cpe-3000000000000000"
        self.write_legacy_payload(nested_id, {"nested": {"format_version": 3}})
        exact_path_id = "cpe-4000000000000000"
        nested_root = (
            self.codex_home
            / "orchestrator"
            / exact_path_id
            / "nested"
        )
        nested_root.mkdir(parents=True)
        (nested_root / "state.json").write_text(
            '{"format_version":3}',
            encoding="utf-8",
        )

        for run_id in (symlink_id, oversize_id, nested_id, exact_path_id):
            with self.subTest(run_id=run_id):
                with self.assertRaisesRegex(ValueError, "legacy run state"):
                    read_legacy_format(self.codex_home, run_id)


if __name__ == "__main__":
    unittest.main()
