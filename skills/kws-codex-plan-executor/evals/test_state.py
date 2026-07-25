"""Focused contract tests for the format-5 durability capsule."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
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
    snapshot_documents,
    validate_resume_capsule,
)


class StateContractTests(unittest.TestCase):
    """The public state boundary accepts opaque files and structural facts only."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.root = self.base / "run"
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
            run_id="cpe-0123456789abcdef",
            git=GitIdentity(
                head_commit="a" * 40,
                worktree_status_digest="b" * 64,
            ),
            documents=records,
            superpowers_skills=("subagent-driven-development", "executing-plans"),
            sandbox="danger-full-access",
        )

    def state(self) -> RunState:
        return RunState(
            run_id="cpe-0123456789abcdef",
            status="prepared",
            controller_generation=0,
            fresh_fallback_used=False,
        )

    def create_store(self) -> RunStore:
        return RunStore.create(
            run_root=self.root,
            manifest=self.manifest(self.snapshot_one_document()),
            state=self.state(),
        )

    def valid_state_payload(self) -> dict[str, object]:
        return self.state().to_payload()

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

    def test_state_contract_has_exact_keys_and_generation_relation(self) -> None:
        payload = self.valid_state_payload()
        self.assertEqual(
            set(payload),
            {
                "format_version",
                "contract_version",
                "run_id",
                "status",
                "controller_generation",
                "fresh_fallback_used",
            },
        )
        self.assertEqual(payload["format_version"], 5)
        self.assertEqual(payload["contract_version"], 3)
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
            {**payload, "run_id": "wrong"},
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
            "format_version", "contract_version", "run_id", "git", "documents",
            "superpowers_skills", "sandbox",
        })
        store.write_handoff({"claim": "interrupted"})
        self.assertEqual(stat.S_IMODE(store.handoff_path.stat().st_mode), 0o600)
        store.save_state(
            RunState(
                run_id="cpe-0123456789abcdef",
                status="running",
                controller_generation=0,
                fresh_fallback_used=False,
            )
        )
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
                run_root=self.root,
                manifest=self.manifest(records),
                state=self.state(),
            )

    def test_run_lock_refuses_a_second_writer(self) -> None:
        store = self.create_store()
        with RunLock(store.lock_path) as lock:
            self.assertIsInstance(lock.fileno(), int)
            self.assertEqual(stat.S_IMODE(store.lock_path.stat().st_mode), 0o600)
            with self.assertRaises(BlockingIOError):
                with RunLock(store.lock_path):
                    pass

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


if __name__ == "__main__":
    unittest.main()
