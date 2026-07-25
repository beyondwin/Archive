"""Focused contract tests for the initial CPE v3 runtime."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable
from unittest.mock import patch

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
NEW_SESSION_ID = "22222222-2222-4222-8222-222222222222"
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
        self.outcomes: list[ControllerOutcome] = []
        self.suppress_session_callback = False

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
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if (
                request.session_id is None
                and outcome.session_id is not None
                and not self.suppress_session_callback
            ):
                on_session_id(outcome.session_id)
                self.callback_states.append(self._opened_state(run_id))
            return outcome
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

    def completed(self) -> TerminalEnvelope:
        return TerminalEnvelope("completed", self.base, None, None)

    def interrupted(
        self,
        note: str = "Continue from the existing Superpowers and Git state.",
    ) -> TerminalEnvelope:
        return TerminalEnvelope(
            "interrupted",
            self.base,
            ResumeCapsule(
                self.base,
                "a" * 64,
                note,
                ("notes/evidence.txt",),
            ),
            None,
        )

    def outcome(
        self,
        process_class: str,
        *,
        terminal: TerminalEnvelope | None,
        session_id: str | None = SESSION_ID,
    ) -> ControllerOutcome:
        provider_code = None
        normalized_class = process_class
        exit_code = 0 if process_class == "completed" else 1
        if process_class == "session_unavailable":
            normalized_class = "failed"
            provider_code = "session_unavailable"
        elif process_class in {"auth", "quota", "provider_unavailable"}:
            normalized_class = "blocked"
            provider_code = process_class
        elif process_class == "transport":
            normalized_class = "failed"
            provider_code = "transport"
        elif process_class == "generic_nonzero":
            normalized_class = "failed"
            provider_code = "unknown"
            exit_code = 7
        elif process_class == "timeout":
            normalized_class = "interrupted"
            provider_code = "transport"
            exit_code = 124
        elif process_class == "interrupted":
            exit_code = 130
        return ControllerOutcome(
            session_id,
            exit_code,
            normalized_class,
            terminal,
            provider_code,
        )

    def create_interrupted_run(
        self,
        note: str = "Continue from the existing Superpowers and Git state.",
    ) -> str:
        self.controller.claim = "interrupted"
        self.controller.process_class = "interrupted"
        self.controller.exit_code = 130
        self.controller.resume_capsule = self.interrupted(note).resume_capsule
        result = self.run_once()
        self.controller.requests.clear()
        self.controller.callback_states.clear()
        return str(result["run_id"])

    def create_generation_one_interrupted_run(self) -> str:
        run_id = self.create_interrupted_run()
        self.controller.outcomes = [
            self.outcome("session_unavailable", terminal=None),
            self.outcome(
                "interrupted",
                terminal=self.interrupted(),
                session_id=NEW_SESSION_ID,
            ),
        ]
        result = self.runtime.resume(run_id=run_id)
        self.assertEqual(result["status"], "interrupted")
        self.controller.requests.clear()
        self.controller.callback_states.clear()
        return run_id

    def create_orphan_handoff(self) -> str:
        real_write = RunStore.write_handoff
        runs_root = self.codex_home / "cpe-v3" / "runs"
        before = set(runs_root.iterdir()) if runs_root.exists() else set()

        def crash_after_write(store: RunStore, payload: dict[str, object]) -> Path:
            real_write(store, payload)
            raise KeyboardInterrupt("simulated parent interruption after handoff write")

        with patch.object(
            RunStore,
            "write_handoff",
            autospec=True,
            side_effect=crash_after_write,
        ):
            with self.assertRaisesRegex(KeyboardInterrupt, "simulated parent"):
                self.run_once()
        run_roots = set(runs_root.iterdir()) - before
        self.assertEqual(len(run_roots), 1)
        self.controller.requests.clear()
        self.controller.callback_states.clear()
        return run_roots.pop().name

    def resume_after_competing_state_change(
        self,
        run_id: str,
        **changes: object,
    ) -> tuple[dict[str, object], bytes]:
        real_open = RunStore.open
        authoritative_state: list[bytes] = []
        open_count = 0

        def open_around_competing_writer(
            codex_home: Path,
            selected_run_id: str,
        ) -> RunStore:
            nonlocal open_count
            store = real_open(codex_home, selected_run_id)
            open_count += 1
            if open_count == 1:
                competing_store = real_open(codex_home, selected_run_id)
                with competing_store.lock():
                    competing_store.save_state(
                        replace(competing_store.state, **changes)
                    )
                    authoritative_state.append(
                        competing_store.state_path.read_bytes()
                    )
            return store

        with patch.object(
            RunStore,
            "open",
            side_effect=open_around_competing_writer,
        ):
            result = self.runtime.resume(run_id=run_id)

        self.assertEqual(len(authoritative_state), 1)
        return result, authoritative_state[0]

    def write_legacy_state(
        self,
        *,
        format_version: int,
        run_id: str | None = None,
    ) -> Path:
        selected = run_id or f"cpe-{format_version:016x}"
        root = self.codex_home / "orchestrator" / selected
        root.mkdir(parents=True)
        state = root / "state.json"
        state.write_text(
            json.dumps({"format_version": format_version, "opaque": {"task": "legacy"}}),
            encoding="utf-8",
        )
        (root / "evidence.bin").write_bytes(b"legacy evidence\x00")
        return state

    @staticmethod
    def hash_tree(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            metadata = path.lstat()
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(f"{metadata.st_mode}:{metadata.st_size}:{metadata.st_mtime_ns}".encode())
            if path.is_file():
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_resume_uses_saved_session_before_any_fallback(self) -> None:
        run_id = self.create_interrupted_run()
        original = self.store(run_id).state.controller_session_id
        self.controller.outcomes = [
            self.outcome("completed", terminal=self.completed(), session_id=original),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "handed_off")
        self.assertEqual(self.controller.requests[-1].session_id, original)
        self.assertEqual(self.store(run_id).state.controller_generation, 0)
        self.assertFalse(self.store(run_id).state.fresh_fallback_used)

    def test_resume_reconciles_valid_orphan_handoff_without_controller_launch(self) -> None:
        run_id = self.create_orphan_handoff()
        store = self.store(run_id)
        worktree = Path(store.manifest.worktree)
        self.assertEqual(store.state.status, "interrupted")
        handoff_before = store.handoff_path.read_bytes()
        head_before = self.git_at(worktree, "rev-parse", "HEAD")
        status_before = self.git_at(
            worktree,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(
            result,
            {
                "status": "handed_off",
                "run_id": run_id,
                "handoff_path": str(store.handoff_path),
            },
        )
        self.assertEqual(self.controller.requests, [])
        self.assertEqual(self.store(run_id).state.status, "handed_off")
        self.assertEqual(store.handoff_path.read_bytes(), handoff_before)
        self.assertEqual(self.git_at(worktree, "rev-parse", "HEAD"), head_before)
        self.assertEqual(
            self.git_at(
                worktree,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ),
            status_before,
        )

    def test_resume_rejects_malformed_or_mismatched_orphan_handoff(self) -> None:
        run_id = self.create_orphan_handoff()
        store = self.store(run_id)
        worktree = Path(store.manifest.worktree)
        original = self.read_handoff(run_id)
        state_before = store.state_path.read_bytes()
        mismatches = {
            "run_id": "cpe-0000000000000000",
            "branch": "codex/wrong",
            "saved_worktree": f"{worktree}-other",
            "base_commit": "f" * 40,
            "observed_head": "f" * 40,
            "tracked_clean": False,
            "untracked_present": not original["untracked_present"],
            "controller_session_id": NEW_SESSION_ID,
            "controller_generation": 1,
        }
        cases = [("malformed", b"{")]
        cases += [
            (name, json.dumps({**original, name: value}).encode("utf-8"))
            for name, value in mismatches.items()
        ]
        for name, handoff_bytes in cases:
            with self.subTest(name=name):
                store.handoff_path.write_bytes(handoff_bytes)
                handoff_before = store.handoff_path.read_bytes()
                head_before = self.git_at(worktree, "rev-parse", "HEAD")

                with self.assertRaisesRegex(ValueError, "handoff"):
                    self.runtime.resume(run_id=run_id)

                self.assertEqual(self.controller.requests, [])
                self.assertEqual(store.state_path.read_bytes(), state_before)
                self.assertEqual(store.handoff_path.read_bytes(), handoff_before)
                self.assertEqual(self.git_at(worktree, "rev-parse", "HEAD"), head_before)

    def test_resume_rejects_stale_orphan_handoff_without_controller_launch(self) -> None:
        run_id = self.create_orphan_handoff()
        store = self.store(run_id)
        worktree = Path(store.manifest.worktree)
        (worktree / "tracked.txt").write_text("advanced\n", encoding="utf-8")
        self.git_at(worktree, "add", "tracked.txt")
        self.git_at(worktree, "commit", "-q", "-m", "advance after handoff")
        state_before = store.state_path.read_bytes()
        handoff_before = store.handoff_path.read_bytes()
        head_before = self.git_at(worktree, "rev-parse", "HEAD")

        with self.assertRaisesRegex(ValueError, "handoff"):
            self.runtime.resume(run_id=run_id)

        self.assertEqual(self.controller.requests, [])
        self.assertEqual(store.state_path.read_bytes(), state_before)
        self.assertEqual(store.handoff_path.read_bytes(), handoff_before)
        self.assertEqual(self.git_at(worktree, "rev-parse", "HEAD"), head_before)

    def test_resume_rejects_orphan_when_only_status_digest_changed(self) -> None:
        def add_untracked(request: ControllerRequest) -> str:
            (request.worktree / "before.tmp").write_text("untracked\n", encoding="utf-8")
            return self.git_at(request.worktree, "rev-parse", "HEAD")

        self.controller.action = add_untracked
        run_id = self.create_orphan_handoff()
        store = self.store(run_id)
        worktree = Path(store.manifest.worktree)
        (worktree / "before.tmp").rename(worktree / "after.tmp")
        state_before = store.state_path.read_bytes()
        handoff_before = store.handoff_path.read_bytes()
        head_before = self.git_at(worktree, "rev-parse", "HEAD")

        with self.assertRaisesRegex(ValueError, "handoff"):
            self.runtime.resume(run_id=run_id)

        self.assertEqual(self.controller.requests, [])
        self.assertEqual(store.state_path.read_bytes(), state_before)
        self.assertEqual(store.handoff_path.read_bytes(), handoff_before)
        self.assertEqual(self.git_at(worktree, "rev-parse", "HEAD"), head_before)

    def test_resume_rejects_symlink_or_nonregular_orphan_handoff(self) -> None:
        for name in ("symlink", "fifo"):
            with self.subTest(name=name):
                run_id = self.create_orphan_handoff()
                store = self.store(run_id)
                state_before = store.state_path.read_bytes()
                handoff_before = store.handoff_path.read_bytes()
                store.handoff_path.unlink()
                external = self.temp / f"{run_id}-external-handoff.json"
                if name == "symlink":
                    external.write_bytes(handoff_before)
                    store.handoff_path.symlink_to(external)
                else:
                    os.mkfifo(store.handoff_path)

                with self.assertRaisesRegex(ValueError, "handoff"):
                    self.runtime.resume(run_id=run_id)

                self.assertEqual(self.controller.requests, [])
                self.assertEqual(store.state_path.read_bytes(), state_before)
                if name == "symlink":
                    self.assertTrue(store.handoff_path.is_symlink())
                    self.assertEqual(external.read_bytes(), handoff_before)
                else:
                    self.assertTrue(stat.S_ISFIFO(store.handoff_path.lstat().st_mode))

    def test_resume_rejects_handed_off_run_without_mutation_or_controller_launch(self) -> None:
        completed = self.run_once()
        run_id = str(completed["run_id"])
        store = self.store(run_id)
        worktree = Path(store.manifest.worktree)
        state_before = store.state_path.read_bytes()
        handoff_before = store.handoff_path.read_bytes()
        head_before = self.git_at(worktree, "rev-parse", "HEAD")
        status_before = self.git_at(
            worktree,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        self.controller.requests.clear()
        self.controller.callback_states.clear()

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(
            result,
            {
                "status": "blocked",
                "run_id": run_id,
                "reason": "run_already_handed_off",
            },
        )
        self.assertEqual(self.controller.requests, [])
        self.assertEqual(store.state_path.read_bytes(), state_before)
        self.assertEqual(store.handoff_path.read_bytes(), handoff_before)
        self.assertEqual(self.git_at(worktree, "rev-parse", "HEAD"), head_before)
        self.assertEqual(
            self.git_at(
                worktree,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ),
            status_before,
        )

    def test_resume_rechecks_handed_off_state_after_acquiring_run_lock(self) -> None:
        run_id = self.create_interrupted_run()
        stale_store = self.store(run_id)
        worktree = Path(stale_store.manifest.worktree)
        real_open = RunStore.open
        authoritative: dict[str, bytes | str] = {}

        @contextmanager
        def lock_after_competing_handoff(shared: bool = False):
            competing_store = real_open(self.codex_home, run_id)
            with competing_store.lock():
                competing_store.write_handoff({"sentinel": "competing-writer"})
                competing_store.save_state(
                    replace(competing_store.state, status="handed_off")
                )
                authoritative["state"] = competing_store.state_path.read_bytes()
                authoritative["handoff"] = competing_store.handoff_path.read_bytes()
                authoritative["head"] = self.git_at(worktree, "rev-parse", "HEAD")
                authoritative["status"] = self.git_at(
                    worktree,
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                )
            with RunStore.lock(stale_store, shared=shared) as lock:
                yield lock

        stale_store.lock = lock_after_competing_handoff
        opened = False

        def open_stale_once(codex_home: Path, selected_run_id: str) -> RunStore:
            nonlocal opened
            if not opened:
                opened = True
                return stale_store
            return real_open(codex_home, selected_run_id)

        with patch.object(RunStore, "open", side_effect=open_stale_once):
            result = self.runtime.resume(run_id=run_id)

        self.assertEqual(
            result,
            {
                "status": "blocked",
                "run_id": run_id,
                "reason": "run_already_handed_off",
            },
        )
        self.assertEqual(self.controller.requests, [])
        final_store = self.store(run_id)
        self.assertEqual(final_store.state_path.read_bytes(), authoritative["state"])
        self.assertEqual(final_store.handoff_path.read_bytes(), authoritative["handoff"])
        self.assertEqual(self.git_at(worktree, "rev-parse", "HEAD"), authoritative["head"])
        self.assertEqual(
            self.git_at(
                worktree,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ),
            authoritative["status"],
        )

    def test_resume_uses_authoritative_session_after_competing_generation_advance(
        self,
    ) -> None:
        run_id = self.create_interrupted_run()
        original_session = self.store(run_id).state.controller_session_id
        self.assertEqual(original_session, SESSION_ID)
        self.controller.outcomes = [
            self.outcome(
                "completed",
                terminal=self.completed(),
                session_id=NEW_SESSION_ID,
            ),
        ]
        result, _authoritative_state = self.resume_after_competing_state_change(
            run_id,
            controller_session_id=NEW_SESSION_ID,
            controller_generation=1,
            fresh_fallback_used=True,
        )
        self.assertEqual(result["status"], "handed_off")
        self.assertEqual(len(self.controller.requests), 1)
        request = self.controller.requests[0]
        self.assertEqual(request.mode, "resume")
        self.assertEqual(request.session_id, NEW_SESSION_ID)
        self.assertNotEqual(request.session_id, original_session)
        self.assertEqual(request.generation, 1)
        final_store = self.store(run_id)
        self.assertEqual(final_store.state.status, "handed_off")
        self.assertEqual(final_store.state.controller_session_id, NEW_SESSION_ID)
        self.assertEqual(final_store.state.controller_generation, 1)
        self.assertTrue(final_store.state.fresh_fallback_used)
        handoff = self.read_handoff(run_id)
        self.assertEqual(handoff["controller_session_id"], NEW_SESSION_ID)
        self.assertEqual(handoff["controller_generation"], 1)

    def test_resume_rechecks_authoritative_missing_session_before_launch(
        self,
    ) -> None:
        run_id = self.create_interrupted_run()
        result, authoritative_state = self.resume_after_competing_state_change(
            run_id,
            controller_session_id=None,
        )
        self.assertEqual(
            result,
            {
                "status": "blocked",
                "run_id": run_id,
                "reason": "saved_session_unavailable",
            },
        )
        self.assertEqual(self.controller.requests, [])
        self.assertEqual(
            self.store(run_id).state_path.read_bytes(),
            authoritative_state,
        )
        self.assertFalse(self.handoff_path(run_id).exists())

    def test_explicit_missing_session_allows_one_fresh_fallback(self) -> None:
        run_id = self.create_interrupted_run()
        self.controller.outcomes = [
            self.outcome("session_unavailable", terminal=None),
            self.outcome(
                "completed",
                terminal=self.completed(),
                session_id=NEW_SESSION_ID,
            ),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "handed_off")
        self.assertIsNotNone(self.controller.requests[0].session_id)
        self.assertIsNone(self.controller.requests[1].session_id)
        state = self.store(run_id).state
        self.assertEqual(state.controller_generation, 1)
        self.assertTrue(state.fresh_fallback_used)

    def test_second_session_loss_blocks_without_launching_generation_two(self) -> None:
        run_id = self.create_generation_one_interrupted_run()
        self.controller.outcomes = [
            self.outcome(
                "session_unavailable",
                terminal=None,
                session_id=NEW_SESSION_ID,
            ),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(self.controller.requests), 1)
        self.assertEqual(self.store(run_id).state.controller_generation, 1)

    def test_legacy_inspect_is_byte_for_byte_read_only(self) -> None:
        legacy = self.write_legacy_state(format_version=3)
        before = self.hash_tree(legacy.parent)

        result = self.runtime.inspect(run_id=legacy.parent.name)

        after = self.hash_tree(legacy.parent)
        self.assertEqual(result["status"], "legacy_read_only")
        self.assertEqual(result["format_version"], 3)
        self.assertEqual(after, before)

    def test_initial_session_loss_does_not_trigger_fallback(self) -> None:
        self.controller.outcomes = [
            self.outcome(
                "session_unavailable",
                terminal=None,
                session_id=None,
            ),
        ]

        result = self.run_once()

        self.assertNotEqual(result["status"], "handed_off")
        self.assertEqual(len(self.controller.requests), 1)
        state = self.store(str(result["run_id"])).state
        self.assertEqual(state.controller_generation, 0)
        self.assertFalse(state.fresh_fallback_used)

    def test_blocked_auth_and_quota_do_not_guess_credentials_or_fallback(self) -> None:
        for provider_code in ("auth", "quota"):
            with self.subTest(provider_code=provider_code):
                run_id = self.create_interrupted_run()
                self.controller.outcomes = [
                    self.outcome(provider_code, terminal=None),
                ]

                result = self.runtime.resume(run_id=run_id)

                self.assertEqual(result["status"], "blocked")
                self.assertEqual(len(self.controller.requests), 1)
                self.assertEqual(self.controller.requests[0].mode, "resume")
                state = self.store(run_id).state
                self.assertEqual(state.controller_generation, 0)
                self.assertFalse(state.fresh_fallback_used)

    def test_other_failure_classes_never_trigger_fresh_fallback(self) -> None:
        cases = (
            ("provider_unavailable", "blocked"),
            ("generic_nonzero", "failed"),
            ("invalid_envelope", "interrupted"),
            ("timeout", "interrupted"),
        )
        for process_class, expected_status in cases:
            with self.subTest(process_class=process_class):
                run_id = self.create_interrupted_run()
                self.controller.outcomes = [
                    self.outcome(process_class, terminal=None),
                ]

                result = self.runtime.resume(run_id=run_id)

                self.assertEqual(result["status"], expected_status)
                self.assertEqual(len(self.controller.requests), 1)
                state = self.store(run_id).state
                self.assertEqual(state.controller_generation, 0)
                self.assertFalse(state.fresh_fallback_used)

    def test_transport_failure_requires_an_explicit_resume_for_next_launch(self) -> None:
        run_id = self.create_interrupted_run()
        self.controller.outcomes = [
            self.outcome("transport", terminal=None),
        ]

        first = self.runtime.resume(run_id=run_id)

        self.assertEqual(first["status"], "interrupted")
        self.assertEqual(len(self.controller.requests), 1)
        self.controller.outcomes = [
            self.outcome("completed", terminal=self.completed()),
        ]

        second = self.runtime.resume(run_id=run_id)

        self.assertEqual(second["status"], "handed_off")
        self.assertEqual(len(self.controller.requests), 2)
        self.assertEqual(self.store(run_id).state.controller_generation, 0)

    def test_transport_interruption_preserves_capsule_for_later_fallback(self) -> None:
        note = "PRESERVE-OPAQUE-CAPSULE"
        run_id = self.create_interrupted_run(note)
        self.controller.outcomes = [self.outcome("transport", terminal=None)]

        self.runtime.resume(run_id=run_id)

        self.assertEqual(self.store(run_id).state.resume_capsule["note"], note)
        self.controller.outcomes = [
            self.outcome("session_unavailable", terminal=None),
            self.outcome(
                "completed",
                terminal=self.completed(),
                session_id=NEW_SESSION_ID,
            ),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "handed_off")
        self.assertIn(note, self.controller.requests[-1].prompt)

    def test_fallback_prompt_preserves_contract_and_bounded_recovery_facts(self) -> None:
        note = "OPAQUE-CAPSULE-NOTE"
        run_id = self.create_interrupted_run(note)
        before = self.store(run_id)
        worktree = Path(before.manifest.worktree)
        (worktree / "current-status.tmp").write_text("current\n", encoding="utf-8")
        current_status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            cwd=worktree,
            check=True,
            capture_output=True,
        ).stdout
        current_status_digest = hashlib.sha256(current_status).hexdigest()
        self.assertNotEqual(current_status_digest, before.state.status_digest)
        self.controller.outcomes = [
            self.outcome("session_unavailable", terminal=None),
            self.outcome(
                "completed",
                terminal=self.completed(),
                session_id=NEW_SESSION_ID,
            ),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "handed_off")
        fallback = self.controller.requests[1]
        self.assertEqual(fallback.mode, "fallback")
        self.assertEqual(fallback.generation, 1)
        self.assertIsNone(fallback.session_id)
        self.assertEqual(fallback.worktree, Path(before.manifest.worktree))
        self.assertEqual(fallback.sandbox, before.manifest.sandbox)
        self.assertEqual(fallback.git_identity, before.manifest.git_identity)
        for record in before.manifest.documents:
            self.assertIn(record.snapshot_path, fallback.prompt)
        for fact in (
            before.manifest.branch,
            before.manifest.worktree,
            before.manifest.base_commit,
            before.state.last_observed_head,
            current_status_digest,
            note,
            '"process_class":"session_unavailable"',
            '"provider_code":"session_unavailable"',
        ):
            self.assertIn(fact, fallback.prompt)
        for forbidden in (
            "completed_task_ids",
            "current_task_id",
            "final_review",
            "verification",
        ):
            self.assertNotIn(forbidden, fallback.prompt)

    def test_healthy_same_session_resume_ignores_capsule(self) -> None:
        note = "DO-NOT-SEND-ON-HEALTHY-RESUME"
        run_id = self.create_interrupted_run(note)
        self.controller.outcomes = [
            self.outcome("completed", terminal=self.completed()),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "handed_off")
        self.assertEqual(self.controller.requests[0].mode, "resume")
        self.assertNotIn(note, self.controller.requests[0].prompt)

    def test_completed_resume_ignores_auxiliary_session_unavailable_code(self) -> None:
        run_id = self.create_interrupted_run()
        self.controller.outcomes = [
            ControllerOutcome(
                SESSION_ID,
                0,
                "completed",
                self.completed(),
                "session_unavailable",
            ),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "handed_off")
        self.assertEqual(len(self.controller.requests), 1)
        state = self.store(run_id).state
        self.assertEqual(state.controller_generation, 0)
        self.assertFalse(state.fresh_fallback_used)

    def test_generation_zero_observation_failure_fails_closed_before_fallback(self) -> None:
        run_id = self.create_interrupted_run()
        original_session = self.store(run_id).state.controller_session_id
        self.controller.outcomes = [
            self.outcome("session_unavailable", terminal=None),
        ]

        with patch(
            "cpe_runtime.runtime.observe_git",
            side_effect=ValueError("observation unavailable"),
        ):
            try:
                result = self.runtime.resume(run_id=run_id)
            except ValueError as exc:
                self.fail(f"observation failure escaped: {exc}")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.controller.requests), 1)
        state = self.store(run_id).state
        self.assertEqual(state.status, "failed")
        self.assertIsNone(state.active_pid)
        self.assertIsNone(state.active_process_group)
        self.assertEqual(state.controller_session_id, original_session)
        self.assertEqual(state.controller_generation, 0)
        self.assertFalse(state.fresh_fallback_used)

    def test_generation_one_observation_failure_fails_closed_while_blocking(self) -> None:
        run_id = self.create_generation_one_interrupted_run()
        generation_one_session = self.store(run_id).state.controller_session_id
        self.controller.outcomes = [
            self.outcome(
                "session_unavailable",
                terminal=None,
                session_id=NEW_SESSION_ID,
            ),
        ]

        with patch(
            "cpe_runtime.runtime.observe_git",
            side_effect=ValueError("observation unavailable"),
        ):
            try:
                result = self.runtime.resume(run_id=run_id)
            except ValueError as exc:
                self.fail(f"observation failure escaped: {exc}")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.controller.requests), 1)
        state = self.store(run_id).state
        self.assertEqual(state.status, "failed")
        self.assertIsNone(state.active_pid)
        self.assertIsNone(state.active_process_group)
        self.assertEqual(state.controller_session_id, generation_one_session)
        self.assertEqual(state.controller_generation, 1)
        self.assertTrue(state.fresh_fallback_used)

    def test_generation_one_session_replaces_generation_zero_after_callback(self) -> None:
        run_id = self.create_interrupted_run()
        self.controller.outcomes = [
            self.outcome("session_unavailable", terminal=None),
            self.outcome(
                "interrupted",
                terminal=self.interrupted(),
                session_id=NEW_SESSION_ID,
            ),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "interrupted")
        self.assertIsNone(self.controller.callback_states[-2].controller_session_id)
        self.assertEqual(
            self.controller.callback_states[-2].controller_generation,
            1,
        )
        self.assertEqual(
            self.controller.callback_states[-1].controller_session_id,
            NEW_SESSION_ID,
        )
        self.assertEqual(
            self.store(run_id).state.controller_session_id,
            NEW_SESSION_ID,
        )

    def test_generation_one_outcome_session_is_not_saved_without_callback(self) -> None:
        run_id = self.create_interrupted_run()
        self.controller.suppress_session_callback = True
        self.controller.outcomes = [
            self.outcome("session_unavailable", terminal=None),
            self.outcome(
                "interrupted",
                terminal=self.interrupted(),
                session_id=NEW_SESSION_ID,
            ),
        ]

        result = self.runtime.resume(run_id=run_id)

        self.assertEqual(result["status"], "interrupted")
        state = self.store(run_id).state
        self.assertEqual(state.controller_generation, 1)
        self.assertIsNone(state.controller_session_id)

    def test_repeated_explicit_resumes_never_create_generation_two(self) -> None:
        run_id = self.create_generation_one_interrupted_run()
        for _attempt in range(2):
            self.controller.outcomes = [
                self.outcome(
                    "session_unavailable",
                    terminal=None,
                    session_id=NEW_SESSION_ID,
                ),
            ]
            result = self.runtime.resume(run_id=run_id)
            self.assertEqual(result["status"], "blocked")

        self.assertEqual(len(self.controller.requests), 2)
        self.assertTrue(
            all(request.generation == 1 for request in self.controller.requests),
        )
        state = self.store(run_id).state
        self.assertEqual(state.controller_generation, 1)
        self.assertTrue(state.fresh_fallback_used)

    def test_v5_inspect_is_strict_read_only_and_does_not_create_a_lock(self) -> None:
        run_id = self.create_interrupted_run()
        store = self.store(run_id)
        store.lock_path.unlink()
        before = (
            store.manifest_path.read_bytes(),
            store.state_path.read_bytes(),
            store.manifest_path.stat().st_mtime_ns,
            store.state_path.stat().st_mtime_ns,
        )

        result = self.runtime.inspect(run_id=run_id)

        after = (
            store.manifest_path.read_bytes(),
            store.state_path.read_bytes(),
            store.manifest_path.stat().st_mtime_ns,
            store.state_path.stat().st_mtime_ns,
        )
        self.assertEqual(result["format_version"], 5)
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(after, before)
        self.assertFalse(store.lock_path.exists())

    def test_legacy_formats_one_through_four_are_read_only(self) -> None:
        for format_version in range(1, 5):
            with self.subTest(format_version=format_version):
                legacy = self.write_legacy_state(format_version=format_version)
                before = self.hash_tree(legacy.parent)

                result = self.runtime.inspect(run_id=legacy.parent.name)

                self.assertEqual(
                    result,
                    {
                        "status": "legacy_read_only",
                        "format_version": format_version,
                        "run_root": str(legacy.parent.resolve()),
                        "recommended_action": (
                            "preserve artifacts; use explicit --adopt-worktree "
                            "for continuation"
                        ),
                    },
                )
                self.assertEqual(self.hash_tree(legacy.parent), before)

    def test_invalid_v5_fails_without_using_a_legacy_run(self) -> None:
        run_id = self.create_interrupted_run()
        store = self.store(run_id)
        legacy = self.write_legacy_state(format_version=3, run_id=run_id)
        before = self.hash_tree(legacy.parent)
        store.state_path.write_text('{"format_version":5}', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "format-5 state"):
            self.runtime.inspect(run_id=run_id)

        self.assertEqual(self.hash_tree(legacy.parent), before)

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
