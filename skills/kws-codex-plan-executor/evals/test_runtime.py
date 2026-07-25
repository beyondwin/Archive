"""Focused contract tests for the initial CPE v3 runtime."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cpe_runtime.controller import (
    ControllerOutcome,
    ControllerRequest,
    ResumeCapsule,
    TerminalEnvelope,
)
from cpe_runtime.runtime import CpeRuntime
from cpe_runtime.state import DocumentSource, RunStore


SESSION_ID = "11111111-1111-4111-8111-111111111111"
ControllerAction = Callable[[ControllerRequest], str | None]


class FakeController:
    """A dependency-injected controller with real state and Git side effects."""

    def __init__(self, codex_home: Path) -> None:
        self.codex_home = codex_home
        self.requests: list[ControllerRequest] = []
        self.callback_states = []
        self.lock_was_held = False
        self.action: ControllerAction | None = None
        self.terminal_head: str | None = None
        self.claim = "completed"
        self.process_class = "completed"
        self.exit_code = 0
        self.resume_capsule: ResumeCapsule | None = None

    @staticmethod
    def _run_id(prompt: str) -> str:
        prefix = "RUN_ID="
        return next(line[len(prefix):] for line in prompt.splitlines() if line.startswith(prefix))

    @staticmethod
    def _git(worktree: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=worktree,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _opened_state(self, run_id: str):
        return RunStore.open(self.codex_home, run_id).state

    def launch(
        self,
        request: ControllerRequest,
        on_session_id: Callable[[str], None],
        on_process_started: Callable[[int, int], None],
    ) -> ControllerOutcome:
        self.requests.append(request)
        run_id = self._run_id(request.prompt)
        store = RunStore.open(self.codex_home, run_id)

        descriptor = os.open(store.lock_path, os.O_RDWR)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.lock_was_held = True
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

        on_process_started(4242, 4242)
        self.callback_states.append(self._opened_state(run_id))
        on_session_id(SESSION_ID)
        self.callback_states.append(self._opened_state(run_id))

        starting_head = self._git(request.worktree, "rev-parse", "HEAD")
        action_head = self.action(request) if self.action is not None else None
        terminal_head = self.terminal_head or action_head or starting_head
        return ControllerOutcome(
            session_id=SESSION_ID,
            exit_code=self.exit_code,
            process_class=self.process_class,
            terminal=TerminalEnvelope(
                claim=self.claim,
                head_commit=terminal_head,
                resume_capsule=self.resume_capsule,
                blocker=None,
            ),
            provider_code=None,
        )


class RuntimeContractTests(unittest.TestCase):
    """The runtime owns one mechanical launch and local Git handoff only."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp = Path(self.temporary_directory.name)
        self.original_environment = os.environ.copy()
        self.home = self.temp / "home"
        self.home.mkdir()
        self.codex_home = self.home / ".codex"
        os.environ.update(
            {
                "HOME": str(self.home),
                "CODEX_HOME": str(self.codex_home),
                "XDG_CONFIG_HOME": str(self.home / ".config"),
                "GIT_CONFIG_NOSYSTEM": "1",
            }
        )
        self.repository = self.temp / "repository"
        self.repository.mkdir()
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "Runtime Canary")
        self.git("config", "user.email", "runtime@example.invalid")
        (self.repository / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-q", "-m", "initial")
        self.base = self.git("rev-parse", "HEAD")

        source_root = self.temp / "documents"
        source_root.mkdir()
        document_payloads = (
            ("spec-a.md", b"heading-free prose\n[broken](missing.md)\n"),
            ("spec-b.weird", b"alpha contradicts beta\n"),
            ("plan-a.txt", b"beta contradicts alpha\n"),
            ("plan-b", b"\xff\x00opaque input\n"),
            ("incident.log", b"unfamiliar extension\n"),
            ("authority.bin", b"caller authority\n"),
        )
        self.document_paths = []
        for name, payload in document_payloads:
            path = source_root / name
            path.write_bytes(payload)
            self.document_paths.append(path)
        self.documents = tuple(DocumentSource(path) for path in self.document_paths)

        self.worktree_root = self.codex_home / "worktrees"
        self.schema_path = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "terminal-envelope.schema.json"
        )
        self.controller = FakeController(self.codex_home)
        self.runtime = CpeRuntime(
            codex_home=self.codex_home,
            worktree_root=self.worktree_root,
            controller=self.controller,
            schema_path=self.schema_path,
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.original_environment)
        self.temporary_directory.cleanup()

    def run_git(
        self,
        cwd: Path,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
        )

    def git(self, *arguments: str, check: bool = True) -> str:
        return self.run_git(self.repository, *arguments, check=check).stdout.strip()

    def git_at(self, cwd: Path, *arguments: str, check: bool = True) -> str:
        return self.run_git(cwd, *arguments, check=check).stdout.strip()

    def run_once(
        self,
        *,
        documents: tuple[DocumentSource, ...] | None = None,
        superpowers_skill: str = "subagent-driven-development",
        adopt_worktree_path: Path | None = None,
        base: str | None = None,
    ) -> dict[str, object]:
        return self.runtime.run(
            workspace=self.repository,
            documents=documents or self.documents,
            superpowers_skill=superpowers_skill,
            sandbox="workspace-write",
            adopt_worktree_path=adopt_worktree_path,
            base=base,
        )

    def store(self, run_id: str) -> RunStore:
        return RunStore.open(self.codex_home, run_id)

    def handoff_path(self, run_id: str) -> Path:
        return self.codex_home / "cpe-v3" / "runs" / run_id / "handoff.json"

    def read_handoff(self, run_id: str) -> dict[str, object]:
        return json.loads(self.handoff_path(run_id).read_text(encoding="utf-8"))

    def test_run_passes_all_opaque_documents_to_one_controller_in_order(self) -> None:
        result = self.run_once()

        self.assertEqual(result["status"], "handed_off")
        self.assertEqual(len(self.controller.requests), 1)
        manifest = self.store(str(result["run_id"])).manifest
        self.assertEqual(len(manifest.documents), len(self.documents))
        prompt = self.controller.requests[0].prompt
        offsets = [prompt.index(record.snapshot_path) for record in manifest.documents]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(
            [Path(record.snapshot_path).read_bytes() for record in manifest.documents],
            [path.read_bytes() for path in self.document_paths],
        )
        for forbidden in (
            "current_plan_index",
            "completed_task_ids",
            "TDD",
            "task review",
            "fix-round",
            "verification policy",
        ):
            self.assertNotIn(forbidden, prompt)

    def test_prompt_is_thin_and_selected_skill_is_required_and_sealed(self) -> None:
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.run_once(superpowers_skill="")
        self.assertEqual(self.git("branch", "--list", "codex/cpe-*"), "")
        self.assertFalse(
            self.worktree_root.exists() and any(self.worktree_root.iterdir())
        )

        result = self.run_once(superpowers_skill="executing-plans")
        store = self.store(str(result["run_id"]))
        request = self.controller.requests[0]
        required_sentences = (
            "Execute the immutable CPE document bundle in the assigned worktree.",
            "Read repository AGENTS.md. The manifest entries are caller-supplied "
            "documents in caller order; interpret and use them under Superpowers "
            "without asking CPE for document roles or validation.",
            "Use the installed Superpowers skill named in SUPERPOWERS_SKILL.",
            "Superpowers and Git own semantic progress and recovery.",
            "Do not merge, push, open a PR, tag, publish, release, or deploy.",
            "Return only the terminal envelope required by TERMINAL_SCHEMA.",
        )
        for sentence in required_sentences:
            self.assertIn(sentence, request.prompt)
        self.assertIn("SUPERPOWERS_SKILL=executing-plans", request.prompt)
        self.assertIn(f"TERMINAL_SCHEMA={self.schema_path}", request.prompt)
        self.assertEqual(store.manifest.superpowers_skill, "executing-plans")
        self.assertEqual(stat.S_IMODE(store.manifest_path.stat().st_mode), 0o400)

    def test_callbacks_persist_process_and_session_immediately_under_run_lock(self) -> None:
        result = self.run_once()

        self.assertTrue(self.controller.lock_was_held)
        process_state, session_state = self.controller.callback_states
        self.assertEqual(process_state.status, "running")
        self.assertEqual(process_state.active_pid, 4242)
        self.assertEqual(process_state.active_process_group, 4242)
        self.assertIsNone(process_state.controller_session_id)
        self.assertEqual(session_state.controller_session_id, SESSION_ID)
        final_state = self.store(str(result["run_id"])).state
        self.assertEqual(final_state.status, "handed_off")
        self.assertIsNone(final_state.active_pid)
        self.assertIsNone(final_state.active_process_group)
        self.assertEqual(final_state.last_process_class, "completed")
        self.assertEqual(final_state.last_exit_code, 0)

    def test_handoff_is_mechanical_local_only_and_state_is_bounded(self) -> None:
        result = self.run_once()
        run_id = str(result["run_id"])
        store = self.store(run_id)
        handoff = self.read_handoff(run_id)

        self.assertEqual(
            set(handoff),
            {
                "format_version",
                "run_id",
                "branch",
                "saved_worktree",
                "base_commit",
                "observed_head",
                "tracked_clean",
                "untracked_present",
                "controller_claim",
                "controller_session_id",
                "controller_generation",
                "integration",
                "remote_actions_by_cpe",
            },
        )
        self.assertEqual(handoff["controller_claim"], "completed")
        self.assertEqual(handoff["integration"], "not_observed")
        self.assertEqual(handoff["remote_actions_by_cpe"], "none")
        self.assertEqual(handoff["controller_session_id"], SESSION_ID)
        self.assertNotIn("verification", handoff)
        self.assertNotIn("findings", handoff)
        state_payload = store.state.to_payload()
        self.assertEqual(
            set(state_payload),
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
        public_payload = json.dumps({"result": result, "handoff": handoff})
        for source_path in self.document_paths:
            self.assertNotIn(str(source_path), public_payload)
        self.assertNotIn("runtime@example.invalid", public_payload)
        self.assertEqual(
            {path.name for path in store.root.iterdir()},
            {"inputs", "manifest.json", "state.json", "run.lock", "handoff.json"},
        )
        self.assertFalse(
            any(
                token in path.name
                for path in store.root.rglob("*")
                for token in ("receipt", "event", "transcript")
            )
        )

    def test_completed_claim_requires_exact_clean_head(self) -> None:
        self.controller.terminal_head = "b" * 40

        result = self.run_once()

        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["reason"], "handoff_incomplete")
        self.assertFalse(self.handoff_path(str(result["run_id"])).exists())

    def test_interruption_retains_one_bounded_capsule_and_last_process_facts(self) -> None:
        self.controller.claim = "interrupted"
        self.controller.process_class = "interrupted"
        self.controller.exit_code = 130
        self.controller.resume_capsule = ResumeCapsule(
            head_commit=self.base,
            worktree_status_digest="a" * 64,
            note="Continue from Git and Superpowers.",
            evidence_refs=("notes/evidence.txt",),
        )

        result = self.run_once()

        self.assertEqual(result["status"], "interrupted")
        state = self.store(str(result["run_id"])).state
        self.assertEqual(state.last_process_class, "interrupted")
        self.assertEqual(state.last_exit_code, 130)
        self.assertEqual(
            state.resume_capsule,
            {
                "head_commit": self.base,
                "worktree_status_digest": "a" * 64,
                "note": "Continue from Git and Superpowers.",
                "evidence_refs": ["notes/evidence.txt"],
            },
        )

    def test_tracked_dirt_wrong_branch_and_ancestry_violation_do_not_handoff(self) -> None:
        def tracked_dirt(request: ControllerRequest) -> str:
            (request.worktree / "tracked.txt").write_text("dirty\n", encoding="utf-8")
            return self.git_at(request.worktree, "rev-parse", "HEAD")

        def wrong_branch(request: ControllerRequest) -> str:
            self.git_at(request.worktree, "switch", "-q", "-c", "codex/wrong")
            return self.git_at(request.worktree, "rev-parse", "HEAD")

        def unrelated_head(request: ControllerRequest) -> str:
            tree = self.git_at(request.worktree, "write-tree")
            head = subprocess.run(
                ["git", "commit-tree", tree, "-m", "unrelated"],
                cwd=request.worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.git_at(request.worktree, "update-ref", "HEAD", head)
            return head

        for action in (tracked_dirt, wrong_branch, unrelated_head):
            with self.subTest(action=action.__name__):
                self.controller.action = action
                result = self.run_once()
                self.assertNotEqual(result["status"], "handed_off")
                self.assertFalse(self.handoff_path(str(result["run_id"])).exists())

    def test_moved_worktree_identity_does_not_handoff(self) -> None:
        def move_worktree(request: ControllerRequest) -> str:
            head = self.git_at(request.worktree, "rev-parse", "HEAD")
            destination = request.worktree.with_name(f"{request.worktree.name}-moved")
            self.git("worktree", "move", str(request.worktree), str(destination))
            return head

        self.controller.action = move_worktree
        result = self.run_once()

        self.assertNotEqual(result["status"], "handed_off")
        self.assertFalse(self.handoff_path(str(result["run_id"])).exists())

    def test_untracked_files_are_observed_without_semantic_failure(self) -> None:
        def add_untracked(request: ControllerRequest) -> str:
            (request.worktree / "controller-note.tmp").write_text(
                "untracked\n",
                encoding="utf-8",
            )
            return self.git_at(request.worktree, "rev-parse", "HEAD")

        self.controller.action = add_untracked
        result = self.run_once()

        self.assertEqual(result["status"], "handed_off")
        store = self.store(str(result["run_id"]))
        handoff = self.read_handoff(str(result["run_id"]))
        self.assertTrue(store.state.tracked_clean)
        self.assertTrue(store.state.untracked_present)
        self.assertTrue(handoff["untracked_present"])

    def test_initialization_cleanup_removes_only_a_newly_created_assignment(self) -> None:
        missing = DocumentSource(self.temp / "missing.md")

        with self.assertRaisesRegex(ValueError, "input"):
            self.run_once(documents=(missing,))

        self.assertEqual(self.controller.requests, [])
        self.assertEqual(self.git("branch", "--list", "codex/cpe-*"), "")
        self.assertFalse(
            self.worktree_root.exists() and any(self.worktree_root.iterdir())
        )

        adopted = self.temp / "adopted"
        self.git(
            "worktree",
            "add",
            "-q",
            "-b",
            "codex/adopted",
            str(adopted),
            self.base,
        )
        sentinel = adopted / "preserve.tmp"
        sentinel.write_text("preserve\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "input"):
            self.run_once(
                documents=(missing,),
                adopt_worktree_path=adopted,
                base=self.base,
            )
        self.assertTrue(adopted.is_dir())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve\n")


if __name__ == "__main__":
    unittest.main()
