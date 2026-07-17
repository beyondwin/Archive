#!/usr/bin/env python3
"""Contract evals for the sequential plan runner."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cpe_runtime.launcher import (
    CodexLauncher,
    LaunchResult,
    _drain_registered,
    _terminate_group,
    _UsageFilter,
)
from cpe_runtime.compiler import (
    CompiledIndexService,
    MAX_COMPILER_OUTPUT_BYTES,
    compiler_cache_key,
    default_operator_contract,
    validate_compiled_index,
)
from cpe_runtime.runner import (
    SequentialRunner,
    _ledger_progress,
    _recovery_decision,
    _write_private_json,
)
from cpe_runtime.state import StateStore


class HistoricalEvidenceFixtureTests(unittest.TestCase):
    fixture_root = ROOT / "evals" / "fixtures"
    approved_provenance = {
        "direct_cpe",
        "direct_codex_goal_comparative",
        "non_cpe_comparative",
    }

    def load_fixture(self, name: str) -> dict[str, object]:
        payload = json.loads(
            (self.fixture_root / name).read_text(encoding="utf-8")
        )
        if payload.get("provenance") not in self.approved_provenance:
            raise ValueError("unknown historical evidence provenance")
        return payload

    def test_unknown_provenance_is_rejected(self) -> None:
        payload = {"provenance": "unverified_run"}
        with mock.patch.object(
            Path,
            "read_text",
            return_value=json.dumps(payload),
        ):
            with self.assertRaisesRegex(ValueError, "unknown historical evidence"):
                self.load_fixture("unknown.json")

    def test_comparative_cases_never_count_as_cpe_metrics(self) -> None:
        for name in (
            "readmates-comparative.json",
            "gasstation-comparative.json",
        ):
            with self.subTest(name=name):
                payload = self.load_fixture(name)
                self.assertFalse(payload["count_as_cpe_metrics"])
                self.assertNotEqual(payload["provenance"], "direct_cpe")

    def test_fixtures_are_sanitized_and_content_free(self) -> None:
        forbidden = (
            '"prompt"',
            '"transcript"',
            '"raw_log"',
            '"source_diff"',
            '"token"',
            '"password"',
            "/Users/",
            "/home/",
        )
        for name in (
            "canvas-direct-run-format2.json",
            "readmates-comparative.json",
            "gasstation-comparative.json",
        ):
            with self.subTest(name=name):
                path = self.fixture_root / name
                text = path.read_text(encoding="utf-8")
                payload = self.load_fixture(name)
                self.assertEqual(payload["schema_version"], 1)
                self.assertTrue(payload["sanitized"])
                for marker in forbidden:
                    self.assertNotIn(marker, text)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


class FailingCreateRunner(SequentialRunner):
    def _add_new_worktree(self, store: StateStore) -> None:
        raise subprocess.CalledProcessError(128, ["git", "worktree", "add"])


class SequentialRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_temporary = tempfile.TemporaryDirectory(
            prefix="cpe-sequential-base-"
        )
        cls.fixture_repo = Path(cls.fixture_temporary.name) / "repo"
        cls.fixture_repo.mkdir()
        subprocess.run(["git", "init", "-q", str(cls.fixture_repo)], check=True)
        git(cls.fixture_repo, "config", "user.email", "cpe@example.invalid")
        git(cls.fixture_repo, "config", "user.name", "CPE Eval")
        for index, name in enumerate(("spec-b.md", "spec-a.md"), 1):
            (cls.fixture_repo / name).write_text(
                f"spec {index}\n",
                encoding="utf-8",
            )
        git(cls.fixture_repo, "add", ".")
        git(cls.fixture_repo, "commit", "-q", "-m", "fixture base")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_temporary.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-sequential-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.home.mkdir(mode=0o700)
        shutil.copytree(self.fixture_repo, self.repo)
        self.specs = [self.repo / "spec-b.md", self.repo / "spec-a.md"]
        self.log = self.root / "invocations.jsonl"
        self.fake = self.root / "codex"
        shutil.copyfile(ROOT / "evals" / "fake_codex.py", self.fake)
        self.fake.chmod(0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def plan(self, number: int, scenario: str) -> Path:
        path = self.repo / f"input-plan-{number}.md"
        path.write_text(f"scenario:{scenario}\nplan {number}\n", encoding="utf-8")
        return path

    def runner(
        self,
        *,
        timeout_seconds: float = 5,
        **extra_environment: str,
    ) -> SequentialRunner:
        environment = {
            "PATH": os.environ["PATH"],
            "CODEX_HOME": str(self.home),
            "CPE_FAKE_INVOCATION_LOG": str(self.log),
            **extra_environment,
        }
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(self.fake),
            timeout_seconds=timeout_seconds,
            termination_grace_seconds=0.02,
            environ=environment,
        )
        return SequentialRunner(codex_home=self.home, launcher=launcher)

    def invocations(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def start_run_process(
        self,
        *,
        run_id: str,
        plan: Path,
        extra_environment: dict[str, str],
    ) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONPATH": str(ROOT / "scripts"),
                "CPE_TEST_HOME": str(self.home),
                "CPE_TEST_REPO": str(self.repo),
                "CPE_TEST_PLAN": str(plan),
                "CPE_TEST_RUN_ID": run_id,
                "CPE_TEST_CODEX": str(self.fake),
                "CPE_TEST_SCHEMA": str(
                    ROOT / "templates" / "plan-result-schema.json"
                ),
                "CPE_FAKE_INVOCATION_LOG": str(self.log),
                **extra_environment,
            }
        )
        program = """
import json
import os
from pathlib import Path
from cpe_runtime.launcher import CodexLauncher
from cpe_runtime.runner import SequentialRunner

launcher = CodexLauncher(
    schema_path=Path(os.environ["CPE_TEST_SCHEMA"]),
    codex_bin=os.environ["CPE_TEST_CODEX"],
    timeout_seconds=5,
    termination_grace_seconds=0.02,
    environ=dict(os.environ),
)
runner = SequentialRunner(
    codex_home=Path(os.environ["CPE_TEST_HOME"]),
    launcher=launcher,
)
result = runner.run(
    workspace=Path(os.environ["CPE_TEST_REPO"]),
    specs=[],
    plans=[Path(os.environ["CPE_TEST_PLAN"])],
    run_id=os.environ["CPE_TEST_RUN_ID"],
)
print(json.dumps(result, sort_keys=True), flush=True)
"""
        return subprocess.Popen(
            [sys.executable, "-c", program],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def wait_for_path(self, path: Path, timeout: float = 3) -> None:
        deadline = time.monotonic() + timeout
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(path.exists(), f"timed out waiting for {path}")

    def wait_for_process_exit(self, pid: int, timeout: float = 3) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)
        self.fail(f"process {pid} did not exit")

    def cleanup_fixture_processes(self, pid_path: Path) -> None:
        if not pid_path.exists():
            return
        for line in pid_path.read_text().splitlines():
            try:
                os.kill(int(line), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass

    def start_cli_process(
        self,
        *,
        plan: Path,
        extra_environment: dict[str, str],
    ) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment.update(
            {
                "CODEX_HOME": str(self.home),
                "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
                "CPE_FAKE_INVOCATION_LOG": str(self.log),
                **extra_environment,
            }
        )
        return subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts" / "cpe.py"),
                "run",
                "--plan",
                str(plan),
                "--workspace",
                str(self.repo),
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def assert_state_rejected(self, store: StateStore, message: str) -> None:
        with self.assertRaisesRegex(ValueError, message):
            store.save()

    def create_format_two_store(self, run_id: str) -> StateStore:
        return StateStore.create(
            run_root=self.home / "orchestrator" / run_id,
            run_id=run_id,
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / run_id,
            branch=f"codex/{run_id}",
            specs=[],
            plans=[self.plan(1, "completed")],
        )

    def create_compiler_store(self, run_id: str) -> StateStore:
        plan = self.repo / f"{run_id}.md"
        plan.write_text("Implement the compiler contract.\n", encoding="utf-8")
        return StateStore.create(
            run_root=self.home / "orchestrator" / run_id,
            run_id=run_id,
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / run_id,
            branch=f"codex/{run_id}",
            specs=[],
            plans=[plan],
        )

    def compiler_payload(
        self, store: StateStore, *, unknowns: list[str] | None = None
    ) -> dict[str, object]:
        contract = default_operator_contract(store.state)
        plan = next(item for item in store.state["inputs"] if item["role"] == "plan")
        source = Path(plan["snapshot_path"]).read_bytes()
        return {
            "format_version": 2,
            "cache_key": compiler_cache_key(store.state, contract),
            "plans": [{
                "plan_id": "plan-01",
                "source_sha256": plan["sha256"],
                "byte_length": plan["byte_length"],
                "line_count": 1,
                "tasks": [{
                    "task_id": "task-01", "order": 0,
                    "source_line_start": 1, "source_line_end": 1,
                    "source_text_sha256": hashlib.sha256(source).hexdigest(),
                }],
                "verifications": [], "capabilities": [],
                "coordination_exceptions": [], "execution_advisories": [],
                "unknowns": list(unknowns or []),
            }],
        }

    def fake_compiler_with_unknown(self, unknown: str):
        def compile_once(store, _contract, _repair):
            return self.compiler_payload(store, unknowns=[unknown])
        return compile_once

    def test_compiler_launcher_is_read_only_bounded_and_has_no_git_add_dir(self) -> None:
        launcher = self.runner().launcher
        request = launcher.compiler_request(
            run_root=self.root,
            snapshot_paths=[self.plan(1, "completed")],
            contract_path=self.root / "operator-contract.json",
            result_path=self.root / "compiled-result.json",
            repair=False,
        )
        self.assertIn("read-only", request.command)
        self.assertNotIn("--add-dir", request.command)
        self.assertIn("--ephemeral", request.command)
        self.assertEqual(request.timeout_seconds, 300)
        self.assertIn("Do not modify files", request.prompt)
        self.assertIn("Do not spawn subagents", request.prompt)

    def test_compiler_repair_prompt_names_sealed_output_and_validation_code(self) -> None:
        prompt_log = self.root / "compiler-prompts.jsonl"
        store = self.create_compiler_store("compiler-repair-prompt")
        launcher = self.runner(
            CPE_FAKE_COMPILER_INVALID_FIRST="1",
            CPE_FAKE_COMPILER_PROMPT_LOG=str(prompt_log),
        ).launcher
        path = CompiledIndexService(compile_once=launcher.compile_index).prepare(store)
        self.assertTrue(path.is_file())
        prompts = [json.loads(line) for line in prompt_log.read_text().splitlines()]
        self.assertEqual(len(prompts), 2)
        attempt_one = store.root / "results" / "compiler-attempt-1.json"
        self.assertIn(f"PREVIOUS_OUTPUT_PATH: {attempt_one}", prompts[1])
        self.assertIn(
            "PREVIOUS_ERROR_CODE: compiled_index_format_is_invalid",
            prompts[1],
        )
        self.assertEqual(attempt_one.stat().st_mode & 0o777, 0o400)

    def test_compiler_preserves_and_seals_all_produced_failure_outputs(self) -> None:
        cases = (
            ("malformed", b"{", None, 0, "compiler launch failed"),
            ("non-object", b"[]", None, 0, "compiler launch failed"),
            (
                "oversized",
                b"x" * (MAX_COMPILER_OUTPUT_BYTES + 1),
                None,
                0,
                "compiler output exceeds size limit",
            ),
            ("nonzero", b"{}", {}, 1, "compiler launch failed"),
        )
        for name, content, payload, returncode, message in cases:
            with self.subTest(name=name):
                store = self.create_compiler_store(f"compiler-evidence-{name}")
                launcher = self.runner().launcher
                result_path = store.root / "results" / "compiler-attempt-1.json"

                def fake_launch(request, _lock_fd):
                    request.result_path.write_bytes(content)
                    request.result_path.chmod(0o600)
                    return LaunchResult(
                        payload=payload, returncode=returncode,
                        timed_out=False, forced_cleanup=False,
                        discarded_log_bytes=0,
                        result_path=request.result_path,
                        log_path=request.log_path, duration_ms=1,
                        input_tokens=None, cached_input_tokens=None,
                        output_tokens=None, reasoning_output_tokens=None,
                        launcher_prompt_bytes=len(request.prompt.encode()),
                    )

                with mock.patch.object(
                    launcher, "_launch_structured", side_effect=fake_launch
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        launcher.compile_index(
                            store, default_operator_contract(store.state), False
                        )
                self.assertEqual(result_path.read_bytes(), content)
                self.assertEqual(result_path.stat().st_mode & 0o777, 0o400)

    def test_compiler_never_overwrites_existing_attempt_output(self) -> None:
        store = self.create_compiler_store("compiler-existing-evidence")
        launcher = self.runner().launcher
        result_path = store.root / "results" / "compiler-attempt-1.json"
        result_path.write_bytes(b"existing evidence")
        result_path.chmod(0o600)
        with mock.patch.object(launcher, "_launch_structured") as launch:
            with self.assertRaisesRegex(
                ValueError, "compiler attempt output already exists"
            ):
                launcher.compile_index(
                    store, default_operator_contract(store.state), False
                )
        launch.assert_not_called()
        self.assertEqual(result_path.read_bytes(), b"existing evidence")
        self.assertEqual(result_path.stat().st_mode & 0o777, 0o400)

    def test_compiled_index_requires_exact_plan_source_spans(self) -> None:
        store = self.create_compiler_store("compiler-source")
        contract = default_operator_contract(store.state)
        payload = self.compiler_payload(store)
        payload["plans"][0]["tasks"][0]["source_text_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "source span digest"):
            validate_compiled_index(payload, store.state, contract)

    def test_optional_compiler_ambiguity_is_preserved_as_unknown(self) -> None:
        store = self.create_compiler_store("compiler-unknown")
        service = CompiledIndexService(
            compile_once=self.fake_compiler_with_unknown("capability:browser"),
        )
        path = service.prepare(store)
        index = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(index["plans"][0]["unknowns"], ["capability:browser"])
        self.assertEqual(service.compile_calls, 1)
        self.assertEqual(service.prepare(store), path)
        self.assertEqual(service.compile_calls, 1)

    def test_compiled_index_rejects_invalid_authorization_shapes(self) -> None:
        store = self.create_compiler_store("compiler-shapes")
        contract = default_operator_contract(store.state)
        valid = self.compiler_payload(store)
        cases = []
        task_extra = json.loads(json.dumps(valid))
        task_extra["plans"][0]["tasks"][0]["shell"] = "make test"
        cases.append(task_extra)
        task_missing_id = json.loads(json.dumps(valid))
        del task_missing_id["plans"][0]["tasks"][0]["task_id"]
        cases.append(task_missing_id)
        task = valid["plans"][0]["tasks"][0]
        verification = {
            "command_id": "verify-01", "argv": ["make", "test"],
            "allowed_branch_phases": ["task_green"], "deterministic": True,
            "mutable_input_policy": "forbidden", "required_artifacts": [],
            "source_line_start": task["source_line_start"],
            "source_line_end": task["source_line_end"],
            "source_text_sha256": task["source_text_sha256"],
        }
        for field, invalid in (
            ("argv", "make test"),
            ("allowed_branch_phases", ["deployment"]),
            ("deterministic", 1),
            ("mutable_input_policy", "unrestricted"),
            ("required_artifacts", ["/tmp/result.json"]),
        ):
            invalid_verification = json.loads(json.dumps(valid))
            candidate = dict(verification, **{field: invalid})
            invalid_verification["plans"][0]["verifications"] = [candidate]
            cases.append(invalid_verification)
        verification_extra = json.loads(json.dumps(valid))
        verification_extra["plans"][0]["verifications"] = [
            dict(verification, shell=True)
        ]
        cases.append(verification_extra)
        invalid_capability = json.loads(json.dumps(valid))
        invalid_capability["plans"][0]["capabilities"] = [{
            "capability_id": "browser", "task_ids": ["missing-task"],
        }]
        cases.append(invalid_capability)
        capability_extra = json.loads(json.dumps(valid))
        capability_extra["plans"][0]["capabilities"] = [{
            "capability_id": "browser", "task_ids": ["task-01"], "grant": True,
        }]
        cases.append(capability_extra)
        invalid_exception = json.loads(json.dumps(valid))
        invalid_exception["plans"][0]["coordination_exceptions"] = [{
            "task_id": "missing-task", "role": "implementer", "fork_turns": "all",
            "reason_code": "unbounded-reason",
            "source_line_start": task["source_line_start"],
            "source_line_end": task["source_line_end"],
            "source_text_sha256": task["source_text_sha256"],
        }]
        cases.append(invalid_exception)
        exception_extra = json.loads(json.dumps(valid))
        exception_extra["plans"][0]["coordination_exceptions"] = [{
            "task_id": "task-01", "role": "x" * 65, "fork_turns": "all",
            "reason_code": "source_requires_shared_context", "authority": "extra",
            "source_line_start": task["source_line_start"],
            "source_line_end": task["source_line_end"],
            "source_text_sha256": task["source_text_sha256"],
        }]
        cases.append(exception_extra)
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "compiled index schema"):
                    validate_compiled_index(payload, store.state, contract)

    def test_compiled_index_accepts_source_backed_authorization_shapes(self) -> None:
        store = self.create_compiler_store("compiler-valid-shapes")
        contract = default_operator_contract(store.state)
        payload = self.compiler_payload(store)
        task = payload["plans"][0]["tasks"][0]
        span = {
            "source_line_start": task["source_line_start"],
            "source_line_end": task["source_line_end"],
            "source_text_sha256": task["source_text_sha256"],
        }
        payload["plans"][0]["verifications"] = [{
            "command_id": "verify-01", "argv": ["python3", "-m", "unittest"],
            "allowed_branch_phases": ["task_green"], "deterministic": True,
            "mutable_input_policy": "forbidden",
            "required_artifacts": ["reports/result.json"], **span,
        }]
        payload["plans"][0]["capabilities"] = [{
            "capability_id": "browser", "task_ids": ["task-01"],
        }]
        payload["plans"][0]["coordination_exceptions"] = [{
            "task_id": "task-01", "role": "implementer", "fork_turns": "all",
            "reason_code": "source_requires_shared_context", **span,
        }]
        self.assertIs(validate_compiled_index(payload, store.state, contract), payload)

    def test_compiler_repairs_unhashable_nested_schema_drift_once(self) -> None:
        for name, mutate in (
            ("list", lambda item: item.update(mutable_input_policy=[])),
            ("object", lambda item: item.update(reason_code={})),
        ):
            with self.subTest(name=name):
                store = self.create_compiler_store(f"compiler-repair-{name}")
                valid = self.compiler_payload(store)
                task = valid["plans"][0]["tasks"][0]
                span = {
                    "source_line_start": task["source_line_start"],
                    "source_line_end": task["source_line_end"],
                    "source_text_sha256": task["source_text_sha256"],
                }
                malformed = json.loads(json.dumps(valid))
                if name == "list":
                    item = {
                        "command_id": "verify-01", "argv": ["make", "test"],
                        "allowed_branch_phases": ["task_green"],
                        "deterministic": True, "mutable_input_policy": "forbidden",
                        "required_artifacts": [], **span,
                    }
                    mutate(item)
                    malformed["plans"][0]["verifications"] = [item]
                else:
                    item = {
                        "task_id": "task-01", "role": "implementer",
                        "fork_turns": "all",
                        "reason_code": "source_requires_shared_context", **span,
                    }
                    mutate(item)
                    malformed["plans"][0]["coordination_exceptions"] = [item]
                repairs = []

                def compile_once(_store, _contract, repair):
                    repairs.append(repair)
                    return valid if repair else malformed

                service = CompiledIndexService(compile_once=compile_once)
                self.assertTrue(service.prepare(store).is_file())
                self.assertEqual(service.compile_calls, 2)
                self.assertEqual(repairs, [False, True])

    def test_cached_compiled_index_revalidates_nested_contract(self) -> None:
        store = self.create_compiler_store("compiler-cache-shape")
        payload = self.compiler_payload(store)
        payload["plans"][0]["tasks"][0]["unexpected"] = True
        target = store.root / "compiled-run-index.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        target.chmod(0o600)
        service = CompiledIndexService(compile_once=lambda *_args: payload)
        with self.assertRaisesRegex(ValueError, "compiled index schema"):
            service.prepare(store)
        self.assertEqual(service.compile_calls, 0)

    def test_cached_compiled_index_requires_bounded_private_regular_file(self) -> None:
        stores = {
            name: self.create_compiler_store(f"compiler-cache-{name}")
            for name in ("symlink", "mode", "oversized")
        }
        symlink_target = self.root / "external-index.json"
        symlink_target.write_text("not-json", encoding="utf-8")
        (stores["symlink"].root / "compiled-run-index.json").symlink_to(symlink_target)
        mode_target = stores["mode"].root / "compiled-run-index.json"
        mode_target.write_text(json.dumps(self.compiler_payload(stores["mode"])), encoding="utf-8")
        mode_target.chmod(0o644)
        oversized_target = stores["oversized"].root / "compiled-run-index.json"
        oversized_target.write_bytes(b" " * (MAX_COMPILER_OUTPUT_BYTES + 1))
        oversized_target.chmod(0o600)
        for name, message in (
            ("symlink", "symlink"), ("mode", "private mode"),
            ("oversized", "size limit"),
        ):
            with self.subTest(name=name):
                service = CompiledIndexService(compile_once=lambda *_args: {})
                with self.assertRaisesRegex(ValueError, message):
                    service.prepare(stores[name])
                self.assertEqual(service.compile_calls, 0)

    def test_format_two_state_has_preparation_and_budget_fields(self) -> None:
        source_commit = git(self.repo, "rev-parse", "HEAD")
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "format-two",
            run_id="format-two",
            source_repository=self.repo,
            source_commit=source_commit,
            worktree=self.home / "worktrees" / "format-two",
            branch="codex/format-two",
            specs=[],
            plans=[self.plan(1, "completed")],
        )
        self.assertEqual(store.state["format_version"], 2)
        self.assertEqual(store.state["status"], "preparing")
        self.assertEqual(
            store.state["plans"][0]["budget"],
            {
                "controller_slice_timeout_seconds": 3600,
                "max_progress_checkpoints": 6,
                "plan_wall_budget_seconds": 21600,
                "max_controller_launches": 8,
            },
        )
        self.assertEqual(store.state["plans"][0]["consecutive_no_progress_slices"], 0)
        self.assertEqual(store.state["plans"][0]["progress_checkpoint_count"], 0)
        self.assertIsNone(store.state["plans"][0]["progress_fingerprint"])
        self.assertIsNone(store.state["plans"][0]["environment_fingerprint"])
        self.assertEqual(store.state["plans"][0]["plan_elapsed_seconds"], 0)
        self.assertTrue((store.root / "evidence").is_dir())
        self.assertTrue((store.root / "reports").is_dir())

    def test_checkpointed_result_is_durable_and_resumable(self) -> None:
        runner = self.runner()
        first = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "interrupted")],
            run_id="checkpointed",
        )
        self.assertEqual(first["status"], "checkpointed")
        self.assertEqual(first["plans"][0]["status"], "checkpointed")

        resumed = runner.resume(run_id="checkpointed")

        self.assertIn(resumed["status"], {"checkpointed", "completed"})

    def test_missing_worktree_never_reports_source_commit_as_observed_head(self) -> None:
        runner = self.runner()
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "blocked")],
            run_id="missing-worktree-summary",
        )
        Path(result["worktree"]).rename(self.root / "moved-worktree")

        inspected = runner.inspect(run_id="missing-worktree-summary")

        self.assertIsNone(inspected["observed_head"])
        self.assertEqual(inspected["last_known_head"], result["last_known_head"])

    def test_missing_worktree_reports_active_later_plan_last_known_head(self) -> None:
        runner = self.runner()
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[
                self.plan(1, "completed"),
                self.plan(2, "blocked_after_commit"),
            ],
            run_id="missing-later-worktree-summary",
        )
        store = StateStore.open(
            self.home / "orchestrator" / "missing-later-worktree-summary"
        )
        first_head = store.state["plans"][0]["accepted_commit"]
        second_head = store.state["plans"][1]["last_known_head"]
        self.assertNotEqual(second_head, first_head)
        Path(result["worktree"]).rename(self.root / "moved-later-worktree")

        inspected = runner.inspect(run_id="missing-later-worktree-summary")

        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(inspected["observed_head"])
        self.assertEqual(inspected["last_known_head"], second_head)

    def test_timeout_persists_advanced_head_and_returns_without_relaunch(self) -> None:
        runner = self.runner(timeout_seconds=1.0)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "timeout_after_commit")],
            run_id="timeout-after-commit",
        )
        advanced_head = git(Path(result["worktree"]), "rev-parse", "HEAD")
        self.assertNotEqual(advanced_head, result["source_commit"])
        Path(result["worktree"]).rename(self.root / "moved-timeout-worktree")

        inspected = runner.inspect(run_id="timeout-after-commit")

        self.assertEqual(result["status"], "checkpointed")
        self.assertIsNone(inspected["observed_head"])
        self.assertEqual(inspected["last_known_head"], advanced_head)
        self.assertEqual(len(self.invocations()), 1)

    def test_format_one_state_is_unsupported_without_mutation(self) -> None:
        root = self.home / "orchestrator" / "legacy-format-one"
        root.mkdir(parents=True, mode=0o700)
        state_path = root / "state.json"
        state_path.write_text('{"format_version":1}', encoding="utf-8")
        before = state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "unsupported_legacy_run"):
            StateStore.open(root)
        self.assertEqual(state_path.read_bytes(), before)

    def test_format_two_event_has_bounded_trust_labelled_envelope(self) -> None:
        store = self.create_format_two_store("event-envelope")
        store.append_event(
            "plan.attempt_finished",
            plan_id="plan-01",
            reason_code="child_completed",
            duration_ms=42,
            result="pass",
            evidence_refs=["results/plan-01.json"],
        )
        event = json.loads(store.events_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertRegex(event["event_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(event["source"], "parent_observed")
        self.assertEqual(event["run_id"], "event-envelope")
        self.assertEqual(event["category"], "plan")
        self.assertEqual(event["action"], "plan.attempt_finished")

    def test_format_two_event_rejects_reserved_envelope_collisions(self) -> None:
        store = self.create_format_two_store("event-collision")
        before = store.events_path.read_bytes()
        reserved = {
            "event_id": "forged-event",
            "at": "forged-time",
            "run_id": "forged-run",
            "category": "forged-category",
        }
        for name, value in reserved.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "reserved envelope field"):
                    store.append_event("plan.started", **{name: value})
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_state_rejects_non_integer_budget_values(self) -> None:
        store = self.create_format_two_store("budget-types")
        budget = store.state["plans"][0]["budget"]
        for value in (3600.0, True):
            with self.subTest(value=value):
                budget["controller_slice_timeout_seconds"] = value
                self.assert_state_rejected(store, "plan budget is invalid")
        budget["controller_slice_timeout_seconds"] = 3600

    def test_state_rejects_impossible_plan_and_run_relationships(self) -> None:
        plans = [self.plan(1, "completed"), self.plan(2, "completed")]
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "semantic-state",
            run_id="semantic-state",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "semantic-state",
            branch="codex/semantic-state",
            specs=[],
            plans=plans,
        )
        store.state["current_plan_index"] = 1
        self.assert_state_rejected(store, "completed prefix")

        store.state["current_plan_index"] = 0
        store.state["plans"].append(dict(store.state["plans"][0]))
        self.assert_state_rejected(store, "plan input count")

    def test_state_rejects_incomplete_completed_evidence(self) -> None:
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "completed-evidence",
            run_id="completed-evidence",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "completed-evidence",
            branch="codex/completed-evidence",
            specs=[],
            plans=[self.plan(1, "completed")],
        )
        plan = store.state["plans"][0]
        plan.update(
            status="completed",
            starting_commit="1" * 40,
            accepted_commit="2" * 40,
        )
        store.state["current_plan_index"] = 1
        store.state["status"] = "completed"
        self.assert_state_rejected(store, "completed plan evidence is incomplete")

        result_path = store.root / "results" / "plan-01-attempt-0.json"
        result_path.write_text("{}", encoding="utf-8")
        result_path.chmod(0o600)
        plan["result_path"] = str(result_path.resolve())
        self.assert_state_rejected(store, "completed plan attempt count")

    def test_state_rejects_nonpristine_future_plan(self) -> None:
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "future-plan",
            run_id="future-plan",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "future-plan",
            branch="codex/future-plan",
            specs=[],
            plans=[self.plan(1, "completed"), self.plan(2, "completed")],
        )
        store.state["plans"][1]["attempt_count"] = 1
        self.assert_state_rejected(store, "future plan is not pristine")

    def test_late_interrupt_preserves_durable_terminal_state(self) -> None:
        for terminal in ("completed", "blocked"):
            with self.subTest(terminal=terminal):
                store = StateStore.create(
                    run_root=self.home / "orchestrator" / f"late-{terminal}",
                    run_id=f"late-{terminal}",
                    source_repository=self.repo,
                    source_commit=git(self.repo, "rev-parse", "HEAD"),
                    worktree=self.home / "worktrees" / f"late-{terminal}",
                    branch=f"codex/late-{terminal}",
                    specs=[],
                    plans=[self.plan(1, "completed")],
                )
                result_path = (
                    store.root / "results" / "plan-01-attempt-1.json"
                )
                result_path.write_text("{}", encoding="utf-8")
                result_path.chmod(0o600)
                plan = store.state["plans"][0]
                plan.update(
                    status=terminal,
                    starting_commit=store.state["source_commit"],
                    attempt_count=1,
                    result_path=str(result_path.resolve()),
                )
                if terminal == "completed":
                    plan["accepted_commit"] = store.state["source_commit"]
                    store.state["current_plan_index"] = 1
                store.state["status"] = terminal
                store.save()

                summary = self.runner()._record_interrupted(store)
                self.assertEqual(summary["status"], terminal)
                reopened = StateStore.open(store.root)
                self.assertEqual(reopened.state["status"], terminal)

    def test_worktree_creation_failure_never_leaves_running_state(self) -> None:
        runner = FailingCreateRunner(
            codex_home=self.home,
            launcher=self.runner().launcher,
        )
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="create-failure",
        )
        self.assertEqual(result["status"], "failed")
        state = json.loads(
            (
                self.home
                / "orchestrator"
                / "create-failure"
                / "state.json"
            ).read_text()
        )
        self.assertEqual(state["status"], "failed")
        self.assertFalse((self.home / "worktrees" / "create-failure").exists())

    def test_reconciles_verified_initializing_worktree(self) -> None:
        runner = self.runner()
        store = runner._initialize_run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="reconcile-create",
        )
        runner._add_new_worktree(store)

        runner._create_or_reconcile_worktree(store)

        self.assertEqual(store.state["status"], "running")
        self.assertTrue(Path(store.state["worktree"]).is_dir())
        self.assertEqual(
            git(Path(store.state["worktree"]), "rev-parse", "HEAD"),
            store.state["source_commit"],
        )

    def test_recreates_absent_initializing_worktree(self) -> None:
        runner = self.runner()
        store = runner._initialize_run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="recreate-initializing",
        )

        runner._create_or_reconcile_worktree(store)

        self.assertEqual(store.state["status"], "running")
        self.assertTrue(Path(store.state["worktree"]).is_dir())
        self.assertEqual(
            git(Path(store.state["worktree"]), "rev-parse", "HEAD"),
            store.state["source_commit"],
        )

    def test_initializing_commit_mismatch_fails_closed_without_deletion(self) -> None:
        runner = self.runner()
        store = runner._initialize_run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="mismatched-initializing",
        )
        runner._add_new_worktree(store)
        worktree = Path(store.state["worktree"])
        (worktree / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        git(worktree, "add", "unexpected.txt")
        git(worktree, "commit", "-q", "-m", "unexpected initializing change")
        with self.assertRaisesRegex(ValueError, "source commit"):
            runner.resume(run_id="mismatched-initializing")
        self.assertTrue(worktree.is_dir())

    def test_existing_run_branch_is_rejected_before_state_creation(self) -> None:
        git(self.repo, "branch", "codex/branch-collision")
        with self.assertRaisesRegex(ValueError, "branch already exists"):
            self.runner().run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(1, "completed")],
                run_id="branch-collision",
            )
        self.assertFalse(
            (self.home / "orchestrator" / "branch-collision").exists()
        )

    def test_broken_worktree_symlink_is_rejected_before_state_creation(self) -> None:
        worktrees = self.home / "worktrees"
        worktrees.mkdir(mode=0o700)
        (worktrees / "symlink-worktree").symlink_to(
            self.root / "missing-external-target"
        )
        with self.assertRaisesRegex(ValueError, "worktree already exists"):
            self.runner().run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(1, "completed")],
                run_id="symlink-worktree",
            )
        self.assertFalse(
            (self.home / "orchestrator" / "symlink-worktree").exists()
        )

    def test_concurrent_resume_does_not_launch_a_second_child(self) -> None:
        ready = self.root / "blocking-ready"
        release = self.root / "blocking-release"
        environment = {
            "CPE_FAKE_READY": str(ready),
            "CPE_FAKE_RELEASE": str(release),
        }
        process = self.start_run_process(
            run_id="concurrent-resume",
            plan=self.plan(1, "blocking_completed"),
            extra_environment=environment,
        )
        try:
            self.wait_for_path(ready)
            state = json.loads(
                (
                    self.home
                    / "orchestrator"
                    / "concurrent-resume"
                    / "state.json"
                ).read_text()
            )
            self.assertEqual(state["plans"][0]["attempt_count"], 1)
            result_path = Path(state["plans"][0]["result_path"])
            self.assertTrue(result_path.is_file())

            second = self.runner(**environment).resume(
                run_id="concurrent-resume"
            )
            self.assertEqual(second["status"], "checkpointed")
            self.assertEqual(second["error"], "run_busy")
            self.assertEqual(len(self.invocations()), 1)
            unchanged = json.loads(
                (
                    self.home
                    / "orchestrator"
                    / "concurrent-resume"
                    / "state.json"
                ).read_text()
            )
            self.assertEqual(unchanged["plans"][0]["attempt_count"], 1)
        finally:
            release.touch()
            stdout, stderr = process.communicate(timeout=4)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["status"], "completed")

    def test_coordinator_loss_keeps_the_child_lock(self) -> None:
        ready = self.root / "loss-ready"
        release = self.root / "loss-release"
        environment = {
            "CPE_FAKE_READY": str(ready),
            "CPE_FAKE_RELEASE": str(release),
        }
        process = self.start_run_process(
            run_id="coordinator-loss",
            plan=self.plan(1, "blocking_completed"),
            extra_environment=environment,
        )
        self.wait_for_path(ready)
        child_pid = int(ready.read_text())
        os.kill(process.pid, signal.SIGKILL)
        process.communicate(timeout=2)

        second = self.runner(**environment).resume(run_id="coordinator-loss")
        self.assertEqual(second["status"], "checkpointed")
        self.assertEqual(second["error"], "run_busy")
        self.assertEqual(len(self.invocations()), 1)

        release.touch()
        self.wait_for_process_exit(child_pid)
        recovered = self.runner(**environment).resume(run_id="coordinator-loss")
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(len(self.invocations()), 2)

    def test_attempts_above_ten_use_numeric_prior_log_identity(self) -> None:
        runner = self.runner()
        store = runner._initialize_run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "failed")],
            run_id="numeric-attempts",
        )
        runner._create_or_reconcile_worktree(store)
        worktree = Path(store.state["worktree"])
        head = git(worktree, "rev-parse", "HEAD")
        result_path = store.root / "results" / "plan-01-attempt-10.json"
        result_path.write_text(
            json.dumps(
                {
                    "plan_id": "plan-01",
                    "status": "failed",
                    "head_commit": head,
                    "verification": [],
                    "summary": "prepared attempt ten",
                }
            ),
            encoding="utf-8",
        )
        result_path.chmod(0o600)
        for attempt in (9, 10):
            log_path = store.root / "logs" / f"plan-01-attempt-{attempt}.log"
            log_path.write_text(f"attempt {attempt}\n", encoding="utf-8")
            log_path.chmod(0o600)
        plan = store.state["plans"][0]
        plan.update(
            status="failed",
            starting_commit=head,
            attempt_count=10,
            result_path=str(result_path.resolve()),
        )
        store.state["status"] = "failed"
        store.save()

        persisted = runner._create_recovery_capsule(
            store,
            plan,
            current_head=head,
            prior_result=result_path,
            prior_log=store.root / "logs" / "plan-01-attempt-10.log",
        )
        persisted_identity = persisted.stat().st_ino

        launch_calls: list[dict[str, object]] = []

        def fail_without_a_process(**kwargs: object) -> LaunchResult:
            launch_calls.append(kwargs)
            result_path = Path(kwargs["result_path"])
            log_path = Path(kwargs["log_path"])
            payload = {
                "plan_id": kwargs["plan_id"],
                "status": "failed",
                "head_commit": kwargs["current_commit"],
                "verification": [],
                "summary": "deterministic failed retry",
            }
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            log_path.write_text("deterministic failed retry\n", encoding="utf-8")
            return LaunchResult(
                payload=payload,
                returncode=1,
                timed_out=False,
                forced_cleanup=False,
                discarded_log_bytes=0,
                result_path=result_path,
                log_path=log_path,
                duration_ms=0,
                input_tokens=None,
                cached_input_tokens=None,
                output_tokens=None,
                reasoning_output_tokens=None,
                launcher_prompt_bytes=1,
            )

        runner.launcher.launch = mock.Mock(side_effect=fail_without_a_process)
        resumed = runner.resume(run_id="numeric-attempts", retry_failed=True)

        self.assertEqual(len(launch_calls), 1)
        recovery_path = Path(launch_calls[-1]["recovery_path"])
        capsule = json.loads(recovery_path.read_text())
        self.assertEqual(resumed["status"], "failed")
        self.assertEqual(resumed["plans"][0]["attempt_count"], 11)
        self.assertEqual(recovery_path, persisted)
        self.assertEqual(recovery_path.stat().st_ino, persisted_identity)
        self.assertEqual(recovery_path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(
            str(capsule["prior_log_path"]).endswith(
                "plan-01-attempt-10.log"
            )
        )

    def test_timeout_kills_the_complete_process_group(self) -> None:
        pid_path = self.root / "timeout-grandchildren"
        results = self.root / "timeout-results"
        logs = self.root / "timeout-logs"
        results.mkdir()
        logs.mkdir()
        timeout_child = self.root / "timeout-codex"
        timeout_child.write_text(
            "#!/bin/sh\n"
            "/bin/sleep 60 &\n"
            "child=$!\n"
            "printf '%s\\n%s\\n' \"$$\" \"$child\" > "
            "\"$CPE_FAKE_GRANDCHILD_PID\"\n"
            "wait\n",
            encoding="utf-8",
        )
        timeout_child.chmod(0o700)
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(timeout_child),
            timeout_seconds=2.0,
            termination_grace_seconds=0.02,
            environ={
                "PATH": os.environ["PATH"],
                "CPE_FAKE_GRANDCHILD_PID": str(pid_path),
            },
        )
        result_path, log_path = launcher.attempt_paths(
            results,
            logs,
            "plan-01",
            1,
        )
        head = git(self.repo, "rev-parse", "HEAD")
        lock_fd = os.open(os.devnull, os.O_RDONLY)
        real_monotonic = time.monotonic

        def readiness_clock() -> float:
            return real_monotonic() + (2.0 if pid_path.exists() else 0.0)

        try:
            with mock.patch(
                "cpe_runtime.launcher.time.monotonic",
                side_effect=readiness_clock,
            ):
                outcome = launcher.launch(
                    worktree=self.repo,
                    plan_id="plan-01",
                    plan_path=self.plan(1, "timeout_grandchild"),
                    spec_paths=[],
                    starting_commit=head,
                    current_commit=head,
                    result_path=result_path,
                    log_path=log_path,
                    lock_fd=lock_fd,
                )
            self.assertTrue(outcome.timed_out)
            self.assertIsNone(outcome.payload)
            self.assertEqual(
                _recovery_decision(
                    payload=None,
                    timed_out=True,
                    previous_signature=None,
                    automatic_available=True,
                ),
                (
                    True,
                    "eligible",
                    "timeout",
                    "resume the first incomplete task from durable evidence after process timeout",
                ),
            )
            pids = [int(line) for line in pid_path.read_text().splitlines()]
            self.assertGreaterEqual(len(pids), 1)
            for pid in pids:
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
        finally:
            os.close(lock_fd)
            self.cleanup_fixture_processes(pid_path)

    def assert_signal_kills_complete_process_group(self, signum: int) -> None:
        pid_path = self.root / f"signal-grandchild-{signum}"
        process = self.start_cli_process(
            plan=self.plan(1, "timeout_grandchild"),
            extra_environment={"CPE_FAKE_GRANDCHILD_PID": str(pid_path)},
        )
        try:
            self.wait_for_path(pid_path)
            process.send_signal(signum)
            stdout, stderr = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 3, stderr)
            self.assertEqual(json.loads(stdout)["status"], "checkpointed")
            for line in pid_path.read_text().splitlines():
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(line), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)
            self.cleanup_fixture_processes(pid_path)

    def test_keyboard_interrupt_kills_the_complete_process_group(self) -> None:
        self.assert_signal_kills_complete_process_group(signal.SIGINT)

    def test_sigterm_kills_the_complete_process_group(self) -> None:
        self.assert_signal_kills_complete_process_group(signal.SIGTERM)

    def test_completed_child_with_live_descendant_is_rejected_and_cleaned(self) -> None:
        pid_path = self.root / "completed-grandchild"
        try:
            result = self.runner(
                CPE_FAKE_GRANDCHILD_PID=str(pid_path)
            ).run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(1, "completed_with_grandchild")],
                run_id="completed-descendant",
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"], "forced_cleanup")
            pid = int(pid_path.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            self.cleanup_fixture_processes(pid_path)

    def test_large_log_retains_only_a_bounded_tail(self) -> None:
        result = self.runner().run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "large_log")],
            run_id="large-log",
        )
        self.assertEqual(result["status"], "completed")
        log_path = (
            self.home
            / "orchestrator"
            / "large-log"
            / "logs"
            / "plan-01-attempt-1.log"
        )
        payload = log_path.read_bytes()
        self.assertLessEqual(len(payload), 1_048_576)
        self.assertIn(b"CPE_FINAL_LOG_MARKER", payload)
        self.assertIn(b"[cpe log truncated; discarded_bytes=", payload)

    def test_spawn_failure_is_recorded_as_a_durable_failed_attempt(self) -> None:
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(self.root / "missing-codex"),
            timeout_seconds=1,
            environ={"PATH": os.environ["PATH"]},
        )
        runner = SequentialRunner(codex_home=self.home, launcher=launcher)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="spawn-failure",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "invalid_result")
        self.assertEqual(result["plans"][0]["attempt_count"], 1)
        state = json.loads(
            (self.home / "orchestrator" / "spawn-failure" / "state.json").read_text()
        )
        self.assertEqual(state["status"], "failed")
        log_path = (
            self.home
            / "orchestrator"
            / "spawn-failure"
            / "logs"
            / "plan-01-attempt-1.log"
        )
        self.assertIn("[cpe spawn failed:", log_path.read_text())

    def test_launcher_command_and_prompt_are_minimal_and_ephemeral(self) -> None:
        launcher = self.runner().launcher
        result_path = self.root / "result.json"
        command = launcher._command(self.repo, result_path)
        prompt = launcher._prompt(
            worktree=self.repo,
            plan_id="plan-01",
            plan_path=self.plan(1, "completed"),
            spec_paths=[],
            starting_commit=git(self.repo, "rev-parse", "HEAD"),
            current_commit=git(self.repo, "rev-parse", "HEAD"),
            recovery_path=None,
        )
        self.assertIn("--ephemeral", command)
        self.assertIn("--json", command)
        self.assertIn("--add-dir", command)
        common = Path(git(self.repo, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = self.repo / common
        self.assertEqual(
            command[command.index("--add-dir") + 1],
            str(common.resolve()),
        )
        self.assertEqual(command.count("--output-last-message"), 1)
        self.assertNotIn("REPOSITORY:", prompt)
        self.assertIn("WORKTREE:", prompt)
        self.assertNotIn(
            "Write only the fixed schema result to RESULT_PATH",
            prompt,
        )
        self.assertIn("SPECIFICATIONS_REFERENCE_ONLY_IN_ORDER:", prompt)
        self.assertIn("Do not preload specification snapshots", prompt)
        self.assertIn("focused RED/GREEN", prompt)
        self.assertIn("no automatic full-suite run per task", prompt)
        self.assertIn("review-package", prompt)
        self.assertIn("one consolidated fix subagent", prompt)
        self.assertIn("cross-task final review", prompt)
        self.assertIn("same normalized verification command", prompt)
        self.assertIn("workflow_receipt", prompt)
        self.assertLess(len(prompt.encode("utf-8")), 2_400)

    def test_usage_filter_keeps_only_bounded_final_totals(self) -> None:
        capture = _UsageFilter()
        capture.feed(
            b'{"type":"item.completed","item":{"text":"RAW_EVENT_SENTINEL"}}\n'
            b'{"type":"turn.completed","usage":{"input_tokens":41,'
        )
        capture.feed(
            b'"cached_input_tokens":31,"output_tokens":7,'
            b'"reasoning_output_tokens":5}}\n'
        )
        capture.finish()
        self.assertEqual(
            capture.usage,
            {
                "input_tokens": 41,
                "cached_input_tokens": 31,
                "output_tokens": 7,
                "reasoning_output_tokens": 5,
            },
        )
        self.assertFalse(hasattr(capture, "events"))

        missing = _UsageFilter()
        missing.feed(b'{"type":"turn.started"}\nnot-json\n')
        missing.finish()
        self.assertEqual(
            missing.usage,
            {
                "input_tokens": None,
                "cached_input_tokens": None,
                "output_tokens": None,
                "reasoning_output_tokens": None,
            },
        )

        oversized = _UsageFilter()
        oversized.feed(b"x" * 70_000 + b"\n")
        oversized.feed(
            b'{"type":"turn.completed","usage":{"input_tokens":3}}\n'
        )
        oversized.finish()
        self.assertEqual(oversized.usage["input_tokens"], 3)

    def test_usage_filter_rejects_unreasonable_integer_totals(self) -> None:
        capture = _UsageFilter()
        capture.feed(
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 10**1_000,
                        "cached_input_tokens": True,
                        "output_tokens": -1,
                        "reasoning_output_tokens": 1.5,
                    },
                }
            ).encode("utf-8")
            + b"\n"
        )
        capture.finish()

        self.assertEqual(
            capture.usage,
            {
                "input_tokens": None,
                "cached_input_tokens": None,
                "output_tokens": None,
                "reasoning_output_tokens": None,
            },
        )

    def test_terminate_group_tolerates_transient_permission_errors(self) -> None:
        process = mock.Mock(pid=1234)
        with mock.patch(
            "cpe_runtime.launcher._group_exists",
            side_effect=[True, False, True, False, False],
        ), mock.patch(
            "cpe_runtime.launcher.os.killpg",
            side_effect=PermissionError(1, "Operation not permitted"),
        ) as killpg:
            forced = _terminate_group(process, 0)

        self.assertTrue(forced)
        self.assertEqual(killpg.call_count, 2)
        process.wait.assert_called_once_with(timeout=1.0)

    def test_terminate_group_fails_closed_on_persistent_permission_error(self) -> None:
        process = mock.Mock(pid=1234)
        process.wait.side_effect = subprocess.TimeoutExpired("codex", 1.0)
        with mock.patch(
            "cpe_runtime.launcher._group_exists",
            return_value=True,
        ), mock.patch(
            "cpe_runtime.launcher.os.killpg",
            side_effect=PermissionError(1, "Operation not permitted"),
        ) as killpg, mock.patch(
            "cpe_runtime.launcher.time.monotonic",
            side_effect=[0.0, 0.0, 0.0, 1.0],
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "child process group did not terminate",
            ):
                _terminate_group(process, 0)

        self.assertEqual(killpg.call_count, 2)
        process.wait.assert_called_once_with(timeout=1.0)

    def test_timeout_and_exception_paths_drain_both_pipes(self) -> None:
        original_drain = _drain_registered

        class FakeProcess:
            pid = 4242

            def __init__(self, stdout: object, stderr: object) -> None:
                self.stdin = mock.Mock()
                self.stdout = stdout
                self.stderr = stderr
                self.returncode: int | None = None

            def poll(self) -> int | None:
                return self.returncode

        class RaisingSelector:
            def __init__(self) -> None:
                self.inner = selectors.DefaultSelector()
                self.closed = False

            def register(self, *args: object, **kwargs: object) -> object:
                return self.inner.register(*args, **kwargs)

            def unregister(self, fileobj: object) -> object:
                return self.inner.unregister(fileobj)

            def modify(self, *args: object, **kwargs: object) -> object:
                return self.inner.modify(*args, **kwargs)

            def get_map(self) -> object:
                return self.inner.get_map()

            def select(self, _timeout: float | None = None) -> object:
                raise RuntimeError("injected selector failure")

            def close(self) -> None:
                self.closed = True
                self.inner.close()

        def pipe_with(payload: bytes) -> object:
            read_descriptor, write_descriptor = os.pipe()
            os.write(write_descriptor, payload)
            os.close(write_descriptor)
            return os.fdopen(read_descriptor, "rb", buffering=0)

        def terminate(process: FakeProcess, _grace: float) -> bool:
            process.returncode = -signal.SIGKILL
            return True

        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            timeout_seconds=1e-9,
        )
        drain_sizes: list[int] = []
        drain_remaining: list[int] = []
        drained_chunks: dict[int, bytearray] = {}

        def observed_drain(selector: selectors.BaseSelector) -> None:
            keys = list(selector.get_map().values())
            drain_sizes.append(len(keys))
            for key in keys:
                original_sink = key.data
                identity = id(key.fileobj)
                drained_chunks.setdefault(identity, bytearray())

                def record(
                    chunk: bytes,
                    *,
                    sink: object = original_sink,
                    stream_identity: int = identity,
                ) -> None:
                    drained_chunks[stream_identity].extend(chunk)
                    sink(chunk)

                selector.modify(
                    key.fileobj,
                    selectors.EVENT_READ,
                    record,
                )
            original_drain(selector)
            drain_remaining.append(len(selector.get_map()))

        timeout_process = FakeProcess(
            pipe_with(
                b'{"type":"turn.completed","usage":{"input_tokens":3,'
                b'"cached_input_tokens":2,"output_tokens":1,'
                b'"reasoning_output_tokens":1}}\n'
            ),
            pipe_with(b"timeout stderr tail\n"),
        )
        timeout_log = self.root / "timeout-drain.log"
        with (
            mock.patch(
                "cpe_runtime.launcher.subprocess.Popen",
                return_value=timeout_process,
            ),
            mock.patch(
                "cpe_runtime.launcher._terminate_group",
                side_effect=terminate,
            ),
            mock.patch(
                "cpe_runtime.launcher._drain_registered",
                side_effect=observed_drain,
            ),
        ):
            outcome = launcher.launch(
                worktree=self.repo,
                plan_id="plan-01",
                plan_path=self.plan(1, "completed"),
                spec_paths=[],
                starting_commit="0" * 40,
                current_commit="0" * 40,
                result_path=self.root / "timeout-drain-result.json",
                log_path=timeout_log,
                lock_fd=0,
            )

        self.assertTrue(outcome.timed_out)
        self.assertEqual(drain_sizes, [2])
        self.assertEqual(drain_remaining, [0])
        self.assertEqual(outcome.input_tokens, 3)
        self.assertIn("timeout stderr tail", timeout_log.read_text())
        self.assertTrue(timeout_process.stdout.closed)
        self.assertTrue(timeout_process.stderr.closed)

        drain_sizes.clear()
        drain_remaining.clear()
        drained_chunks.clear()
        launcher.timeout_seconds = 5.0
        exception_process = FakeProcess(
            pipe_with(b'{"type":"turn.completed","usage":{}}\n'),
            pipe_with(b"exception stderr tail\n"),
        )
        exception_selector = RaisingSelector()
        exception_log = self.root / "exception-drain.log"
        with (
            mock.patch(
                "cpe_runtime.launcher.selectors.DefaultSelector",
                return_value=exception_selector,
            ),
            mock.patch(
                "cpe_runtime.launcher.subprocess.Popen",
                return_value=exception_process,
            ),
            mock.patch(
                "cpe_runtime.launcher._terminate_group",
                side_effect=terminate,
            ),
            mock.patch(
                "cpe_runtime.launcher._drain_registered",
                side_effect=observed_drain,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "injected selector failure",
            ):
                launcher.launch(
                    worktree=self.repo,
                    plan_id="plan-01",
                    plan_path=self.plan(1, "completed"),
                    spec_paths=[],
                    starting_commit="0" * 40,
                    current_commit="0" * 40,
                    result_path=self.root / "exception-drain-result.json",
                    log_path=exception_log,
                    lock_fd=0,
                )

        self.assertEqual(drain_sizes, [2])
        self.assertEqual(drain_remaining, [0])
        self.assertIn(
            b"turn.completed",
            drained_chunks[id(exception_process.stdout)],
        )
        self.assertIn("exception stderr tail", exception_log.read_text())
        self.assertTrue(exception_selector.closed)
        self.assertTrue(exception_process.stdout.closed)
        self.assertTrue(exception_process.stderr.closed)

    def test_legacy_recovery_fields_are_rejected_without_plan_advancement(self) -> None:
        runner = self.runner()
        legacy = {
            "retryable": True,
            "failure_signature": "verification:test_failed",
            "next_strategy": "inspect the focused failing boundary",
        }

        cases = [(field, {field: value}) for field, value in legacy.items()]
        cases.append(("legacy_triple", legacy))

        def launch_with(injected: dict[str, object]):
            def launch(**kwargs: object) -> LaunchResult:
                result_path = Path(kwargs["result_path"])
                log_path = Path(kwargs["log_path"])
                payload: dict[str, object] = {
                    "plan_id": kwargs["plan_id"],
                    "status": "failed",
                    "head_commit": kwargs["current_commit"],
                    "verification": [],
                    "summary": "result with undeclared legacy field",
                    "checkpoint": None,
                    "blocker": None,
                    "workflow_receipt": None,
                    **injected,
                }
                result_path.write_text(json.dumps(payload), encoding="utf-8")
                log_path.write_text("legacy field fixture\n", encoding="utf-8")
                return LaunchResult(
                    payload=payload,
                    returncode=1,
                    timed_out=False,
                    forced_cleanup=False,
                    discarded_log_bytes=0,
                    result_path=result_path,
                    log_path=log_path,
                    duration_ms=0,
                    input_tokens=None,
                    cached_input_tokens=None,
                    output_tokens=None,
                    reasoning_output_tokens=None,
                    launcher_prompt_bytes=0,
                )
            return launch

        for index, (label, injected) in enumerate(cases, 1):
            runner.launcher.launch = mock.Mock(
                side_effect=launch_with(injected)
            )
            result = runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(index, "failed")],
                run_id=f"legacy-result-field-{index}",
            )
            with self.subTest(field=label):
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"], "invalid_result")
                self.assertEqual(result["current_plan_index"], 0)
                self.assertEqual(result["plans"][0]["status"], "failed")
                self.assertIsNone(result["plans"][0]["accepted_commit"])

    def test_undeclared_result_field_is_rejected_at_handoff(self) -> None:
        runner = self.runner()
        store = mock.Mock(state={"worktree": str(self.repo)})
        head = git(self.repo, "rev-parse", "HEAD")
        plan = {"plan_id": "plan-01", "starting_commit": head}
        payload = {
            "plan_id": "plan-01",
            "status": "failed",
            "head_commit": head,
            "verification": [],
            "summary": "focused strict-envelope contract",
            "unexpected": "field",
        }

        def outcome() -> LaunchResult:
            return LaunchResult(
                payload=payload,
                returncode=1,
                timed_out=False,
                forced_cleanup=False,
                discarded_log_bytes=0,
                result_path=self.root / "unused-result.json",
                log_path=self.root / "unused.log",
                duration_ms=0,
                input_tokens=None,
                cached_input_tokens=None,
                output_tokens=None,
                reasoning_output_tokens=None,
                launcher_prompt_bytes=0,
            )

        self.assertEqual(
            runner._handoff_error(store, plan, outcome()),
            "invalid_result",
        )

    def assert_handoff_contract(
        self,
        *,
        runner: SequentialRunner,
        store: StateStore,
        plan: dict[str, object],
    ) -> None:
        result_path = Path(plan["result_path"])
        payload = json.loads(result_path.read_text())
        log_path = (
            store.root
            / "logs"
            / f"{plan['plan_id']}-attempt-{plan['attempt_count']}.log"
        )

        def outcome(
            candidate: dict[str, object],
            *,
            returncode: int = 0,
        ) -> LaunchResult:
            return LaunchResult(
                payload=candidate,
                returncode=returncode,
                timed_out=False,
                forced_cleanup=False,
                discarded_log_bytes=0,
                result_path=result_path,
                log_path=log_path,
                duration_ms=0,
                input_tokens=None,
                cached_input_tokens=None,
                output_tokens=None,
                reasoning_output_tokens=None,
                launcher_prompt_bytes=0,
            )

        self.assertIsNone(runner._handoff_error(store, plan, outcome(payload)))

        nullable_wire_payload = dict(payload)
        self.assertIsNone(
            runner._handoff_error(
                store,
                plan,
                outcome(nullable_wire_payload),
            )
        )
        nullable_failed_wire_payload = dict(
            payload,
            status="failed",
            workflow_receipt=None,
        )
        self.assertIsNone(
            runner._handoff_error(
                store,
                plan,
                outcome(nullable_failed_wire_payload),
            )
        )
        self.assertNotIn("workflow_receipt", nullable_failed_wire_payload)

        missing_receipt = dict(payload)
        missing_receipt.pop("workflow_receipt")
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(missing_receipt)),
            "invalid_workflow_receipt",
        )

        receipt = dict(payload["workflow_receipt"])
        duplicate_verification = dict(
            payload,
            workflow_receipt=dict(receipt, duplicate_verification="repeated"),
        )
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(duplicate_verification)),
            "invalid_workflow_receipt",
        )

        failed_final_review = dict(
            payload,
            workflow_receipt=dict(receipt, open_finding_ids=["F-1"]),
        )
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(failed_final_review)),
            "invalid_workflow_receipt",
        )

        outside_artifact = dict(
            payload,
            workflow_receipt=dict(
                receipt,
                final_review_path="../outside-review.md",
            ),
        )
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(outside_artifact)),
            "unsafe_workflow_artifact",
        )

        worktree = Path(store.state["worktree"])
        symlink = worktree / ".superpowers" / "sdd" / "review-link.md"
        symlink.symlink_to(worktree / ".superpowers" / "sdd" / "final-review.md")
        symlink_artifact = dict(
            payload,
            workflow_receipt=dict(
                receipt,
                final_review_path=".superpowers/sdd/review-link.md",
            ),
        )
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(symlink_artifact)),
            "unsafe_workflow_artifact",
        )
        symlink.unlink()

        wrong_head = dict(payload, head_commit="0" * 40)
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(wrong_head)),
            "wrong_head",
        )
        wrong_incomplete = dict(
            wrong_head,
            status="checkpointed",
            verification=[],
            checkpoint={
                "reason": "coordinator_interrupt",
                "progress_fingerprint": "0" * 64,
                "completed_task_ids": [],
                "current_task_id": None,
            },
            workflow_receipt=None,
        )
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(wrong_incomplete)),
            "wrong_head",
        )

        failed_verification = dict(
            payload,
            verification=[
                {
                    "command_id": "fake-final",
                    "argv_digest": "f" * 64,
                    "phase": "branch_final",
                    "evidence_key": "0" * 64,
                    "exit_code": 1,
                    "receipt_path": None,
                }
            ],
        )
        self.assertEqual(
            runner._handoff_error(
                store,
                plan,
                outcome(failed_verification),
            ),
            "verification_failed",
        )
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(payload, returncode=1)),
            "nonzero_exit",
        )

        worktree = Path(store.state["worktree"])
        dirty = worktree / "untracked-handoff.txt"
        dirty.write_text("dirty\n", encoding="utf-8")
        self.assertEqual(
            runner._handoff_error(store, plan, outcome(payload)),
            "dirty_handoff",
        )
        dirty.unlink()

        git(worktree, "checkout", "-q", "--orphan", "handoff-unrelated")
        git(worktree, "rm", "-q", "-rf", ".")
        unrelated = worktree / "unrelated.txt"
        unrelated.write_text("unrelated\n", encoding="utf-8")
        git(worktree, "add", "unrelated.txt")
        git(worktree, "commit", "-q", "-m", "unrelated handoff")
        unrelated_payload = dict(payload, head_commit=git(worktree, "rev-parse", "HEAD"))
        self.assertEqual(
            runner._handoff_error(
                store,
                plan,
                outcome(unrelated_payload),
            ),
            "broken_ancestry",
        )

    def test_snapshots_preserve_spec_and_plan_order(self) -> None:
        plans = [self.plan(2, "completed"), self.plan(1, "completed")]
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "snapshot-order",
            run_id="snapshot-order",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "snapshot-order",
            branch="codex/snapshot-order",
            specs=self.specs,
            plans=plans,
        )
        inputs = store.state["inputs"]
        self.assertEqual([item["source_path"] for item in inputs], [str(path.resolve()) for path in self.specs + plans])
        self.assertEqual([item["document_id"] for item in inputs], ["spec-01", "spec-02", "plan-01", "plan-02"])
        self.assertEqual([Path(item["snapshot_path"]).read_text() for item in inputs], [path.read_text() for path in self.specs + plans])
        inputs[2]["document_id"] = "../plan-01"
        store.state["plans"][0]["plan_id"] = "../plan-01"
        with self.assertRaisesRegex(ValueError, "input identity"):
            store.save()

    def test_two_plans_execute_sequentially_in_one_worktree(self) -> None:
        runner = self.runner()
        result = runner.run(
            workspace=self.repo,
            specs=self.specs,
            plans=[
                self.plan(1, "oversized_usage"),
                self.plan(2, "mutate_prior_nonzero_completed"),
            ],
            run_id="two-plans",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "nonzero_exit")
        self.assertEqual(
            [plan["attempt_count"] for plan in result["plans"]],
            [1, 1],
        )
        calls = self.invocations()
        self.assertEqual(
            [call["plan_id"] for call in calls],
            ["plan-01", "plan-02"],
        )
        self.assertEqual(len({call["worktree"] for call in calls}), 1)
        self.assertTrue((Path(calls[0]["worktree"]) / "plan-1.txt").is_file())
        self.assertTrue((Path(calls[0]["worktree"]) / "plan-2.txt").is_file())
        events_path = (
            self.home / "orchestrator" / "two-plans" / "events.jsonl"
        )
        events = [
            json.loads(line) for line in events_path.read_text().splitlines()
        ]
        finished = [
            event
            for event in events
            if event["action"] == "plan.attempt_finished"
        ]
        self.assertEqual(len(finished), 2)
        for event in finished:
            self.assertGreaterEqual(event["duration_ms"], 0)
            self.assertGreater(event["launcher_prompt_bytes"], 0)
        oversized = finished[0]
        for field in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ):
            self.assertIsNone(oversized[field])
        finished_lines = [
            line
            for line in events_path.read_text().splitlines()
            if json.loads(line)["action"] == "plan.attempt_finished"
        ]
        self.assertLessEqual(len(finished_lines[0]), 16_383)
        for event in finished[1:]:
            self.assertEqual(event["input_tokens"], 41)
            self.assertEqual(event["cached_input_tokens"], 31)
            self.assertEqual(event["output_tokens"], 7)
            self.assertEqual(event["reasoning_output_tokens"], 5)
        self.assertNotIn("RAW_EVENT_SENTINEL", events_path.read_text())
        for call in calls:
            log = (
                self.home
                / "orchestrator"
                / "two-plans"
                / "logs"
                / f"{call['plan_id']}-attempt-{call['number']}.log"
            )
            self.assertNotIn("RAW_EVENT_SENTINEL", log.read_text())

        first_result = Path(result["plans"][0]["result_path"])
        first_payload = json.loads(first_result.read_text())
        self.assertEqual(first_payload["plan_id"], "plan-01")
        self.assertEqual(first_result.stat().st_mode & 0o777, 0o400)
        store = StateStore.open(self.home / "orchestrator" / "two-plans")
        self.assert_handoff_contract(
            runner=runner,
            store=store,
            plan=store.state["plans"][1],
        )

    def test_resume_skips_completed_plan_and_continues_current_git_state(self) -> None:
        runner = self.runner()
        real_launch = runner.launcher.launch
        launch_plan_ids: list[str] = []

        def complete_first_plan_without_a_process(
            **kwargs: object,
        ) -> LaunchResult:
            plan_id = str(kwargs["plan_id"])
            launch_plan_ids.append(plan_id)
            if plan_id != "plan-01":
                return real_launch(**kwargs)
            worktree = Path(kwargs["worktree"])
            evidence = worktree / ".superpowers" / "sdd"
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
            (evidence / "progress.md").write_text(
                "Task 1: complete\n",
                encoding="utf-8",
            )
            (evidence / "final-review.md").write_text(
                "Verdict: approved\nFindings: none\n",
                encoding="utf-8",
            )
            result_path = Path(kwargs["result_path"])
            log_path = Path(kwargs["log_path"])
            payload = {
                "plan_id": plan_id,
                "status": "completed",
                "head_commit": kwargs["current_commit"],
                "verification": [
                    {
                        "command_id": "focused-deterministic-verify",
                        "argv_digest": "a" * 64,
                        "phase": "branch_final",
                        "evidence_key": "b" * 64,
                        "exit_code": 0,
                        "receipt_path": None,
                    }
                ],
                "summary": "deterministic first-plan completion",
                "workflow_receipt": {
                    "ledger_path": ".superpowers/sdd/progress.md",
                    "final_review_path": ".superpowers/sdd/final-review.md",
                    "final_review_head": kwargs["current_commit"],
                    "open_finding_ids": [],
                    "open_obligation_ids": [],
                },
            }
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            log_path.write_text(
                "deterministic first-plan completion\n",
                encoding="utf-8",
            )
            return LaunchResult(
                payload=payload,
                returncode=0,
                timed_out=False,
                forced_cleanup=False,
                discarded_log_bytes=0,
                result_path=result_path,
                log_path=log_path,
                duration_ms=0,
                input_tokens=None,
                cached_input_tokens=None,
                output_tokens=None,
                reasoning_output_tokens=None,
                launcher_prompt_bytes=1,
            )

        runner.launcher.launch = mock.Mock(
            side_effect=complete_first_plan_without_a_process
        )
        first = runner.run(workspace=self.repo, specs=[], plans=[self.plan(1, "completed"), self.plan(2, "resume_completed")], run_id="resume")
        self.assertEqual(first["status"], "blocked")
        prior_head = first["observed_head"]
        self.assertEqual(launch_plan_ids, ["plan-01", "plan-02"])
        self.assertEqual(len(self.invocations()), 1)
        resumed = runner.resume(run_id="resume")
        self.assertEqual(resumed["status"], "completed")
        self.assertNotEqual(resumed["observed_head"], prior_head)
        self.assertEqual(
            launch_plan_ids,
            ["plan-01", "plan-02", "plan-02"],
        )
        self.assertEqual(
            [call["plan_id"] for call in self.invocations()],
            ["plan-02", "plan-02"],
        )

    def test_failed_result_stops_without_automatic_recovery(self) -> None:
        self.assertEqual(
            _recovery_decision(
                payload={"status": "interrupted"},
                timed_out=False,
                previous_signature=None,
                automatic_available=True,
            ),
            (
                True,
                "eligible",
                "status:interrupted",
                "resume the first incomplete task from durable evidence after child interruption",
            ),
        )
        runner = self.runner()
        launch_calls: list[dict[str, object]] = []
        attempts: dict[str, int] = {}

        def recovery_without_a_process(**kwargs: object) -> LaunchResult:
            launch_calls.append(kwargs)
            plan_id = str(kwargs["plan_id"])
            attempts[plan_id] = attempts.get(plan_id, 0) + 1
            worktree = Path(kwargs["worktree"])
            evidence = worktree / ".superpowers" / "sdd"
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
            (evidence / "progress.md").write_text(
                "Task 1: complete (commit 1111111)\n"
                "Task 2: complete (commit 2222222)\n",
                encoding="utf-8",
            )
            (evidence / "final-review.md").write_text(
                "Verdict: approved\nFindings: none\n",
                encoding="utf-8",
            )
            result_path = Path(kwargs["result_path"])
            log_path = Path(kwargs["log_path"])
            timed_out = plan_id == "plan-02"
            if timed_out:
                payload = None
                returncode = -signal.SIGKILL
                log_path.write_text("deterministic timeout\n", encoding="utf-8")
            elif attempts[plan_id] == 1:
                payload = {
                    "plan_id": plan_id,
                    "status": "failed",
                    "head_commit": kwargs["current_commit"],
                    "verification": [],
                    "summary": "deterministic failed result",
                }
                returncode = 1
                result_path.write_text(json.dumps(payload), encoding="utf-8")
                log_path.write_text(
                    "deterministic failed result\n",
                    encoding="utf-8",
                )
            else:
                payload = {
                    "plan_id": plan_id,
                    "status": "completed",
                    "head_commit": kwargs["current_commit"],
                    "verification": [
                        {
                            "command_id": "focused-deterministic-verify",
                            "argv_digest": "f" * 64,
                            "phase": "branch_final",
                            "evidence_key": "0" * 64,
                            "exit_code": 0,
                            "receipt_path": None,
                        }
                    ],
                    "summary": "deterministic recovery completed",
                    "workflow_receipt": {
                        "ledger_path": ".superpowers/sdd/progress.md",
                        "final_review_path": ".superpowers/sdd/final-review.md",
                        "final_review_head": kwargs["current_commit"],
                        "open_finding_ids": [],
                        "open_obligation_ids": [],
                    },
                }
                returncode = 0
                result_path.write_text(json.dumps(payload), encoding="utf-8")
                log_path.write_text(
                    "deterministic recovery completed\n",
                    encoding="utf-8",
                )
            return LaunchResult(
                payload=payload,
                returncode=returncode,
                timed_out=timed_out,
                forced_cleanup=timed_out,
                discarded_log_bytes=0,
                result_path=result_path,
                log_path=log_path,
                duration_ms=0,
                input_tokens=None,
                cached_input_tokens=None,
                output_tokens=None,
                reasoning_output_tokens=None,
                launcher_prompt_bytes=1,
            )

        runner.launcher.launch = mock.Mock(
            side_effect=recovery_without_a_process
        )
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[
                self.plan(1, "interrupted"),
                self.plan(2, "interrupted"),
            ],
            run_id="recovery-wiring",
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [plan["attempt_count"] for plan in result["plans"]],
            [1, 0],
        )
        self.assertEqual(
            [plan["status"] for plan in result["plans"]],
            ["failed", "pending"],
        )
        self.assertEqual(len(launch_calls), 1)
        persisted = StateStore.open(
            self.home / "orchestrator" / "recovery-wiring"
        ).state
        self.assertEqual(persisted["format_version"], 2)
        self.assertEqual(persisted["status"], "failed")
        self.assertEqual(persisted["plans"][1]["status"], "pending")
        self.assertEqual(persisted["plans"][1]["checkpoint_count"], 0)
        self.assertEqual(
            [plan["attempt_count"] for plan in persisted["plans"]],
            [1, 0],
        )
        events = [
            json.loads(line)
            for line in (
                self.home
                / "orchestrator"
                / "recovery-wiring"
                / "events.jsonl"
            ).read_text().splitlines()
        ]
        self.assertTrue(any(event["action"] == "plan.attempt_incomplete" for event in events))

    def test_progress_ledger_read_is_bounded_before_parsing(self) -> None:
        evidence = self.repo / ".superpowers" / "sdd"
        evidence.mkdir(parents=True)
        ledger = evidence / "progress.md"
        prefix = b"Task 1: complete\n"
        ledger.write_bytes(
            prefix
            + b" " * (65_536 - len(prefix))
            + b"Task 2: complete\n"
        )

        real_read = os.read
        requested: list[int] = []
        returned: list[int] = []

        def bounded_read(descriptor: int, count: int) -> bytes:
            requested.append(count)
            chunk = real_read(descriptor, count)
            returned.append(len(chunk))
            return chunk

        with mock.patch("cpe_runtime.runner.os.read", side_effect=bounded_read):
            completed, current = _ledger_progress(self.repo)

        self.assertEqual(completed, ["Task 1"])
        self.assertEqual(current, "Task 2")
        self.assertTrue(requested)
        self.assertTrue(all(count <= 65_536 for count in requested))
        self.assertLessEqual(sum(returned), 65_536)

    def test_existing_capsule_must_match_expected_canonical_bytes(self) -> None:
        target = self.root / "capsule.json"
        payload = {"plan_id": "plan-01", "attempt": 1}
        self.assertEqual(_write_private_json(target, payload), target.resolve())
        self.assertEqual(_write_private_json(target, payload), target.resolve())

        target.write_text('{"different":true}', encoding="utf-8")
        target.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "capsule"):
            _write_private_json(target, payload)

    def test_existing_capsule_rejects_unsafe_mode_and_symlink(self) -> None:
        target = self.root / "capsule.json"
        payload = {"plan_id": "plan-01", "attempt": 1}
        _write_private_json(target, payload)
        target.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "capsule"):
            _write_private_json(target, payload)

        target.unlink()
        backing = self.root / "backing.json"
        _write_private_json(backing, payload)
        target.symlink_to(backing)
        with self.assertRaisesRegex((OSError, ValueError), "capsule|symlink"):
            _write_private_json(target, payload)

    def test_new_capsule_partial_write_is_removed(self) -> None:
        target = self.root / "capsule.json"
        payload = {"plan_id": "plan-01", "attempt": 1}
        with mock.patch(
            "cpe_runtime.runner.os.write",
            side_effect=OSError("injected write failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected write failure"):
                _write_private_json(target, payload)
        self.assertFalse(target.exists())

    def test_nonretryable_failure_stops_until_one_explicit_retry(self) -> None:
        self.assertEqual(
            _recovery_decision(
                payload={"status": "failed"},
                timed_out=False,
                previous_signature=None,
                automatic_available=True,
            ),
            (False, "not_retryable", "status:failed", ""),
        )
        runner = self.runner()
        launch_count = 0

        def fail_without_a_process(**kwargs: object) -> LaunchResult:
            nonlocal launch_count
            launch_count += 1
            result_path = Path(kwargs["result_path"])
            log_path = Path(kwargs["log_path"])
            payload = {
                "plan_id": kwargs["plan_id"],
                "status": "failed",
                "head_commit": kwargs["current_commit"],
                "verification": [],
                "summary": "deterministic nonretryable failure",
            }
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            log_path.write_text(
                "deterministic nonretryable failure\n",
                encoding="utf-8",
            )
            return LaunchResult(
                payload=payload,
                returncode=1,
                timed_out=False,
                forced_cleanup=False,
                discarded_log_bytes=0,
                result_path=result_path,
                log_path=log_path,
                duration_ms=0,
                input_tokens=None,
                cached_input_tokens=None,
                output_tokens=None,
                reasoning_output_tokens=None,
                launcher_prompt_bytes=1,
            )

        runner.launcher.launch = mock.Mock(side_effect=fail_without_a_process)
        initial = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "failed")],
            run_id="explicit-retry",
        )
        self.assertEqual(initial["status"], "failed")
        self.assertEqual(initial["plans"][0]["attempt_count"], 1)
        self.assertEqual(launch_count, 1)
        result = runner.resume(run_id="explicit-retry", retry_failed=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(launch_count, 2)
        self.assertEqual(result["plans"][0]["attempt_count"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
