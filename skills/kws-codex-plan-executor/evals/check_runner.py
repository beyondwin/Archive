#!/usr/bin/env python3
"""Contract evals for the sequential plan runner."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib
import json
import os
import selectors
import signal
import shutil
import stat
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
    StructuredLaunchRequest,
    _drain_registered,
    _terminate_group,
    _JsonEventFilter,
)
import cpe_runtime.launcher as launcher_module
from cpe_runtime.capabilities import (
    CapabilityObservation,
    blocker_resume_decision,
    canonicalize_observation,
    environment_fingerprint,
    typed_blockers,
    validate_observation,
)
from cpe_runtime.progress import (
    CheckpointBudget,
    ProgressSnapshot,
    decide_child_outcome,
    decide_checkpoint,
    observe_worktree_changes,
    progress_fingerprint,
)
from cpe_runtime.verification import (
    MAX_VERIFICATION_LOG_BYTES,
    VerificationRequest,
    execution_environment_fingerprint,
    execute_verification,
    find_reusable_receipt,
    materialize_helper_descriptor,
    resolved_executable_identity,
    verification_cache_key,
)
from cpe_runtime.evidence import (
    MAX_EVIDENCE_FILE_BYTES,
    append_execution_event,
    ingest_plan_evidence,
    read_progress_snapshot,
    validate_execution_ledger,
)
import cpe_runtime.evidence as evidence_module
from cpe_runtime.reporting import (
    MAX_OBSERVED_COUNTER,
    build_optimization_report,
    render_optimization_markdown,
)
import cpe_runtime.reporting as reporting_module
import cpe_runtime.runner as runner_module
from cpe_runtime.runner import (
    SequentialRunner,
    _ledger_progress,
    _recovery_decision,
    _write_private_json,
)
from cpe_runtime.state import StateStore
try:
    from evals.fake_codex import workflow_receipt
except ModuleNotFoundError as exc:
    if exc.name != "evals":
        raise
    from fake_codex import workflow_receipt


class VerificationReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.worktree = self.root / "worktree"
        self.cwd = self.worktree / "project"
        self.cwd.mkdir(parents=True)
        self.evidence_root = (
            self.worktree / ".superpowers" / "sdd" / "verification"
        )

    def request(self, **changes: object) -> VerificationRequest:
        execution_environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PWD", "OLDPWD", "SHLVL", "_", "TERM_SESSION_ID"}
        }
        values: dict[str, object] = {
            "run_id": "run-one",
            "command_id": "unit",
            "argv": (sys.executable, "-c", "print('ok')"),
            "cwd": self.cwd,
            "head": "a" * 40,
            "environment_fingerprint": execution_environment_fingerprint(
                environ=execution_environment,
                sandbox_mode="danger-full-access",
                executable_identity=resolved_executable_identity(
                    sys.executable, cwd=self.cwd, environ=execution_environment
                ),
            ),
            "phase": "task",
            "input_digest": "1" * 64,
            "deterministic": True,
            "mutable_input_policy": "immutable",
            "required_artifact_paths": (),
            "timeout_seconds": 10,
        }
        values.update(changes)
        return VerificationRequest(**values)  # type: ignore[arg-type]

    def test_cache_key_uses_six_execution_identity_parts(self) -> None:
        base = self.request(command_id="unit", phase="task")
        self.assertEqual(
            verification_cache_key(base),
            verification_cache_key(
                self.request(command_id="renamed", phase="branch_final")
            ),
        )
        other_cwd = self.worktree / "other"
        other_cwd.mkdir()
        for field, replacement in (
            ("argv", (sys.executable, "-c", "print('other')")),
            ("cwd", other_cwd),
            ("head", "b" * 40),
            ("environment_fingerprint", "2" * 64),
            ("input_digest", "2" * 64),
            ("mutable_input_policy", "always_execute"),
        ):
            with self.subTest(field=field):
                changed = dataclasses.replace(base, **{field: replacement})
                self.assertNotEqual(
                    verification_cache_key(base),
                    verification_cache_key(changed),
                )

        for field, replacement in (
            ("run_id", "run-two"),
            ("timeout_seconds", 11),
            ("deterministic", False),
            ("required_artifact_paths", ("result.txt",)),
        ):
            with self.subTest(non_key_field=field):
                changed = dataclasses.replace(base, **{field: replacement})
                self.assertEqual(
                    verification_cache_key(base),
                    verification_cache_key(changed),
                )

    def test_receipt_reuses_across_phase_and_command_id_without_relabelling_execution(self) -> None:
        executed_request = self.request(command_id="unit", phase="task")
        receipt = execute_verification(self.evidence_root, executed_request)
        requested = self.request(command_id="branch-unit", phase="branch_final")

        reused = find_reusable_receipt(self.evidence_root, requested)

        self.assertEqual(receipt, reused)
        assert reused is not None
        self.assertEqual("unit", reused.request["command_id"])
        self.assertEqual("task", reused.request["executed_phase"])

    def test_sealed_receipt_persists_only_argv_digest_not_raw_argv(self) -> None:
        inline_marker = "private-inline-argument-marker"
        request = self.request(
            argv=(sys.executable, "-c", f"print({inline_marker!r})")
        )

        receipt = execute_verification(self.evidence_root, request)
        document = json.loads(
            (self.evidence_root / "receipts" / f"{receipt.receipt_id}.json")
            .read_text(encoding="utf-8")
        )
        serialized = json.dumps(document, sort_keys=True)

        self.assertNotIn("argv", document["request"])
        self.assertEqual(
            hashlib.sha256(
                json.dumps(list(request.argv), separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            document["request"]["argv_digest"],
        )
        self.assertNotIn(sys.executable, serialized)
        self.assertNotIn(inline_marker, serialized)

    def test_environment_fingerprint_binds_exact_mapping_sandbox_and_executable(self) -> None:
        environ = {"PATH": os.environ.get("PATH", ""), "CPE_VISIBLE": "one"}
        executable = resolved_executable_identity(
            sys.executable, cwd=self.cwd, environ=environ
        )
        base = execution_environment_fingerprint(
            environ=environ,
            sandbox_mode="danger-full-access",
            executable_identity=executable,
        )

        self.assertNotEqual(
            base,
            execution_environment_fingerprint(
                environ={**environ, "CPE_VISIBLE": "two"},
                sandbox_mode="danger-full-access",
                executable_identity=executable,
            ),
        )
        self.assertNotEqual(
            base,
            execution_environment_fingerprint(
                environ=environ,
                sandbox_mode="workspace-write",
                executable_identity=executable,
            ),
        )
        self.assertEqual(64, len(base))
        self.assertNotIn("CPE_VISIBLE", base)
        self.assertNotIn("one", base)

    def test_executable_identity_resolves_symlink_and_detects_replacement(self) -> None:
        executable = self.root / "tools" / "verify-tool"
        executable.parent.mkdir()
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        link = executable.parent / "verify-link"
        link.symlink_to(executable)
        environ = {"PATH": str(executable.parent)}

        first = resolved_executable_identity(
            "verify-link", cwd=self.cwd, environ=environ
        )
        executable.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        executable.chmod(0o755)
        second = resolved_executable_identity(
            "verify-link", cwd=self.cwd, environ=environ
        )

        self.assertEqual(
            {"resolved_path_digest", "device", "inode", "size", "mtime_ns", "sha256"},
            set(first),
        )
        self.assertNotEqual(first, second)
        self.assertNotIn(str(executable), json.dumps(first))

        executable.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "regular executable"):
            resolved_executable_identity(str(link), cwd=self.cwd, environ=environ)

    def test_digest_complete_requires_non_placeholder_lowercase_sha256(self) -> None:
        valid = self.request(
            mutable_input_policy="digest_complete",
            input_digest="1" * 64,
        )
        self.assertEqual(64, len(verification_cache_key(valid)))

        for invalid in ("", "not-a-digest", "A" * 64, "0" * 64):
            with self.subTest(input_digest=invalid):
                with self.assertRaisesRegex(ValueError, "input digest"):
                    verification_cache_key(
                        dataclasses.replace(valid, input_digest=invalid)
                    )

        immutable_sentinel = self.request(input_digest="immutable")
        self.assertEqual(64, len(verification_cache_key(immutable_sentinel)))

    def test_passing_receipt_is_reusable_only_for_same_run_execution_identity(self) -> None:
        request = self.request()
        receipt = execute_verification(self.evidence_root, request)

        self.assertEqual("passed", receipt.status)
        self.assertEqual(receipt, find_reusable_receipt(self.evidence_root, request))
        self.assertIsNone(
            find_reusable_receipt(
                self.evidence_root,
                dataclasses.replace(request, run_id="run-two"),
            )
        )
        self.assertIsNotNone(
            find_reusable_receipt(
                self.evidence_root,
                dataclasses.replace(request, timeout_seconds=11),
            )
        )

    def test_execution_preserves_argv_boundaries_and_bounds_each_log(self) -> None:
        marker = self.cwd / "shell-expanded"
        script = (
            "import sys; "
            f"print('x' * {MAX_VERIFICATION_LOG_BYTES + 4096}); "
            f"print('y' * {MAX_VERIFICATION_LOG_BYTES + 4096}, file=sys.stderr); "
            "print(sys.argv[1])"
        )
        request = self.request(
            argv=(sys.executable, "-c", script, f"value; touch {marker}"),
        )

        receipt = execute_verification(self.evidence_root, request)

        self.assertEqual("passed", receipt.status)
        self.assertFalse(marker.exists())
        stdout = self.evidence_root / receipt.stdout_path
        stderr = self.evidence_root / receipt.stderr_path
        self.assertLessEqual(stdout.stat().st_size, MAX_VERIFICATION_LOG_BYTES)
        self.assertLessEqual(stderr.stat().st_size, MAX_VERIFICATION_LOG_BYTES)
        self.assertEqual("logs", stdout.parent.name)
        self.assertEqual("logs", stderr.parent.name)
        receipt_files = list((self.evidence_root / "receipts").glob("*.json"))
        self.assertEqual(1, len(receipt_files))
        self.assertEqual(0o400, stat.S_IMODE(receipt_files[0].stat().st_mode))

    def test_nonpassing_nondeterministic_and_always_execute_receipts_are_not_reused(self) -> None:
        failed = self.request(argv=(sys.executable, "-c", "raise SystemExit(7)"))
        self.assertEqual("failed", execute_verification(self.evidence_root, failed).status)
        self.assertIsNone(find_reusable_receipt(self.evidence_root, failed))

        timed_out = self.request(
            command_id="timeout",
            argv=(sys.executable, "-c", "import time; time.sleep(2)"),
            timeout_seconds=1,
        )
        self.assertEqual(
            "timed_out", execute_verification(self.evidence_root, timed_out).status
        )
        self.assertIsNone(find_reusable_receipt(self.evidence_root, timed_out))

        for request in (
            self.request(command_id="nondeterministic", deterministic=False),
            self.request(
                command_id="mutable",
                mutable_input_policy="always_execute",
            ),
        ):
            self.assertEqual(
                "passed", execute_verification(self.evidence_root, request).status
            )
            self.assertIsNone(find_reusable_receipt(self.evidence_root, request))

    def test_required_artifact_must_remain_regular_inside_worktree_with_same_digest(self) -> None:
        artifact = self.cwd / "result.txt"
        artifact.write_text("first\n", encoding="utf-8")
        request = self.request(required_artifact_paths=("project/result.txt",))
        execute_verification(self.evidence_root, request)
        self.assertIsNotNone(find_reusable_receipt(self.evidence_root, request))

        artifact.write_text("changed\n", encoding="utf-8")
        self.assertIsNone(find_reusable_receipt(self.evidence_root, request))
        artifact.unlink()
        self.assertIsNone(find_reusable_receipt(self.evidence_root, request))
        self.assertFalse((self.evidence_root / "corruption-events.jsonl").exists())
        artifact.symlink_to(self.cwd / "elsewhere.txt")
        self.assertIsNone(find_reusable_receipt(self.evidence_root, request))

        self.assertIsNone(
            find_reusable_receipt(
                self.evidence_root,
                dataclasses.replace(
                    request, required_artifact_paths=("../outside.txt",)
                ),
            )
        )

    def test_receipt_copied_from_another_evidence_root_is_not_reusable(self) -> None:
        request = self.request()
        execute_verification(self.evidence_root, request)
        other_worktree = self.root / "other-worktree"
        other_cwd = other_worktree / "project"
        other_cwd.mkdir(parents=True)
        other_root = other_worktree / ".superpowers" / "sdd" / "verification"
        shutil.copytree(self.evidence_root, other_root)
        copied_request = dataclasses.replace(request, cwd=other_cwd)

        self.assertIsNone(find_reusable_receipt(other_root, copied_request))

    def test_malformed_or_digest_mismatched_receipt_emits_corruption_event(self) -> None:
        request = self.request()
        receipt = execute_verification(self.evidence_root, request)
        receipt_path = self.evidence_root / "receipts" / f"{receipt.receipt_id}.json"
        receipt_path.chmod(0o600)
        document = json.loads(receipt_path.read_text(encoding="utf-8"))
        document["stdout_digest"] = "0" * 64
        receipt_path.write_text(json.dumps(document), encoding="utf-8")
        receipt_path.chmod(0o400)

        self.assertIsNone(find_reusable_receipt(self.evidence_root, request))
        events = [
            json.loads(line)
            for line in (self.evidence_root / "corruption-events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual("verification.receipt_corrupt", events[-1]["event"])
        self.assertEqual(verification_cache_key(request), events[-1]["cache_key"])
        self.assertNotIn("error", events[-1])

    def test_helper_descriptor_is_private_absolute_and_source_bound(self) -> None:
        run_root = self.root / "run"
        cpe_script = ROOT / "scripts" / "cpe.py"
        descriptor_path = materialize_helper_descriptor(run_root, cpe_script)
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))

        self.assertEqual(0o400, stat.S_IMODE(descriptor_path.stat().st_mode))
        self.assertEqual(["python3", str(cpe_script.resolve()), "verify"], descriptor["argv_prefix"])
        self.assertEqual(
            hashlib.sha256(cpe_script.read_bytes()).hexdigest(),
            descriptor["source_digests"]["cpe.py"],
        )
        verification_source = ROOT / "scripts" / "cpe_runtime" / "verification.py"
        self.assertEqual(
            hashlib.sha256(verification_source.read_bytes()).hexdigest(),
            descriptor["source_digests"]["cpe_runtime/verification.py"],
        )

        descriptor_path.chmod(0o600)
        descriptor_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "replaced"):
            materialize_helper_descriptor(run_root, cpe_script)

        symlink = self.root / "cpe-link.py"
        symlink.symlink_to(cpe_script)
        with self.assertRaisesRegex(ValueError, "regular source"):
            materialize_helper_descriptor(self.root / "other-run", symlink)

    def test_helper_descriptor_binds_every_runtime_python_source_and_detects_drift(self) -> None:
        scripts = self.root / "scripts"
        shutil.copytree(ROOT / "scripts", scripts)
        cpe_script = scripts / "cpe.py"
        run_root = self.root / "run"

        descriptor_path = materialize_helper_descriptor(run_root, cpe_script)
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        expected_sources = {
            "cpe.py": cpe_script,
            **{
                f"cpe_runtime/{path.name}": path
                for path in sorted((scripts / "cpe_runtime").glob("*.py"))
            },
        }

        self.assertEqual(set(expected_sources), set(descriptor["source_digests"]))
        for name, path in expected_sources.items():
            with self.subTest(source=name):
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    descriptor["source_digests"][name],
                )

        runtime_source = scripts / "cpe_runtime" / "runner.py"
        runtime_source.write_text(
            runtime_source.read_text(encoding="utf-8") + "\n# descriptor drift\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "replaced"):
            materialize_helper_descriptor(run_root, cpe_script)


class VerificationReuseIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-verify-ingest-")
        self.addCleanup(self.temporary.cleanup)
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
        plan = self.repo / "plan.md"
        plan.write_text("Verify once.\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "plan.md"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "seed"],
            check=True,
        )
        self.run_id = "verification-ingest"
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-q", "-b", f"codex/{self.run_id}"],
            check=True,
        )
        self.store = StateStore.create(
            run_root=self.home / "orchestrator" / self.run_id,
            run_id=self.run_id,
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.repo,
            branch=f"codex/{self.run_id}",
            specs=[],
            plans=[plan],
        )

    def execution_environment_fingerprint(self, argv0: str) -> str:
        environ = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PWD", "OLDPWD", "SHLVL", "_", "TERM_SESSION_ID"}
        }
        return execution_environment_fingerprint(
            environ=environ,
            sandbox_mode="danger-full-access",
            executable_identity=resolved_executable_identity(
                argv0, cwd=self.repo, environ=environ
            ),
        )

    def test_prompt_exposes_helper_descriptor_without_verification_policy(self) -> None:
        descriptor = self.store.root / "tools" / "run-and-record.json"
        prompt = CodexLauncher._prompt(
            worktree=self.repo,
            plan_id="plan-01",
            plan_path=self.store.root / "inputs" / "plan-01.md",
            spec_paths=[],
            starting_commit=git(self.repo, "rev-parse", "HEAD"),
            current_commit=git(self.repo, "rev-parse", "HEAD"),
            recovery_path=None,
            execution_ledger=self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
            verification_helper_descriptor=descriptor,
        )

        self.assertIn(f"VERIFICATION_HELPER_DESCRIPTOR: {descriptor}", prompt)
        self.assertNotIn("command-id", prompt)
        self.assertNotIn("cache", prompt.lower())
        self.assertNotIn("fallback", prompt.lower())

    def test_prompt_does_not_prescribe_superpowers_workflow_semantics(self) -> None:
        prompt = CodexLauncher._prompt(
            worktree=self.repo,
            plan_id="plan-01",
            plan_path=self.store.root / "inputs" / "plan-01.md",
            spec_paths=[],
            starting_commit=git(self.repo, "rev-parse", "HEAD"),
            current_commit=git(self.repo, "rev-parse", "HEAD"),
            recovery_path=None,
            execution_ledger=(
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl"
            ),
            verification_helper_descriptor=(
                self.store.root / "tools" / "run-and-record.json"
            ),
        )

        for policy in (
            "subagent-driven-development",
            "task-brief",
            "review-package",
            "consolidated fix subagent",
            "finding delta",
            "cross-task final review",
        ):
            with self.subTest(policy=policy):
                self.assertNotIn(policy, prompt)

    def test_prompt_contains_only_infrastructure_worktree_boundaries(self) -> None:
        prompt = CodexLauncher._prompt(
            worktree=self.repo,
            plan_id="plan-01",
            plan_path=self.store.root / "inputs" / "plan-01.md",
            spec_paths=[],
            starting_commit=git(self.repo, "rev-parse", "HEAD"),
            current_commit=git(self.repo, "rev-parse", "HEAD"),
            recovery_path=None,
            execution_ledger=self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
            verification_helper_descriptor=self.store.root / "tools" / "run-and-record.json",
        )

        self.assertIn("already isolated", prompt)
        self.assertNotIn("COMPILED_RUN_INDEX", prompt)
        for forbidden in (
            "task mapping",
            "delta review",
            "finding cycle",
            "subagent count",
            "on recovery",
            "for verification commands",
            "branch_final",
            "cache hit",
            "uncached_command_required",
            "do not run the same",
            "successful final verification",
        ):
            self.assertNotIn(forbidden, prompt.lower())

    def test_replaced_helper_descriptor_without_exact_request_fails_closed(self) -> None:
        descriptor = materialize_helper_descriptor(
            self.store.root, ROOT / "scripts" / "cpe.py"
        )
        descriptor.chmod(0o600)
        descriptor.write_text("{}", encoding="utf-8")
        descriptor.chmod(0o400)
        runner = SequentialRunner(codex_home=self.home)

        with self.assertRaisesRegex(ValueError, "without exact submitted request"):
            runner._verification_helper_descriptor_for_launch(self.store)

        events = [
            json.loads(line)
            for line in self.store.events_path.read_text(encoding="utf-8").splitlines()
        ]
        fallback = [
            event for event in events
            if event.get("action") == "verification.helper_unavailable_no_request"
        ]
        self.assertEqual(1, len(fallback))
        self.assertEqual("verification_helper_unavailable", fallback[0]["reason"])

    def test_resume_validates_run_id_then_opens_state_without_command_id(self) -> None:
        runner = SequentialRunner(codex_home=self.home)
        with mock.patch.object(
            StateStore, "open", side_effect=ValueError("resume state opened")
        ) as opened:
            with self.assertRaisesRegex(ValueError, "resume state opened"):
                runner.resume(run_id="missing-valid-run")

        opened.assert_called_once_with(
            (self.home / "orchestrator" / "missing-valid-run").resolve()
        )

    def test_parent_ingests_nonreusable_receipt_once_without_relabelling_pass(self) -> None:
        evidence_root = self.repo / ".superpowers" / "sdd" / "verification"
        request = VerificationRequest(
            run_id=self.run_id,
            command_id="unit",
            argv=(sys.executable, "-c", "print('ok')"),
            cwd=self.repo,
            head=git(self.repo, "rev-parse", "HEAD"),
            environment_fingerprint=self.execution_environment_fingerprint(sys.executable),
            phase="task",
            input_digest="immutable",
            deterministic=True,
            mutable_input_policy="always_execute",
            required_artifact_paths=(),
            timeout_seconds=10,
        )
        receipts = [
            execute_verification(evidence_root, request),
            execute_verification(evidence_root, request),
        ]
        self.assertNotEqual(receipts[0].receipt_id, receipts[1].receipt_id)
        self.assertFalse((evidence_root / "indexes").exists())
        argv_digest = hashlib.sha256(
            json.dumps(list(request.argv), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for marker, receipt in zip(("a", "b"), receipts, strict=True):
            append_execution_event(
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
                {
                    "event_id": "verification.executed:" + marker * 32,
                    "source": "child_attested",
                    "plan_id": "plan-01",
                    "category": "verification",
                    "action": "verified",
                    "result": "pass",
                    "evidence_refs": [
                        f"verification/receipts/{receipt.receipt_id}.json",
                        f"verification/{receipt.stdout_path}",
                        f"verification/{receipt.stderr_path}",
                    ],
                    "command_id": "unit",
                    "argv_digest": argv_digest,
                    "evidence_key": receipt.cache_key,
                    "duration_ms": 1,
                    "requested_phase": "task",
                    "executed_phase": "task",
                    "avoided_executions": 0,
                },
            )
        runner = SequentialRunner(codex_home=self.home)

        runner._ingest_verification_observations(self.store)
        runner._ingest_verification_observations(self.store)

        events = [
            json.loads(line)
            for line in self.store.events_path.read_text(encoding="utf-8").splitlines()
        ]
        ingested = [
            event for event in events
            if event.get("action") == "verification.evidence_ingested"
        ]
        self.assertEqual(2, len(ingested))
        self.assertEqual({receipt.receipt_id for receipt in receipts}, {
            event["receipt_id"] for event in ingested
        })
        for event in ingested:
            self.assertEqual("parent_observed", event["source"])
            self.assertEqual("child_attested", event["semantic_source"])
            self.assertEqual("executed", event["decision"])
            self.assertNotIn("result", event)

    def test_reused_claim_requires_prior_validated_executed_lifecycle(self) -> None:
        evidence_root = self.repo / ".superpowers" / "sdd" / "verification"
        request = VerificationRequest(
            run_id=self.run_id,
            command_id="unit",
            argv=(sys.executable, "-c", "print('ok')"),
            cwd=self.repo,
            head=git(self.repo, "rev-parse", "HEAD"),
            environment_fingerprint=self.execution_environment_fingerprint(sys.executable),
            phase="task",
            input_digest="immutable",
            deterministic=True,
            mutable_input_policy="immutable",
            required_artifact_paths=(),
            timeout_seconds=10,
        )
        receipt = execute_verification(evidence_root, request)
        argv_digest = hashlib.sha256(
            json.dumps(list(request.argv), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        append_execution_event(
            self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
            {
                "event_id": "verification.reused:" + "a" * 32,
                "source": "child_attested",
                "plan_id": "plan-01",
                "category": "verification",
                "action": "verified",
                "result": "pass",
                "evidence_refs": [
                    f"verification/receipts/{receipt.receipt_id}.json",
                    f"verification/{receipt.stdout_path}",
                    f"verification/{receipt.stderr_path}",
                ],
                "command_id": "unit",
                "argv_digest": argv_digest,
                "evidence_key": receipt.cache_key,
                "duration_ms": 0,
                "requested_phase": "task",
                "executed_phase": "task",
                "avoided_executions": 1,
            },
        )

        with self.assertRaisesRegex(ValueError, "executed lifecycle"):
            SequentialRunner(codex_home=self.home)._ingest_verification_observations(
                self.store
            )

    def test_valid_executed_then_reused_lifecycle_is_parent_observed(self) -> None:
        evidence_root = self.repo / ".superpowers" / "sdd" / "verification"
        request = VerificationRequest(
            run_id=self.run_id,
            command_id="unit",
            argv=(sys.executable, "-c", "print('ok')"),
            cwd=self.repo,
            head=git(self.repo, "rev-parse", "HEAD"),
            environment_fingerprint=self.execution_environment_fingerprint(sys.executable),
            phase="task",
            input_digest="immutable",
            deterministic=True,
            mutable_input_policy="immutable",
            required_artifact_paths=(),
            timeout_seconds=10,
        )
        receipt = execute_verification(evidence_root, request)
        argv_digest = hashlib.sha256(
            json.dumps(list(request.argv), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        references = [
            f"verification/receipts/{receipt.receipt_id}.json",
            f"verification/{receipt.stdout_path}",
            f"verification/{receipt.stderr_path}",
        ]
        for decision, marker, command_id, requested_phase in (
            ("executed", "a", "unit", "task"),
            ("reused", "b", "branch-unit", "branch_final"),
        ):
            append_execution_event(
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
                {
                    "event_id": f"verification.{decision}:" + marker * 32,
                    "source": "child_attested",
                    "plan_id": "plan-01",
                    "category": "verification",
                    "action": "verified",
                    "result": "pass",
                    "evidence_refs": references,
                    "command_id": command_id,
                    "argv_digest": argv_digest,
                    "evidence_key": receipt.cache_key,
                    "duration_ms": 0,
                    "requested_phase": requested_phase,
                    "executed_phase": "task",
                    "avoided_executions": 1 if decision == "reused" else 0,
                },
            )

        runner = SequentialRunner(codex_home=self.home)
        runner._ingest_verification_observations(self.store)

        events = [
            json.loads(line)
            for line in self.store.events_path.read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("action") == "verification.evidence_ingested"
        ]
        self.assertEqual(["executed", "reused"], [event["decision"] for event in events])
        self.assertEqual("branch-unit", events[-1]["command_id"])
        self.assertEqual("branch_final", events[-1]["requested_phase"])
        self.assertEqual("task", events[-1]["executed_phase"])
        self.assertEqual(1, events[-1]["avoided_executions"])

    def test_failed_and_timed_out_executions_remain_counted_facts(self) -> None:
        evidence_root = self.repo / ".superpowers" / "sdd" / "verification"
        requests = (
            VerificationRequest(
                run_id=self.run_id,
                command_id="failed-unit",
                argv=(sys.executable, "-c", "raise SystemExit(7)"),
                cwd=self.repo,
                head=git(self.repo, "rev-parse", "HEAD"),
                environment_fingerprint=self.execution_environment_fingerprint(sys.executable),
                phase="task",
                input_digest="immutable",
                deterministic=True,
                mutable_input_policy="immutable",
                required_artifact_paths=(),
                timeout_seconds=10,
            ),
            VerificationRequest(
                run_id=self.run_id,
                command_id="timed-unit",
                argv=(sys.executable, "-c", "import time; time.sleep(2)"),
                cwd=self.repo,
                head=git(self.repo, "rev-parse", "HEAD"),
                environment_fingerprint=self.execution_environment_fingerprint(sys.executable),
                phase="affected",
                input_digest="immutable",
                deterministic=True,
                mutable_input_policy="immutable",
                required_artifact_paths=(),
                timeout_seconds=1,
            ),
        )
        receipts = [execute_verification(evidence_root, request) for request in requests]
        self.assertEqual(["failed", "timed_out"], [receipt.status for receipt in receipts])
        for marker, request, receipt in zip(("f", "t"), requests, receipts, strict=True):
            append_execution_event(
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
                {
                    "event_id": "verification.executed:" + marker * 32,
                    "source": "child_attested",
                    "plan_id": "plan-01",
                    "category": "verification",
                    "action": "verified",
                    "result": "fail",
                    "evidence_refs": [
                        f"verification/receipts/{receipt.receipt_id}.json",
                        f"verification/{receipt.stdout_path}",
                        f"verification/{receipt.stderr_path}",
                    ],
                    "command_id": request.command_id,
                    "argv_digest": hashlib.sha256(
                        json.dumps(list(request.argv), separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    "evidence_key": receipt.cache_key,
                    "duration_ms": 1,
                    "requested_phase": request.phase,
                    "executed_phase": request.phase,
                    "avoided_executions": 0,
                },
            )

        runner = SequentialRunner(codex_home=self.home)
        runner._ingest_verification_observations(self.store)
        parent_events = [
            json.loads(line)
            for line in self.store.events_path.read_text(encoding="utf-8").splitlines()
        ]
        ingested = [
            event for event in parent_events
            if event.get("action") == "verification.evidence_ingested"
        ]
        report = build_optimization_report(
            run_id=self.run_id,
            events=parent_events,
            findings=[],
        )

        self.assertEqual(2, len(ingested))
        self.assertEqual(["failed", "timed_out"], [event["verification_status"] for event in ingested])
        self.assertEqual(2, report["verification"]["requests"])
        self.assertEqual(2, report["verification"]["executions"])
        self.assertEqual(
            {"task": 1, "affected": 1, "branch_final": 0},
            report["verification"]["executed_phase_counts"],
        )

    def test_duplicate_executed_lifecycle_for_same_receipt_is_rejected(self) -> None:
        evidence_root = self.repo / ".superpowers" / "sdd" / "verification"
        request = VerificationRequest(
            run_id=self.run_id,
            command_id="unit",
            argv=(sys.executable, "-c", "print('ok')"),
            cwd=self.repo,
            head=git(self.repo, "rev-parse", "HEAD"),
            environment_fingerprint=self.execution_environment_fingerprint(sys.executable),
            phase="task",
            input_digest="immutable",
            deterministic=True,
            mutable_input_policy="immutable",
            required_artifact_paths=(),
            timeout_seconds=10,
        )
        receipt = execute_verification(evidence_root, request)
        references = [
            f"verification/receipts/{receipt.receipt_id}.json",
            f"verification/{receipt.stdout_path}",
            f"verification/{receipt.stderr_path}",
        ]
        argv_digest = hashlib.sha256(
            json.dumps(list(request.argv), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for marker in ("a", "b"):
            append_execution_event(
                self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
                {
                    "event_id": "verification.executed:" + marker * 32,
                    "source": "child_attested",
                    "plan_id": "plan-01",
                    "category": "verification",
                    "action": "verified",
                    "result": "pass",
                    "evidence_refs": references,
                    "command_id": "unit",
                    "argv_digest": argv_digest,
                    "evidence_key": receipt.cache_key,
                    "duration_ms": 1,
                    "requested_phase": "task",
                    "executed_phase": "task",
                    "avoided_executions": 0,
                },
            )

        with self.assertRaisesRegex(ValueError, "duplicate executed lifecycle"):
            SequentialRunner(codex_home=self.home)._ingest_verification_observations(
                self.store
            )

    def test_uncached_pass_has_strict_null_receipt_and_idempotent_parent_ingest(self) -> None:
        evidence_key = hashlib.sha256(b"uncached-unit").hexdigest()
        argv_digest = hashlib.sha256(b"uncached-argv").hexdigest()
        append_execution_event(
            self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
            {
                "event_id": "verification.executed_uncached:" + "a" * 32,
                "source": "child_attested",
                "plan_id": "plan-01",
                "category": "verification",
                "action": "executed_uncached",
                "result": "pass",
                "evidence_refs": [],
                "command_id": "unit-uncached",
                "argv_digest": argv_digest,
                "evidence_key": evidence_key,
                "duration_ms": 12,
                "exit_code": 0,
                "receipt_path": None,
                "reason_code": "uncached_command_required",
                "requested_phase": "task",
                "executed_phase": "task",
                "avoided_executions": 0,
            },
        )
        runner = SequentialRunner(codex_home=self.home)

        runner._ingest_verification_observations(self.store)
        runner._ingest_verification_observations(self.store)

        validate_execution_ledger(
            self.repo / ".superpowers" / "sdd" / "execution-ledger.jsonl",
            expected_plan_id="plan-01",
        )
        ingested = [
            json.loads(line)
            for line in self.store.events_path.read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("action") == "verification.evidence_ingested"
        ]
        self.assertEqual(1, len(ingested))
        self.assertEqual("executed_uncached", ingested[0]["decision"])
        self.assertEqual(0, ingested[0]["exit_code"])
        self.assertIsNone(ingested[0]["receipt_id"])
        self.assertFalse((self.repo / ".superpowers" / "sdd" / "verification" / "indexes").exists())

    def test_unavailable_dirty_inventory_executes_without_lookup_or_index_publication(self) -> None:
        materialize_helper_descriptor(self.store.root, ROOT / "scripts" / "cpe.py")
        self.store.state["status"] = "ready"
        self.store.save()
        counter = self.root / "dirty-inventory-counter.txt"
        argv = (
            sys.executable,
            "-c",
            f"from pathlib import Path; p=Path({str(counter)!r}); p.write_text((p.read_text() if p.exists() else '') + 'x')",
        )
        unavailable = mock.Mock(changed=True, reason_code="dirty_inventory_unavailable")
        runner = SequentialRunner(codex_home=self.home)

        with mock.patch.object(
            runner_module, "observe_worktree_changes", return_value=unavailable
        ):
            first = runner.verify(
                run_id=self.run_id,
                command_id="unit",
                phase="task",
                input_digest="immutable",
                mutable_input_policy="immutable",
                cwd=self.repo,
                argv=argv,
            )
            second = runner.verify(
                run_id=self.run_id,
                command_id="unit-final",
                phase="branch_final",
                input_digest="immutable",
                mutable_input_policy="immutable",
                cwd=self.repo,
                argv=argv,
            )

        self.assertFalse(first["reused"])
        self.assertFalse(second["reused"])
        self.assertEqual("dirty_worktree_requires_execution", second["reason"])
        self.assertEqual("xx", counter.read_text(encoding="utf-8"))
        self.assertFalse(
            (self.repo / ".superpowers" / "sdd" / "verification" / "indexes").exists()
        )


class CapabilityTests(unittest.TestCase):
    def test_fingerprint_ignores_incidental_probe_details(self) -> None:
        first = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="unavailable",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"host": "127.0.0.1", "probe_port": "43117"},
        )
        second = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="unavailable",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"host": "127.0.0.1", "probe_port": "58241"},
        )
        self.assertEqual(
            environment_fingerprint([first]),
            environment_fingerprint([second]),
        )

    def test_child_hypothesis_does_not_become_typed_blocker(self) -> None:
        observation = CapabilityObservation(
            capability="product_runtime",
            scope="plan",
            outcome="unavailable",
            reason_code="suspected_environment",
            observed_by="hypothesis",
            stable_details={},
        )
        self.assertEqual([], typed_blockers([observation]))

    def test_parent_observed_unavailable_capability_is_a_blocker(self) -> None:
        observation = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="unavailable",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"host": "127.0.0.1"},
        )
        self.assertEqual("loopback_bind", typed_blockers([observation])[0]["capability"])

    def test_trust_upgrade_does_not_change_environment_fingerprint(self) -> None:
        child = CapabilityObservation(
            "loopback_bind", "workspace", "unavailable", "permission_denied",
            "child_attested", {"host": "127.0.0.1"},
        )
        parent = dataclasses.replace(child, observed_by="parent_observed")
        self.assertEqual(
            environment_fingerprint([child]), environment_fingerprint([parent])
        )
        self.assertEqual([], typed_blockers([child]))
        self.assertEqual(1, len(typed_blockers([parent])))

    def test_fingerprint_is_stable_for_permuted_distinct_observations(self) -> None:
        available = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="available",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"host": "127.0.0.1"},
        )
        unavailable = dataclasses.replace(available, outcome="unavailable")
        self.assertEqual(
            environment_fingerprint([available, unavailable]),
            environment_fingerprint([unavailable, available]),
        )

    def test_validation_accepts_allowlisted_and_incidental_details(self) -> None:
        observation = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="available",
            reason_code="bound",
            observed_by="parent_observed",
            stable_details={"host": "127.0.0.1", "probe_port": "43117"},
        )
        validate_observation(observation)
        self.assertEqual(
            {"host": "127.0.0.1"},
            canonicalize_observation(observation)["stable_details"],
        )

    def test_validation_accepts_safe_declared_detail_values(self) -> None:
        cases = (
            (
                "loopback_bind",
                {"host": "127.0.0.1", "host_family": "ipv4", "sandbox_policy": "workspace-write"},
            ),
            (
                "workspace_write",
                {"filesystem_type": "apfs", "sandbox_policy": "read-only"},
            ),
            ("git", {"version": "2.44.0", "worktree_supported": "true"}),
        )
        for capability, details in cases:
            with self.subTest(capability=capability):
                validate_observation(
                    CapabilityObservation(
                        capability=capability,
                        scope="workspace",
                        outcome="available",
                        reason_code="bound",
                        observed_by="parent_observed",
                        stable_details=details,
                    )
                )

    def test_validation_rejects_unsafe_values_under_allowed_detail_keys(self) -> None:
        cases = (
            ("loopback_bind", {"host": "token=secret-value"}),
            ("loopback_bind", {"sandbox_policy": "permission denied at /tmp/run"}),
            ("workspace_write", {"filesystem_type": "PATH=/private/bin"}),
            ("git", {"version": "git version 2.44.0; cookie=secret"}),
            ("git", {"worktree_supported": "yes, use this token"}),
        )
        for capability, details in cases:
            with self.subTest(capability=capability, details=details):
                with self.assertRaises(ValueError):
                    validate_observation(
                        CapabilityObservation(
                            capability=capability,
                            scope="workspace",
                            outcome="unavailable",
                            reason_code="permission_denied",
                            observed_by="parent_observed",
                            stable_details=details,
                        )
                    )

    def test_validation_rejects_empty_required_fields(self) -> None:
        for field in ("capability", "scope", "reason_code"):
            with self.subTest(field=field):
                values = {
                    "capability": "loopback_bind",
                    "scope": "workspace",
                    "reason_code": "permission_denied",
                }
                values[field] = ""
                with self.assertRaises(ValueError):
                    validate_observation(
                        CapabilityObservation(
                            outcome="unavailable",
                            observed_by="parent_observed",
                            stable_details={},
                            **values,
                        )
                    )

    def test_validation_rejects_unstable_reason_codes(self) -> None:
        for reason_code in (
            "permission denied: /tmp/runtime",
            "permission_denied_20260717",
            "api_key_sk_live_secret",
        ):
            with self.subTest(reason_code=reason_code):
                observation = CapabilityObservation(
                    capability="loopback_bind",
                    scope="workspace",
                    outcome="unavailable",
                    reason_code=reason_code,
                    observed_by="parent_observed",
                    stable_details={},
                )
                with self.assertRaises(ValueError):
                    validate_observation(observation)

    def test_validation_rejects_unsupported_enum_values(self) -> None:
        observation = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="blocked",  # type: ignore[arg-type]
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={},
        )
        with self.assertRaises(ValueError):
            validate_observation(observation)

    def test_validation_rejects_non_string_detail_keys_or_values(self) -> None:
        for details in ({"host": 127}, {1: "127.0.0.1"}):
            with self.subTest(details=details):
                observation = CapabilityObservation(
                    capability="loopback_bind",
                    scope="workspace",
                    outcome="unavailable",
                    reason_code="permission_denied",
                    observed_by="parent_observed",
                    stable_details=details,  # type: ignore[arg-type]
                )
                with self.assertRaises(ValueError):
                    validate_observation(observation)

    def test_validation_rejects_secret_like_detail_keys(self) -> None:
        observation = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="unavailable",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"api_token": "secret"},
        )
        with self.assertRaises(ValueError):
            validate_observation(observation)

    def test_validation_rejects_unknown_detail_keys(self) -> None:
        observation = CapabilityObservation(
            capability="loopback_bind",
            scope="workspace",
            outcome="unavailable",
            reason_code="permission_denied",
            observed_by="parent_observed",
            stable_details={"raw_environment": "PATH=/bin"},
        )
        with self.assertRaises(ValueError):
            validate_observation(observation)

    def test_blocker_resume_decision_stops_only_unchanged_fingerprints(self) -> None:
        self.assertEqual(
            "stop_unchanged",
            blocker_resume_decision(
                previous_fingerprint="same", current_fingerprint="same"
            ),
        )
        self.assertEqual(
            "launch",
            blocker_resume_decision(
                previous_fingerprint="previous", current_fingerprint="current"
            ),
        )


class WorktreeProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repository"
        self.repo.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "cpe@example.test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "CPE"],
            check=True,
        )
        (self.repo / "seed.txt").write_text("seed", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "seed"], check=True)

    def test_clean_tree_has_canonical_clean_digest(self) -> None:
        observed = observe_worktree_changes(self.repo)
        self.assertEqual((False, None), (observed.changed, observed.reason_code))
        self.assertRegex(observed.digest or "", r"^[0-9a-f]{64}$")
        self.assertEqual(0, observed.regular_file_count)
        self.assertEqual(0, observed.total_bytes)

    def test_tracked_and_untracked_content_change_progress_without_leaking_content(self) -> None:
        tracked = self.repo / "tracked-secret-name.txt"
        tracked.write_text("sensitive-body", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "tracked"], check=True)
        tracked.write_text("changed-sensitive-body", encoding="utf-8")
        (self.repo / "untracked-secret-name.txt").write_text("other-body", encoding="utf-8")
        observed = observe_worktree_changes(self.repo)
        self.assertTrue(observed.changed)
        self.assertRegex(observed.digest or "", r"^[0-9a-f]{64}$")
        serialized = json.dumps(dataclasses.asdict(observed))
        self.assertNotIn("secret-name", serialized)
        self.assertNotIn("sensitive-body", serialized)
        snapshot = ProgressSnapshot("a" * 40, (), None, observed.changed, observed.digest)
        persisted_or_event_payload = json.dumps({
            "progress_fingerprint": progress_fingerprint(snapshot),
            "worktree_changed": snapshot.worktree_changed,
            "worktree_change_digest": snapshot.worktree_change_digest,
        })
        self.assertNotIn("secret-name", persisted_or_event_payload)
        self.assertNotIn("sensitive-body", persisted_or_event_payload)

    def test_deletion_is_a_changed_digest_without_a_file_body(self) -> None:
        (self.repo / "seed.txt").unlink()
        observed = observe_worktree_changes(self.repo)
        self.assertTrue(observed.changed)
        self.assertRegex(observed.digest or "", r"^[0-9a-f]{64}$")
        self.assertEqual(0, observed.regular_file_count)
        self.assertEqual(0, observed.total_bytes)

    def test_symlink_inventory_is_unavailable_without_path_leak(self) -> None:
        secret = self.repo / "symlink-secret-name"
        secret.symlink_to("seed.txt")
        observed = observe_worktree_changes(self.repo)
        self.assertEqual(
            (True, None, "dirty_inventory_unavailable"),
            (observed.changed, observed.digest, observed.reason_code),
        )
        self.assertNotIn("secret-name", json.dumps(dataclasses.asdict(observed)))

    def test_over_limit_or_unreadable_inventory_is_unavailable(self) -> None:
        over_limit = self.repo / "large.txt"
        over_limit.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
        self.assertEqual(
            "dirty_inventory_unavailable",
            observe_worktree_changes(self.repo).reason_code,
        )
        over_limit.unlink()
        unreadable = self.repo / "unreadable.txt"
        unreadable.write_text("body", encoding="utf-8")
        with mock.patch("cpe_runtime.progress.os.open", side_effect=PermissionError):
            observed = observe_worktree_changes(self.repo)
        self.assertEqual("dirty_inventory_unavailable", observed.reason_code)
        with mock.patch(
            "cpe_runtime.progress.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, b"x\0" * 4097),
        ):
            observed = observe_worktree_changes(self.repo)
        self.assertEqual("dirty_inventory_unavailable", observed.reason_code)


class ProgressDecisionTests(unittest.TestCase):
    DEFAULT_BUDGET = CheckpointBudget(
        max_controller_launches=6,
        plan_wall_seconds=7_200,
    )

    def snapshot(self, *, head: str = "abc", completed: tuple[str, ...] = ()) -> ProgressSnapshot:
        return ProgressSnapshot(head, completed, "T3")

    def decide(
        self,
        *,
        previous: ProgressSnapshot | None = None,
        current: ProgressSnapshot | None = None,
        timed_out: bool = True,
        controller_launches: int = 0,
        plan_elapsed_seconds: int = 0,
        child_completed: bool = False,
    ) -> object:
        return decide_checkpoint(
            previous=previous,
            current=current or self.snapshot(),
            timed_out=timed_out,
            controller_launches=controller_launches,
            plan_elapsed_seconds=plan_elapsed_seconds,
            budget=self.DEFAULT_BUDGET,
            child_completed=child_completed,
        )

    def test_child_completed_finishes_before_hard_budgets(self) -> None:
        decision = self.decide(
            controller_launches=6, plan_elapsed_seconds=7_200, child_completed=True,
        )
        self.assertEqual("finish", decision.action)
        self.assertEqual("child_completed", decision.reason_code)

    def test_non_timeout_child_statuses_have_explicit_terminal_actions(self) -> None:
        expected = {
            "checkpointed": ("checkpoint", "child_checkpointed"),
            "failed": ("fail", "child_failed"),
            "blocked": ("block", "child_blocked"),
        }
        for status, outcome in expected.items():
            with self.subTest(status=status):
                decision = decide_child_outcome(
                    previous=self.snapshot(),
                    current=self.snapshot(),
                    timed_out=False,
                    controller_launches=1,
                    plan_elapsed_seconds=1,
                    budget=self.DEFAULT_BUDGET,
                    child_status=status,
                )
                self.assertEqual(outcome, (decision.action, decision.reason_code))

    def test_child_checkpoint_respects_post_slice_hard_budget(self) -> None:
        decision = decide_child_outcome(
            previous=self.snapshot(),
            current=self.snapshot(),
            timed_out=False,
            controller_launches=6,
            plan_elapsed_seconds=1,
            budget=self.DEFAULT_BUDGET,
            child_status="checkpointed",
        )
        self.assertEqual("stop_budget", decision.action)
        self.assertEqual("launch_budget_exhausted", decision.reason_code)

    def test_timed_out_changed_fingerprint_continues_within_budgets(self) -> None:
        decision = self.decide(previous=self.snapshot(head="before"))
        self.assertEqual("continue", decision.action)
        self.assertEqual("productive_timeout", decision.reason_code)

    def test_first_unchanged_timeout_stops_immediately(self) -> None:
        current = self.snapshot()
        decision = self.decide(previous=current)
        self.assertEqual("stop_stalled", decision.action)
        self.assertEqual("no_progress_timeout", decision.reason_code)

    def test_changed_fingerprint_stops_at_launch_budget(self) -> None:
        decision = self.decide(
            previous=self.snapshot(head="before"), controller_launches=6,
        )
        self.assertEqual("stop_budget", decision.action)
        self.assertEqual("launch_budget_exhausted", decision.reason_code)

    def test_changed_fingerprint_stops_at_wall_budget(self) -> None:
        decision = self.decide(
            previous=self.snapshot(head="before"), plan_elapsed_seconds=7_200,
        )
        self.assertEqual("stop_budget", decision.action)
        self.assertEqual("wall_budget_exhausted", decision.reason_code)

    def test_progress_fingerprint_ignores_set_like_ordering(self) -> None:
        left = ProgressSnapshot("abc", ("T2", "T1"), "T3")
        right = ProgressSnapshot("abc", ("T1", "T2"), "T3")
        self.assertEqual(progress_fingerprint(left), progress_fingerprint(right))

    def test_progress_fingerprint_rejects_empty_head(self) -> None:
        with self.assertRaisesRegex(ValueError, "head"):
            progress_fingerprint(self.snapshot(head=""))

    def create_progress_store(self) -> tuple[tempfile.TemporaryDirectory[str], StateStore, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        repository = root / "repository"
        worktree = root / "worktree"
        repository.mkdir()
        worktree.mkdir()
        plan = root / "plan.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        store = StateStore.create(
            run_root=root / "run",
            run_id="progress-snapshot",
            source_repository=repository,
            source_commit="1" * 40,
            worktree=worktree,
            branch="codex/progress-snapshot",
            specs=[],
            plans=[plan],
        )
        return temporary, store, worktree

    def ledger_event(self, event_id: str, category: str, **extra: object) -> dict[str, object]:
        event: dict[str, object] = {
            "schema_version": 1,
            "event_id": event_id,
            "source": "child_attested",
            "plan_id": "plan-01",
            "category": category,
            "action": "recorded",
            "result": "pass",
            "evidence_refs": [],
        }
        event.update(extra)
        return event

    def test_read_progress_snapshot_projects_validated_execution_ledger(self) -> None:
        temporary, store, worktree = self.create_progress_store()
        self.addCleanup(temporary.cleanup)
        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        events = [
            self.ledger_event("task-start-1", "task", action="started", task_id="T1", duration_ms=0),
            self.ledger_event("task-complete-1", "task", action="completed", task_id="T1", duration_ms=1),
            self.ledger_event("task-start-2", "task", action="started", task_id="T2", duration_ms=0),
            self.ledger_event("review-1", "review", action="approved", result="accepted", review_id="R1", artifact_digest="a" * 64, duration_ms=1),
            self.ledger_event("finding-1", "finding_fix", action="resolved", result="closed", finding_ids=["F2", "F1"], fix_digest="b" * 64, duration_ms=1),
        ]
        for event in events:
            append_execution_event(ledger, event)

        snapshot = read_progress_snapshot(store.root, plan_index=0, head="2" * 40)

        self.assertEqual("2" * 40, snapshot.head)
        self.assertEqual(("T1",), snapshot.completed_task_ids)
        self.assertEqual("T2", snapshot.current_task_id)
        self.assertEqual(
            {
                "head", "completed_task_ids", "current_task_id",
                "worktree_changed", "worktree_change_digest",
            },
            set(dataclasses.asdict(snapshot)),
        )

    def test_read_progress_snapshot_rejects_duplicate_ledger_event(self) -> None:
        temporary, store, worktree = self.create_progress_store()
        self.addCleanup(temporary.cleanup)
        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        event = self.ledger_event(
            "task-start-1", "task", action="started", task_id="T1", duration_ms=0,
        )
        ledger.parent.mkdir(parents=True)
        ledger.write_text(
            json.dumps(event) + "\n" + json.dumps(event) + "\n", encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "duplicated"):
            read_progress_snapshot(store.root, plan_index=0, head="2" * 40)

    def test_execution_ledger_schema_matches_runtime_validator_contract(self) -> None:
        schema = json.loads((
            ROOT / "templates" / "execution-ledger.schema.json"
        ).read_text(encoding="utf-8"))
        evidence_module = importlib.import_module("cpe_runtime.evidence")
        self.assertEqual(
            evidence_module._CATEGORIES,
            set(schema["properties"]["category"]["enum"]),
        )
        self.assertEqual(
            evidence_module._ACTIONS,
            set(schema["properties"]["action"]["enum"]),
        )
        self.assertEqual(
            evidence_module._RESULTS,
            set(schema["properties"]["result"]["enum"]),
        )
        self.assertEqual(
            evidence_module._BASE_FIELDS,
            set(schema["required"]),
        )
        self.assertIs(schema["unevaluatedProperties"], False)

        category_branches = {
            branch["if"]["properties"]["category"]["const"]: branch["then"]
            for branch in schema["allOf"]
        }
        self.assertEqual(evidence_module._CATEGORIES, set(category_branches))
        for category, fields in evidence_module._VARIANT_FIELDS.items():
            with self.subTest(category=category):
                branch = category_branches[category]
                if category == "verification":
                    self.assertEqual({"oneOf"}, set(branch))
                    normal, uncached = branch["oneOf"]
                    self.assertEqual(fields, set(normal["required"]))
                    self.assertEqual(fields | {"action"}, set(normal["properties"]))
                    self.assertEqual(
                        fields | evidence_module._UNCACHED_FIELDS,
                        set(uncached["required"]),
                    )
                    self.assertEqual(
                        fields
                        | evidence_module._UNCACHED_FIELDS
                        | {"action", "evidence_refs"},
                        set(uncached["properties"]),
                    )
                    continue
                self.assertEqual({"properties", "required"}, set(branch))
                self.assertEqual(fields, set(branch["required"]))
                self.assertEqual(fields, set(branch["properties"]))
                for field, property_schema in branch["properties"].items():
                    if field == "duration_ms":
                        self.assertEqual(
                            {"type": "integer", "minimum": 0}, property_schema,
                        )
                    elif field == "finding_ids":
                        self.assertEqual("array", property_schema["type"])
                        self.assertEqual(1, property_schema["minItems"])
                        self.assertIs(property_schema["uniqueItems"], True)
                        self.assertEqual(
                            {"type": "string", "pattern": evidence_module._IDENTIFIER.pattern},
                            property_schema["items"],
                        )
                    elif field.endswith("digest") or field in {"argv_digest", "evidence_key"}:
                        self.assertEqual(
                            {"type": "string", "pattern": evidence_module._DIGEST.pattern},
                            property_schema,
                        )
                    else:
                        self.assertEqual(
                            {"type": "string", "pattern": evidence_module._IDENTIFIER.pattern},
                            property_schema,
                        )


class HistoricalEvidenceFixtureTests(unittest.TestCase):
    fixture_root = ROOT / "evals" / "fixtures"
    approved_provenance = {
        "direct_cpe",
        "direct_cpe_format1_forensic",
        "direct_codex_goal_comparative",
        "non_cpe_comparative",
        "sanitized_cpe_observation",
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
            "canvas-format1-token-forensic.json",
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

    def test_format1_forensic_fixture_is_observability_only(self) -> None:
        payload = self.load_fixture("canvas-format1-token-forensic.json")

        self.assertEqual("running", payload["snapshot_state"])
        self.assertFalse(payload["count_as_format2_runtime_metrics"])
        self.assertNotIn("format2_status", payload)
        self.assertNotIn("accepted", payload)
        self.assertNotIn("promotable", payload)

    def test_retry_forensic_fixture_is_advisory_and_content_free(self) -> None:
        payload = self.load_fixture("cpe-2-1-retry-forensic.json")
        observations = {
            item["signal"]: item["occurrences"]
            for item in payload["observations"]
        }

        self.assertEqual(3, observations["unchanged_environment_blocker"])
        self.assertEqual(2, observations["short_empty_result"])
        self.assertEqual(0, 0 if observations["unchanged_environment_blocker"] else 1)
        self.assertEqual(
            "controller_transport_failed",
            launcher_module._controller_outcome(
                spawn_failed=False,
                timed_out=False,
                provider_outcome=None,
                result_present=False,
                returncode=1,
            ),
        )
        self.assertFalse(payload["contains_raw_prompts"])
        self.assertFalse(payload["contains_raw_diffs"])
        self.assertFalse(payload["contains_provider_messages"])
        self.assertNotIn("acceptance", payload)
        self.assertNotIn("accepted", payload)


class OptimizationReportObservabilityTests(unittest.TestCase):
    def test_controller_transport_blocker_retry_and_progress_facts_are_exact(self) -> None:
        report = build_optimization_report(
            run_id="controller-facts",
            events=[
                {
                    "action": "plan.attempt_finished",
                    "source": "parent_observed",
                    "duration_ms": 10,
                    "outcome_code": "provider_usage_blocked",
                    "state_db_warning_count": 4,
                },
                {
                    "action": "plan.attempt_finished",
                    "source": "parent_observed",
                    "duration_ms": 20,
                    "outcome_code": "controller_transport_failed",
                    "state_db_warning_count": 0,
                },
                {
                    "action": "plan.blocked",
                    "source": "parent_observed",
                    "kind": "controller_transport",
                    "environment_fingerprint": None,
                },
                {
                    "action": "resume.stopped_unchanged_blocker",
                    "source": "parent_observed",
                },
                {
                    "action": "run.resumed",
                    "source": "parent_observed",
                    "retry_blocked": True,
                    "retry_failed": False,
                },
                {
                    "action": "plan.continuation_scheduled",
                    "source": "parent_observed",
                    "reason": "productive_timeout",
                },
                {
                    "action": "plan.recovery_stopped",
                    "source": "parent_observed",
                    "reason": "no_progress_timeout",
                },
            ],
            findings=[],
        )

        controller = report["controller"]
        self.assertEqual(2, controller["attempts"])
        self.assertEqual(4, controller["state_db_warning_count"])
        self.assertEqual(1, controller["transport_outcome_counts"]["provider_usage_blocked"])
        self.assertEqual(1, controller["transport_outcome_counts"]["controller_transport_failed"])
        self.assertEqual(0, controller["transport_outcome_counts"]["controller_result_invalid"])
        self.assertEqual({"controller_transport": 1}, controller["blocker_kind_counts"])
        self.assertEqual(0, controller["blocker_fingerprint_available"])
        self.assertEqual(1, controller["unchanged_blocker_stops"])
        self.assertEqual(1, controller["explicit_blocked_retries"])
        self.assertEqual(0, controller["explicit_failed_retries"])
        self.assertEqual(1, controller["progress_continuations"])
        self.assertEqual(1, controller["progress_stops"])

    def test_usage_fields_are_independently_complete_and_missing_is_not_zero(self) -> None:
        report = build_optimization_report(
            run_id="field-complete-usage",
            events=[
                {
                    "action": "plan.attempt_finished",
                    "source": "parent_observed",
                    "duration_ms": 100,
                    "timed_out": False,
                    "returncode": 0,
                    "input_tokens": 100,
                    "cached_input_tokens": 75,
                    "output_tokens": 9,
                    "reasoning_output_tokens": None,
                    "launcher_prompt_bytes": 80,
                },
                {
                    "action": "plan.attempt_finished",
                    "source": "parent_observed",
                    "duration_ms": 200,
                    "timed_out": True,
                    "returncode": -15,
                    "input_tokens": None,
                    "cached_input_tokens": None,
                    "output_tokens": 4,
                    "reasoning_output_tokens": 2,
                    "launcher_prompt_bytes": 90,
                },
                {
                    "action": "plan.attempt_finished",
                    "source": "parent_observed",
                    "duration_ms": None,
                    "timed_out": False,
                    "returncode": 1,
                    "input_tokens": 50,
                    "cached_input_tokens": None,
                    "output_tokens": None,
                    "reasoning_output_tokens": 1,
                    "launcher_prompt_bytes": None,
                },
            ],
            findings=[],
        )
        usage = report["usage"]

        self.assertEqual(3, usage["attempts_finished"])
        self.assertEqual(0, usage["attempts_fully_observed"])
        self.assertEqual(
            {"observed_tokens": 150, "known_attempts": 2,
             "unknown_attempts": 1, "total_kind": "lower_bound"},
            usage["input"],
        )
        self.assertEqual(
            {"observed_tokens": 75, "known_attempts": 1,
             "unknown_attempts": 2, "total_kind": "lower_bound"},
            usage["cached_input"],
        )
        self.assertEqual(25, usage["uncached_input"]["observed_tokens"])
        self.assertEqual(1, usage["uncached_input"]["known_attempts"])
        self.assertEqual(2, usage["uncached_input"]["unknown_attempts"])
        self.assertEqual("input_minus_cached_per_attempt", usage["uncached_input"]["derivation"])
        self.assertEqual(13, usage["output"]["observed_tokens"])
        self.assertEqual(3, usage["reasoning_output"]["observed_tokens"])
        self.assertEqual(200, usage["unknown_attempt_duration_ms"])
        self.assertEqual(0, usage["unknown_attempt_missing_duration_count"])
        self.assertEqual({"timeout": 1}, usage["unknown_attempts_by_reason"])
        self.assertEqual("controller_and_nested_agents_aggregate", usage["scope"])
        self.assertEqual("unavailable", usage["attribution"])
        self.assertEqual("provider_event_not_agent_scoped", usage["attribution_unavailable_reason"])
        self.assertEqual(300, report["duration_ms"])
        self.assertEqual(1, report["duration_unknown_attempt_count"])

    def test_invalid_usage_values_cannot_inflate_totals_or_fabricate_uncached(self) -> None:
        too_large = 2**63
        report = build_optimization_report(
            run_id="invalid-usage",
            events=[
                {
                    "action": "plan.attempt_finished",
                    "source": "parent_observed",
                    "duration_ms": True,
                    "timed_out": False,
                    "returncode": 0,
                    "input_tokens": 10,
                    "cached_input_tokens": 11,
                    "output_tokens": -1,
                    "reasoning_output_tokens": True,
                    "launcher_prompt_bytes": too_large,
                },
                {
                    "action": "plan.attempt_finished",
                    "source": "parent_observed",
                    "duration_ms": -1,
                    "timed_out": False,
                    "returncode": 0,
                    "input_tokens": too_large,
                    "cached_input_tokens": 2,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 4,
                    "launcher_prompt_bytes": 5,
                },
            ],
            findings=[],
        )
        usage = report["usage"]

        self.assertEqual(10, usage["input"]["observed_tokens"])
        self.assertEqual(2, usage["cached_input"]["observed_tokens"])
        self.assertEqual(0, usage["uncached_input"]["observed_tokens"])
        self.assertEqual(0, usage["uncached_input"]["known_attempts"])
        self.assertEqual(2, usage["uncached_input"]["unknown_attempts"])
        self.assertEqual(3, usage["output"]["observed_tokens"])
        self.assertEqual(4, usage["reasoning_output"]["observed_tokens"])
        self.assertEqual(5, usage["launcher_prompt"]["observed_bytes"])
        self.assertEqual(2, report["duration_unknown_attempt_count"])
        self.assertGreaterEqual(len(report["data_quality_warnings"]), 5)

    def test_verification_counts_come_from_parent_ingested_events(self) -> None:
        report = build_optimization_report(
            run_id="verification-counts",
            events=[
                {"action": "verification.evidence_ingested", "source": "parent_observed", "decision": "executed", "child_event_id": "a", "requested_phase": "task", "executed_phase": "task", "avoided_executions": 0},
                {"action": "verification.evidence_ingested", "source": "parent_observed", "decision": "reused", "child_event_id": "b", "requested_phase": "branch_final", "executed_phase": "task", "avoided_executions": 1},
                {"action": "verification.evidence_ingested", "source": "parent_observed", "decision": "executed_uncached", "child_event_id": "c", "requested_phase": "affected", "executed_phase": "affected", "avoided_executions": 0},
                {"action": "verified", "decision": "reused", "source": "child_attested"},
            ],
            findings=[],
        )

        self.assertEqual(
            {
                "requests": 3,
                "executions": 2,
                "reuses": 1,
                "uncached_executions": 1,
                "avoided_executions": 1,
                "requested_phase_counts": {"task": 1, "affected": 1, "branch_final": 1},
                "executed_phase_counts": {"task": 1, "affected": 1, "branch_final": 0},
            },
            report["verification"],
        )

    def test_verification_counts_ignore_incomplete_observations(self) -> None:
        report = build_optimization_report(
            run_id="verification-missing-counts",
            events=[
                {"action": "verification.evidence_ingested", "source": "parent_observed", "decision": "reused", "child_event_id": "missing"},
            ],
            findings=[],
        )

        self.assertEqual(0, report["verification"]["requests"])
        self.assertEqual(0, report["verification"]["avoided_executions"])

    def test_usage_excludes_non_parent_attempt_events(self) -> None:
        report = build_optimization_report(
            run_id="parent-attempts-only",
            events=[
                {
                    "action": "plan.attempt_finished",
                    "source": "parent_observed",
                    "duration_ms": 10,
                    "input_tokens": 7,
                    "cached_input_tokens": 5,
                    "output_tokens": 2,
                    "reasoning_output_tokens": 1,
                    "launcher_prompt_bytes": 3,
                },
                {
                    "action": "plan.attempt_finished",
                    "source": "child_attested",
                    "duration_ms": 1000,
                    "input_tokens": 900,
                    "cached_input_tokens": 800,
                    "output_tokens": 90,
                    "reasoning_output_tokens": 80,
                    "launcher_prompt_bytes": 70,
                },
                {
                    "action": "plan.attempt_finished",
                    "source": "derived",
                    "duration_ms": 2000,
                    "input_tokens": 1900,
                    "cached_input_tokens": 1800,
                    "output_tokens": 190,
                    "reasoning_output_tokens": 180,
                    "launcher_prompt_bytes": 170,
                },
            ],
            findings=[],
        )

        self.assertEqual(1, report["usage"]["attempts_finished"])
        self.assertEqual(7, report["usage"]["input"]["observed_tokens"])
        self.assertEqual(10, report["duration_ms"])

    def test_markdown_renders_all_bounded_observability_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".superpowers" / "sdd"
            root.mkdir(parents=True)
            (root / "task.diff").write_bytes(b"x" * 12)
            report = build_optimization_report(
                run_id="markdown-facts",
                events=[
                    {
                        "action": "plan.attempt_finished",
                        "source": "parent_observed",
                        "duration_ms": 25,
                        "timed_out": True,
                        "returncode": -15,
                        "input_tokens": None,
                        "cached_input_tokens": None,
                        "output_tokens": 3,
                        "reasoning_output_tokens": None,
                        "launcher_prompt_bytes": 9,
                    }
                ],
                findings=[],
                sdd_root=root,
            )
        markdown = render_optimization_markdown(report)

        for expected in (
            "Input (lower_bound): 0 observed tokens; 0 known; 1 unknown.",
            "Cached input (lower_bound): 0 observed tokens; 0 known; 1 unknown.",
            "Paired uncached input (lower_bound): 0 observed tokens; 0 known; 1 unknown.",
            "Output (exact): 3 observed tokens; 1 known; 0 unknown.",
            "Reasoning output (lower_bound): 0 observed tokens; 0 known; 1 unknown.",
            "Launcher prompt (exact): 9 observed bytes; 1 known; 0 unknown.",
            "Paired cache ratio: unavailable.",
            'Unknown-usage reasons: {"timeout":1}.',
            'Artifact classes: {"review_diff":{"bytes":12,"files":1}}.',
            "Review-diff pressure: 1 files, 12 bytes, largest 12 bytes.",
            "Largest artifact: task.diff (12 bytes, review_diff).",
            "Inventory truncated: false.",
            "Declared context: unavailable (not_directly_evidenced); refs=null, bytes=null.",
            "Data quality warnings:",
            "attempt 1 input_tokens is unavailable",
        ):
            self.assertIn(expected, markdown)
        self.assertNotIn("xxxxxxxxxxxx", markdown)

    def test_schema_and_runtime_report_shapes_stay_in_parity(self) -> None:
        schema = json.loads(
            (ROOT / "templates" / "optimization-report.schema.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            available_root = Path(temporary) / ".superpowers" / "sdd"
            available_root.mkdir(parents=True)
            available = build_optimization_report(
                run_id="schema-available",
                events=[],
                findings=[],
                sdd_root=available_root,
            )
        unavailable = build_optimization_report(
            run_id="schema-unavailable", events=[], findings=[]
        )

        self.assertEqual(set(schema["required"]), set(available))
        for field in (
            "usage", "controller", "verification", "artifact_inventory",
            "recovery_metrics",
        ):
            self.assertEqual(
                set(schema["properties"][field]["required"]),
                set(available[field]),
            )
        self.assertEqual(
            MAX_OBSERVED_COUNTER, schema["$defs"]["counter"]["maximum"]
        )
        self.assertEqual(
            {"$ref": "#/$defs/counter"},
            schema["$defs"]["nullableCounter"]["oneOf"][0],
        )
        inventory_schema = schema["properties"]["artifact_inventory"]
        self.assertEqual(2, len(inventory_schema["allOf"]))
        self.assertEqual("available", available["artifact_inventory"]["availability"])
        self.assertIsInstance(available["artifact_inventory"]["produced_files"], int)
        self.assertEqual("unavailable", unavailable["artifact_inventory"]["availability"])
        self.assertIsNone(unavailable["artifact_inventory"]["produced_files"])
        self.assertIsNone(unavailable["artifact_inventory"]["review_diff_pressure"]["bytes"])

    def test_artifact_inventory_is_metadata_only_and_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".superpowers" / "sdd"
            (root / "reviews").mkdir(parents=True)
            (root / "reviews" / "task.diff").write_bytes(b"diff-body" * 10)
            (root / "task-review.md").write_text("review body", encoding="utf-8")
            (root / "progress.md").write_text("progress", encoding="utf-8")

            report = build_optimization_report(
                run_id="artifact-inventory", events=[], findings=[], sdd_root=root,
            )
        inventory = report["artifact_inventory"]

        self.assertEqual("available", inventory["availability"])
        self.assertEqual("produced_filesystem_metadata_only", inventory["measurement_kind"])
        self.assertTrue(inventory["advisory_only"])
        self.assertFalse(inventory["acceptance_effect"])
        self.assertEqual(3, inventory["produced_files"])
        self.assertEqual(1, inventory["review_diff_pressure"]["files"])
        self.assertEqual(90, inventory["review_diff_pressure"]["bytes"])
        self.assertEqual("reviews/task.diff", inventory["largest"]["relative_path"])
        self.assertNotIn("body", json.dumps(inventory))
        self.assertEqual(
            {"status": "unavailable", "refs": None, "bytes": None,
             "reason": "not_directly_evidenced"},
            inventory["declared_context"],
        )

    def test_missing_artifact_root_stays_unavailable_not_zero(self) -> None:
        report = build_optimization_report(
            run_id="artifact-unavailable",
            events=[],
            findings=[],
            sdd_root=Path("/definitely/not/a/cpe/sdd/root"),
        )

        inventory = report["artifact_inventory"]
        self.assertEqual("unavailable", inventory["availability"])
        self.assertIsNone(inventory["produced_files"])
        self.assertIsNone(inventory["produced_bytes"])


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def structured_launch_kwargs(request: StructuredLaunchRequest) -> dict[str, object]:
    def prompt_value(name: str) -> str:
        prefix = f"{name}: "
        return next(
            line.removeprefix(prefix)
            for line in request.prompt.splitlines()
            if line.startswith(prefix)
        )

    recovery = next(
        (
            line.removeprefix("RECOVERY_CAPSULE: ")
            for line in request.prompt.splitlines()
            if line.startswith("RECOVERY_CAPSULE: ")
        ),
        None,
    )
    return {
        "worktree": request.cwd,
        "plan_id": prompt_value("PLAN_ID"),
        "current_commit": prompt_value("CURRENT_COMMIT"),
        "starting_commit": prompt_value("STARTING_COMMIT"),
        "result_path": request.result_path,
        "log_path": request.log_path,
        "recovery_path": Path(recovery) if recovery is not None else None,
    }


def controller_side_effect(
    launcher: CodexLauncher,
    callback: object,
):
    real = getattr(
        launcher,
        "_cpe_test_real_structured",
        launcher._launch_structured,
    )
    launcher._cpe_test_real_structured = real  # type: ignore[attr-defined]

    def dispatch(request: StructuredLaunchRequest, lock_fd: int) -> LaunchResult:
        if "PLAN_ID: " not in request.prompt:
            return real(request, lock_fd)
        return callback(request, lock_fd)  # type: ignore[operator]

    return dispatch


class FailingCreateRunner(SequentialRunner):
    fail_worktree_creation = True

    def _add_new_worktree(self, store: StateStore) -> None:
        if self.fail_worktree_creation:
            raise subprocess.CalledProcessError(128, ["git", "worktree", "add"])
        super()._add_new_worktree(store)


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

    def test_run_launches_controller_directly_without_compiler_artifacts(self) -> None:
        result = self.runner().run(
            workspace=self.repo,
            specs=[self.specs[0]],
            plans=[self.plan(1, "completed")],
            run_id="direct",
        )

        self.assertEqual("completed", result["status"])
        root = self.home / "orchestrator" / "direct"
        self.assertEqual(1, fake_codex_launch_count(root))
        self.assertFalse((root / ("compiled" + "-run-index.json")).exists())
        self.assertFalse((root / "operator-contract.json").exists())

    def test_report_marks_missing_usage_as_lower_bound(self) -> None:
        report = build_optimization_report(
            run_id="report-lower-bound",
            events=[
                {"action": "plan.attempt_finished", "source": "parent_observed", "duration_ms": 1000, "input_tokens": 41},
                {"action": "plan.attempt_finished", "source": "parent_observed", "duration_ms": 2000, "input_tokens": None},
            ],
            findings=[{
                "signal": "timeout",
                "source": "derived",
                "evidence_refs": ["events.jsonl:2"],
            }],
        )
        self.assertEqual(report["usage"]["input"]["observed_tokens"], 41)
        self.assertEqual(report["usage"]["input"]["unknown_attempts"], 1)
        self.assertEqual(report["usage"]["input"]["total_kind"], "lower_bound")
        self.assertEqual(report["findings"][0]["source"], "derived")

    def test_report_rejects_missing_or_invalid_trust_source(self) -> None:
        for source in (None, "trusted_by_default"):
            finding = {
                "signal": "timeout",
                "evidence_refs": ["events.jsonl:2"],
            }
            if source is not None:
                finding["source"] = source
            with self.subTest(source=source), self.assertRaisesRegex(
                ValueError, "trust source"
            ):
                build_optimization_report(
                    run_id="invalid-trust",
                    events=[],
                    findings=[finding],
                )

    def test_report_rejects_unsafe_evidence_references(self) -> None:
        for reference in ("../events.jsonl", "/tmp/evidence", "receipts\\escape"):
            with self.subTest(reference=reference), self.assertRaisesRegex(
                ValueError, "evidence reference"
            ):
                build_optimization_report(
                    run_id="unsafe-reference",
                    events=[],
                    findings=[{
                        "signal": "timeout",
                        "source": "derived",
                        "evidence_refs": [reference],
                    }],
                )

    def test_run_prepares_index_before_worktree_and_reports_after_plan(self) -> None:
        result = self.runner().run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="prepared-run",
        )
        root = self.home / "orchestrator" / "prepared-run"
        self.assertEqual(result["status"], "completed")
        self.assertFalse((root / ("compiled" + "-run-index.json")).exists())
        self.assertTrue((root / "evidence" / "plan-01" / "evidence-manifest.json").is_file())
        self.assertTrue((root / "reports" / "optimization-report.json").is_file())

    def test_format_three_persists_immutable_runtime_config(self) -> None:
        store = StateStore.create(
            run_root=self.home / "orchestrator" / "format-three",
            run_id="format-three",
            source_repository=self.repo,
            source_commit=git(self.repo, "rev-parse", "HEAD"),
            worktree=self.home / "worktrees" / "format-three",
            branch="codex/format-three",
            specs=[],
            plans=[self.plan(1, "completed")],
            sandbox_mode="workspace-write",
            controller_slice_seconds=1800,
        )
        self.assertEqual(3, store.state["format_version"])
        self.assertEqual(
            {
                "sandbox_mode": "workspace-write",
                "controller_slice_seconds": 1800,
            },
            store.state["run_config"],
        )
        self.assertEqual(6, store.state["plans"][0]["budget"]["max_controller_launches"])
        self.assertEqual(7200, store.state["plans"][0]["budget"]["plan_wall_budget_seconds"])

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
        before = store.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, message):
            store.save()
        self.assertEqual(before, store.state_path.read_bytes())

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
                "plan_wall_budget_seconds": 7200,
                "max_controller_launches": 6,
            },
        )
        self.assertIsNone(store.state["plans"][0]["progress_fingerprint"])
        self.assertIsNone(store.state["plans"][0]["environment_fingerprint"])
        self.assertEqual(store.state["plans"][0]["plan_elapsed_seconds"], 0)
        self.assertTrue((store.root / "evidence").is_dir())
        self.assertTrue((store.root / "reports").is_dir())

    def execution_event(self, category: str, **extra: object) -> dict[str, object]:
        event: dict[str, object] = {
            "schema_version": 1,
            "event_id": f"event-{category}",
            "source": "child_attested",
            "plan_id": "plan-01",
            "category": category,
            "action": "recorded",
            "result": "pass",
            "evidence_refs": [],
        }
        event.update({
            "task": {"task_id": "task-01", "duration_ms": 0},
            "review": {"review_id": "review-01", "artifact_digest": "a" * 64, "duration_ms": 0},
            "finding_fix": {"finding_ids": ["finding-01"], "fix_digest": "a" * 64, "duration_ms": 0},
            "verification": {"command_id": "command-01", "argv_digest": "a" * 64, "evidence_key": "b" * 64, "duration_ms": 0, "requested_phase": "task", "executed_phase": "task", "avoided_executions": 0},
            "capability": {"capability_id": "capability-01", "capability_digest": "a" * 64},
            "checkpoint": {"checkpoint_id": "checkpoint-01", "checkpoint_digest": "a" * 64},
            "blocker": {"blocker_id": "blocker-01", "blocker_digest": "a" * 64},
            "obligation": {"obligation_id": "obligation-01", "obligation_digest": "a" * 64},
            "coordination": {"coordination_id": "coordination-01", "coordination_digest": "a" * 64, "duration_ms": 0},
        }.get(category, {}))
        event.update(extra)
        return event

    def write_execution_ledger(
        self, worktree: Path, events: list[dict[str, object]]
    ) -> Path:
        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        for event in events:
            append_execution_event(ledger, event)
        return ledger

    def test_plan_evidence_survives_worktree_removal(self) -> None:
        worktree = self.root / "evidence-worktree"
        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        append_execution_event(
            ledger,
            {
                "event_id": "event-1",
                "source": "child_attested",
                "plan_id": "plan-01",
                "category": "task",
                "action": "completed",
                "result": "pass",
                "evidence_refs": [],
                "task_id": "task-01",
                "duration_ms": 1,
            },
        )
        manifest = ingest_plan_evidence(
            run_root=self.root / "run",
            worktree=worktree,
            plan_id="plan-01",
            accepted_head="1" * 40,
        )
        shutil.rmtree(worktree)
        archived = self.root / "run" / "evidence" / "plan-01"
        self.assertEqual(manifest["accepted_head"], "1" * 40)
        self.assertTrue((archived / "execution-ledger.jsonl").is_file())
        self.assertEqual(
            (archived / "execution-ledger.jsonl").stat().st_mode & 0o777, 0o400
        )

    def test_execution_ledger_accepts_each_category_and_rejects_bad_schema(self) -> None:
        categories = (
            "task", "review", "finding_fix", "verification", "capability",
            "checkpoint", "blocker", "obligation", "coordination",
        )
        worktree = self.root / "ledger-schema"
        ledger = self.write_execution_ledger(
            worktree, [self.execution_event(category) for category in categories]
        )
        self.assertEqual(len(validate_execution_ledger(ledger, expected_plan_id="plan-01")), 9)

        invalid_events = [
            self.execution_event("unknown"),
            self.execution_event("task", action="unknown"),
            self.execution_event("task", surprise=True),
            self.execution_event("task", source="untrusted"),
            self.execution_event("task", evidence_refs=["/absolute"]),
            self.execution_event("task", evidence_refs=["../escape"]),
            self.execution_event("task", source="parent_observed"),
        ]
        for index, event in enumerate(invalid_events):
            with self.subTest(index=index):
                bad = worktree / f"bad-{index}.jsonl"
                bad.write_text(json.dumps(event) + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    validate_execution_ledger(bad, expected_plan_id="plan-01")

        duplicate = worktree / "duplicate.jsonl"
        event = self.execution_event("task")
        duplicate.write_text(
            json.dumps(event) + "\n" + json.dumps(event) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "duplicated"):
            validate_execution_ledger(duplicate, expected_plan_id="plan-01")

    def test_evidence_rejects_symlinks_limits_and_cleans_partial_target(self) -> None:
        cases: list[tuple[str, list[tuple[str, bytes]], str]] = [
            ("too-many", [(f"file-{i}", b"x") for i in range(128)], "file count"),
            ("too-large", [("large", b"x" * (MAX_EVIDENCE_FILE_BYTES + 1))], "size limit"),
            ("aggregate", [(f"chunk-{i}", b"x" * MAX_EVIDENCE_FILE_BYTES) for i in range(9)], "bundle"),
        ]
        for name, files, message in cases:
            with self.subTest(name=name):
                worktree = self.root / f"evidence-{name}"
                sdd = worktree / ".superpowers" / "sdd"
                sdd.mkdir(parents=True)
                refs = []
                for filename, payload in files:
                    (sdd / filename).write_bytes(payload)
                    refs.append(filename)
                self.write_execution_ledger(worktree, [self.execution_event("task", evidence_refs=refs)])
                run_root = self.root / f"run-{name}"
                with self.assertRaisesRegex(ValueError, message):
                    ingest_plan_evidence(run_root=run_root, worktree=worktree, plan_id="plan-01", accepted_head="1" * 40)
                self.assertFalse((run_root / "evidence" / "plan-01").exists())

        worktree = self.root / "evidence-symlink"
        sdd = worktree / ".superpowers" / "sdd"
        sdd.mkdir(parents=True)
        real = sdd / "real-ledger"
        real.write_text(json.dumps(self.execution_event("task")) + "\n", encoding="utf-8")
        (sdd / "execution-ledger.jsonl").symlink_to(real)
        with self.assertRaisesRegex(ValueError, "redirected"):
            ingest_plan_evidence(run_root=self.root / "run-symlink", worktree=worktree, plan_id="plan-01", accepted_head="1" * 40)

    def test_evidence_publication_fsync_failure_cleans_target_and_allows_retry(self) -> None:
        worktree = self.root / "evidence-publication-fsync"
        self.write_execution_ledger(worktree, [self.execution_event("task")])
        run_root = self.root / "run-publication-fsync"
        evidence_root = run_root / "evidence"
        evidence_module = importlib.import_module("cpe_runtime.evidence")
        original_fsync_directory = evidence_module._fsync_directory
        injected = False

        def fail_published_parent_once(path: Path) -> None:
            nonlocal injected
            if path == evidence_root and not injected:
                injected = True
                raise OSError("injected publication fsync failure")
            original_fsync_directory(path)

        with mock.patch.object(
            evidence_module, "_fsync_directory", side_effect=fail_published_parent_once
        ):
            with self.assertRaisesRegex(OSError, "injected publication fsync failure"):
                ingest_plan_evidence(
                    run_root=run_root,
                    worktree=worktree,
                    plan_id="plan-01",
                    accepted_head="1" * 40,
                )

        self.assertTrue(injected)
        self.assertFalse((evidence_root / "plan-01").exists())
        manifest = ingest_plan_evidence(
            run_root=run_root,
            worktree=worktree,
            plan_id="plan-01",
            accepted_head="1" * 40,
        )
        self.assertEqual(manifest["plan_id"], "plan-01")

    def test_identical_sealed_evidence_publication_is_idempotent(self) -> None:
        worktree = self.root / "evidence-idempotent"
        self.write_execution_ledger(worktree, [self.execution_event("task")])
        run_root = self.root / "run-evidence-idempotent"

        first = ingest_plan_evidence(
            run_root=run_root,
            worktree=worktree,
            plan_id="plan-01",
            accepted_head="1" * 40,
        )
        second = ingest_plan_evidence(
            run_root=run_root,
            worktree=worktree,
            plan_id="plan-01",
            accepted_head="1" * 40,
        )

        self.assertEqual(first, second)
        self.assertEqual(1, len(list((run_root / "evidence").iterdir())))

    def test_mismatched_existing_evidence_fails_closed_without_deletion(self) -> None:
        worktree = self.root / "evidence-mismatch"
        self.write_execution_ledger(worktree, [self.execution_event("task")])
        run_root = self.root / "run-evidence-mismatch"
        ingest_plan_evidence(
            run_root=run_root,
            worktree=worktree,
            plan_id="plan-01",
            accepted_head="1" * 40,
        )
        target = run_root / "evidence" / "plan-01"
        sealed_ledger = target / "execution-ledger.jsonl"
        sealed_ledger.chmod(0o600)
        sealed_ledger.write_text("tampered\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "sealed evidence target does not match"):
            ingest_plan_evidence(
                run_root=run_root,
                worktree=worktree,
                plan_id="plan-01",
                accepted_head="1" * 40,
            )

        self.assertTrue(target.is_dir())
        self.assertEqual("tampered\n", sealed_ledger.read_text(encoding="utf-8"))

    def test_evidence_mode_is_durable_before_each_final_file_fsync(self) -> None:
        worktree = self.root / "evidence-mode-order"
        self.write_execution_ledger(worktree, [
            self.execution_event("task", evidence_refs=["receipt.txt"]),
        ])
        source = worktree / ".superpowers" / "sdd"
        (source / "receipt.txt").write_text("receipt\n", encoding="utf-8")
        run_root = self.root / "run-evidence-mode-order"
        calls: list[tuple[str, int, int]] = []
        real_fchmod = os.fchmod
        real_fsync = os.fsync

        def record_fchmod(descriptor: int, mode: int) -> None:
            real_fchmod(descriptor, mode)
            metadata = os.fstat(descriptor)
            calls.append(("fchmod", metadata.st_ino, stat.S_IMODE(metadata.st_mode)))

        def record_fsync(descriptor: int) -> None:
            metadata = os.fstat(descriptor)
            if stat.S_ISREG(metadata.st_mode):
                calls.append(("fsync", metadata.st_ino, stat.S_IMODE(metadata.st_mode)))
            real_fsync(descriptor)

        with (
            mock.patch("cpe_runtime.evidence.os.fchmod", side_effect=record_fchmod),
            mock.patch("cpe_runtime.evidence.os.fsync", side_effect=record_fsync),
        ):
            ingest_plan_evidence(
                run_root=run_root,
                worktree=worktree,
                plan_id="plan-01",
                accepted_head="1" * 40,
            )

        target = run_root / "evidence" / "plan-01"
        published = [path for path in target.rglob("*") if path.is_file()]
        self.assertEqual(3, len(published))
        for path in published:
            inode = path.stat().st_ino
            inode_calls = [call for call in calls if call[1] == inode]
            chmod_positions = [
                index for index, call in enumerate(inode_calls)
                if call == ("fchmod", inode, 0o400)
            ]
            fsync_positions = [
                index for index, call in enumerate(inode_calls)
                if call == ("fsync", inode, 0o400)
            ]
            self.assertTrue(chmod_positions, path)
            self.assertTrue(fsync_positions, path)
            self.assertLess(chmod_positions[-1], fsync_positions[-1], path)

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

        self.assertEqual(result["status"], "failed")
        self.assertIsNone(inspected["observed_head"])
        self.assertEqual(inspected["last_known_head"], second_head)

    def test_timeout_persists_advanced_head_and_stops_on_first_stalled_slice(self) -> None:
        runner = self.runner(timeout_seconds=1.0)
        real_launch = runner.launcher._launch_structured
        observed_timeouts: list[float] = []

        def accelerated(
            request: StructuredLaunchRequest, lock_fd: int,
        ) -> LaunchResult:
            if "PLAN_ID: " in request.prompt:
                observed_timeouts.append(request.timeout_seconds)
                request = dataclasses.replace(request, timeout_seconds=0.12)
            return real_launch(request, lock_fd)

        runner.launcher._launch_structured = mock.Mock(side_effect=accelerated)
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

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["last_decision_reason"], "no_progress_timeout")
        self.assertIsNone(inspected["observed_head"])
        self.assertEqual(inspected["last_known_head"], advanced_head)
        self.assertEqual(len(self.invocations()), 3)
        self.assertEqual(observed_timeouts, [3600.0, 3600.0, 3600.0])

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

    def test_worktree_creation_blocker_is_durable_and_plain_resume_recovers(self) -> None:
        runner = FailingCreateRunner(
            codex_home=self.home,
            launcher=self.runner().launcher,
        )
        run_root = self.home / "orchestrator" / "create-failure"
        worktree = self.home / "worktrees" / "create-failure"
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="create-failure",
        )
        self.assertEqual(result["status"], "blocked")
        blocked_bytes = (run_root / "state.json").read_bytes()
        state = StateStore.open(run_root).state
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["plans"][0]["status"], "blocked")
        self.assertEqual(state["plans"][0]["attempt_count"], 0)
        self.assertEqual(state["plans"][0]["controller_launch_count"], 0)
        self.assertEqual(state["pre_execution_blocker"], {
            "code": "worktree_creation_failed",
            "kind": "verification_environment",
            "operation": "create_or_reconcile_worktree",
            "owner": "operator",
        })
        self.assertFalse(worktree.exists())

        inspected = runner.inspect(run_id="create-failure")

        self.assertEqual(inspected["status"], "blocked")
        self.assertEqual(inspected["last_decision_reason"], "worktree_creation_failed")
        self.assertEqual(blocked_bytes, (run_root / "state.json").read_bytes())

        blocked_again = runner.resume(run_id="create-failure")

        self.assertEqual(blocked_again["status"], "blocked")
        repeated = StateStore.open(run_root).state
        self.assertEqual(repeated["status"], "blocked")
        self.assertEqual(repeated["plans"][0]["status"], "blocked")
        self.assertEqual(repeated["plans"][0]["attempt_count"], 0)
        self.assertEqual(repeated["plans"][0]["controller_launch_count"], 0)
        self.assertFalse(worktree.exists())
        blocked_events = [
            event for event in _runner_events(run_root)
            if event.get("action") == "run.worktree_creation_blocked"
        ]
        self.assertEqual(len(blocked_events), 2)
        self.assertTrue(all(
            event.get("source") == "parent_observed"
            and event.get("kind") == "verification_environment"
            and event.get("code") == "worktree_creation_failed"
            and event.get("owner") == "operator"
            for event in blocked_events
        ))

        runner.fail_worktree_creation = False
        completed = runner.resume(run_id="create-failure")

        self.assertEqual(completed["status"], "completed")
        recovered = StateStore.open(run_root).state
        self.assertEqual(recovered["status"], "completed")
        self.assertIsNone(recovered["pre_execution_blocker"])
        self.assertEqual(recovered["plans"][0]["attempt_count"], 1)
        self.assertEqual(recovered["plans"][0]["controller_launch_count"], 1)
        self.assertTrue(worktree.is_dir())

    def test_pre_execution_worktree_blocker_rejects_impossible_state_without_persisting(self) -> None:
        blocker = {
            "code": "worktree_creation_failed",
            "kind": "verification_environment",
            "operation": "create_or_reconcile_worktree",
            "owner": "operator",
        }

        def change_blocker(field: str, value: str):
            def mutate(store: StateStore) -> None:
                store.state["pre_execution_blocker"] = {**blocker, field: value}
            return mutate

        def change_run_status(store: StateStore) -> None:
            store.state["status"] = "failed"

        def change_current_status(store: StateStore) -> None:
            store.state["plans"][0]["status"] = "failed"

        def set_current_counter(field: str):
            def mutate(store: StateStore) -> None:
                store.state["plans"][0][field] = 1
            return mutate

            digest = field.replace("_path", "_sha256")

            def mutate(store: StateStore) -> None:
                store.state[field] = None
                store.state[digest] = None

            return mutate

        def advance_current_index(store: StateStore) -> None:
            store.state["current_plan_index"] = 1

        def complete_while_retaining_blocker(store: StateStore) -> None:
            result_path = store.root / "results" / "completed-with-blocker.json"
            result_path.write_text("{}", encoding="utf-8")
            result_path.chmod(0o600)
            plan = store.state["plans"][0]
            plan.update(
                status="completed",
                starting_commit=store.state["source_commit"],
                accepted_commit=store.state["source_commit"],
                attempt_count=1,
                result_path=str(result_path.resolve()),
            )
            store.state["current_plan_index"] = 1
            store.state["status"] = "completed"

        def block_future_plan(store: StateStore) -> None:
            store.state["plans"][1]["status"] = "blocked"

        cases = (
            ("wrong-kind", 1, change_blocker("kind", "runtime_integrity"), "pre-execution blocker is invalid"),
            ("wrong-operation", 1, change_blocker("operation", "verify_worktree"), "pre-execution blocker is invalid"),
            ("wrong-owner", 1, change_blocker("owner", "controller"), "pre-execution blocker is invalid"),
            ("wrong-reason", 1, change_blocker("code", "worktree_missing"), "pre-execution blocker is invalid"),
            ("run-not-blocked", 1, change_run_status, "pre-execution blocker state is invalid"),
            ("current-not-blocked", 1, change_current_status, "pre-execution blocker state is invalid"),
            ("attempt-present", 1, set_current_counter("attempt_count"), "pre-execution blocker state is invalid"),
            ("launch-present", 1, set_current_counter("controller_launch_count"), "pre-execution blocker state is invalid"),
            ("index-advanced", 1, advance_current_index, "completed prefix"),
            ("completed-retains-blocker", 1, complete_while_retaining_blocker, "completed run cannot retain"),
            ("future-plan-blocked", 2, block_future_plan, "future plan is not pristine"),
        )

        for name, plan_count, mutate, message in cases:
            with self.subTest(case=name):
                runner = FailingCreateRunner(
                    codex_home=self.home,
                    launcher=self.runner().launcher,
                )
                run_id = f"invalid-worktree-blocker-{name}"
                result = runner.run(
                    workspace=self.repo,
                    specs=[],
                    plans=[self.plan(index, "completed") for index in range(1, plan_count + 1)],
                    run_id=run_id,
                )
                self.assertEqual(result["status"], "blocked")
                store = StateStore.open(self.home / "orchestrator" / run_id)
                persisted = store.state_path.read_bytes()

                mutate(store)

                with self.assertRaisesRegex(ValueError, message):
                    store.save()
                self.assertEqual(persisted, store.state_path.read_bytes())

    def test_worktree_creation_blocker_preserves_unowned_path_collision(self) -> None:
        runner = FailingCreateRunner(
            codex_home=self.home,
            launcher=self.runner().launcher,
        )
        run_root = self.home / "orchestrator" / "create-path-collision"
        worktree = self.home / "worktrees" / "create-path-collision"
        blocked = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(1, "completed")],
            run_id="create-path-collision",
        )
        self.assertEqual(blocked["status"], "blocked")
        worktree.mkdir(mode=0o700, parents=True)
        marker = worktree / "unowned.txt"
        marker.write_text("preserve\n", encoding="utf-8")

        blocked_again = runner.resume(run_id="create-path-collision")

        self.assertEqual(blocked_again["status"], "blocked")
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")
        state = StateStore.open(run_root).state
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["plans"][0]["attempt_count"], 0)
        self.assertEqual(state["plans"][0]["controller_launch_count"], 0)

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

        runner.launcher._launch_structured = mock.Mock(
            side_effect=controller_side_effect(
                runner.launcher,
                lambda request, _lock_fd: fail_without_a_process(
                    **structured_launch_kwargs(request)
                ),
            )
        )
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
        runner = SequentialRunner(
            codex_home=self.home,
            launcher=launcher,
        )
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
        command = launcher._command(self.repo, result_path, "danger-full-access")
        restricted = launcher._command(self.repo, result_path, "workspace-write")
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
        self.assertEqual(
            "danger-full-access", command[command.index("--sandbox") + 1],
        )
        self.assertEqual(
            "workspace-write", restricted[restricted.index("--sandbox") + 1],
        )
        self.assertNotIn("REPOSITORY:", prompt)
        self.assertIn("WORKTREE:", prompt)
        self.assertNotIn(
            "Write only the fixed schema result to RESULT_PATH",
            prompt,
        )
        self.assertIn("SPECIFICATIONS:", prompt)
        self.assertIn("Ordinary agents reuse this worktree", prompt)
        for semantic_instruction in (
            "focused RED/GREEN",
            "no automatic full-suite run per task",
            "review-package",
            "one consolidated fix subagent",
            "cross-task final review",
        ):
            self.assertNotIn(semantic_instruction, prompt)
        self.assertIn("same normalized verification command", prompt)
        self.assertIn("workflow_receipt", prompt)
        self.assertLess(len(prompt.encode("utf-8")), 2_400)

    def test_usage_filter_keeps_only_bounded_final_totals(self) -> None:
        capture = _JsonEventFilter()
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

        missing = _JsonEventFilter()
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

        oversized = _JsonEventFilter()
        oversized.feed(b"x" * 70_000 + b"\n")
        oversized.feed(
            b'{"type":"turn.completed","usage":{"input_tokens":3}}\n'
        )
        oversized.finish()
        self.assertEqual(oversized.usage["input_tokens"], 3)

    def test_usage_filter_rejects_unreasonable_integer_totals(self) -> None:
        capture = _JsonEventFilter()
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
            runner.launcher._launch_structured = mock.Mock(
                side_effect=controller_side_effect(
                    runner.launcher,
                    lambda request, _lock_fd, injected=injected: launch_with(
                        injected
                    )(**structured_launch_kwargs(request)),
                )
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
        real_launch = runner.launcher._launch_structured
        launch_plan_ids: list[str] = []

        def complete_first_plan_without_a_process(
            **kwargs: object,
        ) -> LaunchResult:
            plan_id = str(kwargs["plan_id"])
            launch_plan_ids.append(plan_id)
            if plan_id != "plan-01":
                raise AssertionError("real launch must use the structured wrapper")
            worktree = Path(kwargs["worktree"])
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
                "workflow_receipt": workflow_receipt(
                    worktree,
                    str(kwargs["current_commit"]),
                    plan_id,
                ),
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

        def complete_first_or_launch(
            request: StructuredLaunchRequest, lock_fd: int,
        ) -> LaunchResult:
            if "PLAN_ID: " not in request.prompt:
                return real_launch(request, lock_fd)
            kwargs = structured_launch_kwargs(request)
            if kwargs["plan_id"] == "plan-01":
                return complete_first_plan_without_a_process(**kwargs)
            launch_plan_ids.append(str(kwargs["plan_id"]))
            return real_launch(request, lock_fd)

        runner.launcher._launch_structured = mock.Mock(
            side_effect=complete_first_or_launch
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

        runner.launcher._launch_structured = mock.Mock(
            side_effect=controller_side_effect(
                runner.launcher,
                lambda request, _lock_fd: recovery_without_a_process(
                    **structured_launch_kwargs(request)
                ),
            )
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
        self.assertTrue(any(
            event["action"] == "plan.checkpoint_decided"
            and event.get("decision") == "fail"
            for event in events
        ))
        self.assertTrue(any(event["action"] == "plan.failed" for event in events))

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

        runner.launcher._launch_structured = mock.Mock(
            side_effect=controller_side_effect(
                runner.launcher,
                lambda request, _lock_fd: fail_without_a_process(
                    **structured_launch_kwargs(request)
                ),
            )
        )
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


def _runner_events(run_root: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (run_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def fake_codex_launch_count(run_root: Path) -> int:
    events = _runner_events(run_root)
    resumed_at = max(
        (index for index, event in enumerate(events) if event.get("action") == "run.resumed"),
        default=-1,
    )
    return sum(
        event.get("action") == "plan.attempt_started"
        for event in events[resumed_at + 1:]
    )



class _RecoveryRunnerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-recovery-integration-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.repo = self.root / "repo"
        self.home.mkdir(mode=0o700)
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        git(self.repo, "config", "user.email", "cpe@example.invalid")
        git(self.repo, "config", "user.name", "CPE Eval")
        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "fixture base")
        self.fake = self.root / "codex"
        shutil.copyfile(ROOT / "evals" / "fake_codex.py", self.fake)
        self.fake.chmod(0o700)
        self.invocations = self.root / "invocations.jsonl"
        self.captured_timeouts: list[float] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def plan(
        self, scenario: str, *, loopback: bool = False, number: int = 1,
    ) -> Path:
        path = self.repo / f"input-plan-{number}.md"
        suffix = "requires loopback_bind\n" if loopback else ""
        path.write_text(
            f"scenario:{scenario}\n{suffix}plan {number}\n", encoding="utf-8",
        )
        return path

    def runner(
        self, run_id: str, *, accelerated_timeout: float = 0.12,
    ) -> SequentialRunner:
        run_root = self.home / "orchestrator" / run_id
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(self.fake),
            timeout_seconds=accelerated_timeout,
            termination_grace_seconds=0.02,
            environ={
                "PATH": os.environ["PATH"],
                "CODEX_HOME": str(self.home),
                "CPE_FAKE_INVOCATION_LOG": str(self.invocations),
            },
        )
        real_launch = launcher._launch_structured

        def accelerated(request: object, lock_fd: int) -> LaunchResult:
            assert hasattr(request, "timeout_seconds")
            timeout = float(request.timeout_seconds)  # type: ignore[attr-defined]
            if timeout != 300.0:
                self.captured_timeouts.append(timeout)
                request = dataclasses.replace(
                    request, timeout_seconds=accelerated_timeout,
                )
            return real_launch(request, lock_fd)  # type: ignore[arg-type]

        launcher._launch_structured = mock.Mock(side_effect=accelerated)
        return SequentialRunner(codex_home=self.home, launcher=launcher)


class ControllerTransportTests(_RecoveryRunnerFixture):
    def run_scenario(
        self, scenario: str, *, timeout_seconds: float = 1.0,
    ) -> dict[str, object]:
        run_id = f"transport-{scenario.replace('_', '-')}"
        return self.runner(
            run_id, accelerated_timeout=timeout_seconds,
        ).run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan(scenario)],
            run_id=run_id,
        )

    def attempt_event(self, scenario: str) -> dict[str, object]:
        run_id = f"transport-{scenario.replace('_', '-')}"
        return next(
            event
            for event in _runner_events(self.home / "orchestrator" / run_id)
            if event.get("action") == "plan.attempt_finished"
        )

    def test_json_event_filter_keeps_only_usage_and_allowlisted_error_code(self) -> None:
        filter_class = getattr(launcher_module, "_JsonEventFilter", None)
        self.assertIsNotNone(filter_class)
        capture = filter_class()
        capture.feed(
            b'{"type":"item.completed","message":"RAW_PROVIDER_MESSAGE",'
            b'"error":{"code":"rate-limit-exceeded",'
            b'"message":"RAW_NESTED_MESSAGE"}}\n'
            b'{"type":"turn.completed","usage":{"input_tokens":41,'
        )
        capture.feed(
            b'"cached_input_tokens":31,"output_tokens":7,'
            b'"reasoning_output_tokens":5}}\n'
            b'{malformed-json\n'
        )
        capture.feed(
            b'{"error":{"code":"provider-unavailable",'
            b'"message":"' + b'x' * 70_000 + b'"}}\n'
        )
        capture.finish()

        self.assertEqual(
            {
                "input_tokens": 41,
                "cached_input_tokens": 31,
                "output_tokens": 7,
                "reasoning_output_tokens": 5,
            },
            capture.usage,
        )
        self.assertEqual("provider_usage_blocked", capture.provider_outcome)
        self.assertNotIn("RAW_PROVIDER_MESSAGE", repr(vars(capture)))
        self.assertNotIn("RAW_NESTED_MESSAGE", repr(vars(capture)))
        self.assertFalse(hasattr(capture, "events"))

    def test_json_event_filter_ignores_unknown_and_nested_error_codes(self) -> None:
        filter_class = getattr(launcher_module, "_JsonEventFilter", None)
        self.assertIsNotNone(filter_class)
        capture = filter_class()
        capture.feed(
            b'{"error":{"code":"unknown-provider-code",'
            b'"details":{"code":"invalid-api-key"}},'
            b'"message":"RAW_UNKNOWN_MESSAGE"}\n'
        )
        capture.finish()

        self.assertIsNone(capture.provider_outcome)
        self.assertNotIn("RAW_UNKNOWN_MESSAGE", repr(vars(capture)))

    def test_spawn_failure_has_stable_controller_outcome(self) -> None:
        launcher = CodexLauncher(
            schema_path=ROOT / "templates" / "plan-result-schema.json",
            codex_bin=str(self.root / "missing-codex"),
            timeout_seconds=1,
            environ={"PATH": os.environ["PATH"]},
        )
        result = SequentialRunner(
            codex_home=self.home, launcher=launcher,
        ).run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("completed")],
            run_id="transport-spawn-failure",
        )

        self.assertEqual("failed", result["status"])
        self.assertEqual("controller_spawn_failed", result["last_decision_reason"])

    def test_zero_exit_empty_result_is_missing_controller_result(self) -> None:
        result = self.run_scenario("zero_empty_result")

        self.assertEqual("failed", result["status"])
        self.assertEqual("controller_result_missing", result["last_decision_reason"])

    def test_nonzero_empty_result_is_transport_failure_not_invalid_product_result(self) -> None:
        result = self.run_scenario("nonzero_empty_result")

        self.assertEqual("failed", result["status"])
        self.assertEqual(
            "controller_transport_failed", result.get("last_decision_reason"),
        )

    def test_invalid_present_result_remains_runner_owned(self) -> None:
        result = self.run_scenario("invalid_present_result")

        self.assertEqual("failed", result["status"])
        self.assertEqual("controller_result_invalid", result["last_decision_reason"])

    def test_timeout_keeps_progress_decision_and_records_transport_fact(self) -> None:
        result = self.run_scenario(
            "timeout_without_progress", timeout_seconds=0.12,
        )

        self.assertEqual("blocked", result["status"])
        self.assertEqual("no_progress_timeout", result["last_decision_reason"])
        self.assertEqual(
            "controller_timed_out",
            self.attempt_event("timeout_without_progress")["outcome_code"],
        )

    def test_provider_error_codes_block_without_raw_message_retention(self) -> None:
        cases = {
            "provider_usage_blocked": "provider_usage_blocked",
            "provider_auth_blocked": "provider_auth_blocked",
            "provider_unavailable": "provider_unavailable",
        }
        for scenario, expected in cases.items():
            with self.subTest(scenario=scenario):
                result = self.run_scenario(scenario)
                run_root = (
                    self.home / "orchestrator"
                    / f"transport-{scenario.replace('_', '-')}"
                )
                self.assertEqual("blocked", result["status"])
                self.assertEqual(expected, result["last_decision_reason"])
                self.assertNotIn(
                    "RAW_PROVIDER_MESSAGE",
                    (run_root / "events.jsonl").read_text(encoding="utf-8"),
                )
                self.assertNotIn(
                    "RAW_PROVIDER_MESSAGE",
                    next((run_root / "logs").iterdir()).read_text(encoding="utf-8"),
                )

    def test_state_db_warning_count_persists_without_matched_line(self) -> None:
        result = self.run_scenario("state_db_warnings")
        event = self.attempt_event("state_db_warnings")
        run_root = self.home / "orchestrator" / "transport-state-db-warnings"
        report = json.loads(
            (run_root / "reports" / "optimization-report.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual("completed", result["status"])
        self.assertEqual(4, event["state_db_warning_count"])
        self.assertNotIn("state_db_warning_line", event)
        self.assertEqual(4, report["controller"]["state_db_warning_count"])
        self.assertNotIn("database is locked", json.dumps(report))


class ResumeCapabilityTests(_RecoveryRunnerFixture):
    def run_blocked(self, *, resource: str) -> tuple[SequentialRunner, dict[str, object]]:
        plan = self.plan("blocked")
        plan.write_text(
            f"scenario:blocked\nblocker-resource:{resource}\n",
            encoding="utf-8",
        )
        runner = self.runner("resume-capability", accelerated_timeout=1.0)
        return runner, runner.run(
            workspace=self.repo,
            specs=[],
            plans=[plan],
            run_id="resume-capability",
        )

    def test_unknown_child_blocker_requires_explicit_retry_without_launch(self) -> None:
        runner, first = self.run_blocked(resource="browser_visual_evidence")
        run_root = self.home / "orchestrator" / str(first["run_id"])
        before = sum(
            event.get("action") == "plan.attempt_started"
            for event in _runner_events(run_root)
        )

        stopped = runner.resume(run_id=str(first["run_id"]))

        self.assertEqual("blocked", stopped["status"])
        self.assertEqual(before, sum(
            event.get("action") == "plan.attempt_started"
            for event in _runner_events(run_root)
        ))
        self.assertEqual("resume.stopped_unknown_blocker", _runner_events(run_root)[-1]["action"])

        retried = runner.resume(run_id=str(first["run_id"]), retry_blocked=True)

        self.assertEqual("blocked", retried["status"])
        self.assertEqual(before + 1, sum(
            event.get("action") == "plan.attempt_started"
            for event in _runner_events(run_root)
        ))
        self.assertEqual(1, StateStore.open(run_root).state["plans"][0]["blocker"]["explicit_retry_count"])

    def test_controller_stop_blocker_persists_facts_and_plain_resume_stays_closed(self) -> None:
        runner = self.runner("controller-stop-facts")
        first = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("timeout_without_progress")],
            run_id="controller-stop-facts",
        )
        run_root = self.home / "orchestrator" / "controller-stop-facts"
        before = sum(
            event.get("action") == "plan.attempt_started"
            for event in _runner_events(run_root)
        )
        blocker = StateStore.open(run_root).state["plans"][0]["blocker"]

        self.assertEqual("blocked", first["status"])
        self.assertEqual({
            "kind": "operator_owned",
            "code": "no_progress_timeout",
            "resource": "plan-01",
            "parent_fingerprint": None,
            "fingerprint_available": False,
            "parent_observed": False,
            "explicit_retry_count": 0,
        }, blocker)

        stopped = runner.resume(run_id="controller-stop-facts")

        self.assertEqual("blocked", stopped["status"])
        self.assertEqual(before, sum(
            event.get("action") == "plan.attempt_started"
            for event in _runner_events(run_root)
        ))
        self.assertEqual("resume.stopped_unknown_blocker", _runner_events(run_root)[-1]["action"])

    def test_unchanged_loopback_blocker_stops_then_changed_probe_allows_one_launch(self) -> None:
        unavailable = CapabilityObservation(
            "loopback_bind", "workspace", "unavailable", "permission_denied",
            "parent_observed", {"host": "127.0.0.1"},
        )
        available = dataclasses.replace(
            unavailable, outcome="available", reason_code="bound",
        )
        with mock.patch("cpe_runtime.runner.observe_loopback_bind", return_value=unavailable):
            runner, first = self.run_blocked(resource="loopback_bind")
        run_root = self.home / "orchestrator" / str(first["run_id"])
        before = sum(
            event.get("action") == "plan.attempt_started"
            for event in _runner_events(run_root)
        )

        with mock.patch("cpe_runtime.runner.observe_loopback_bind", return_value=unavailable):
            stopped = runner.resume(run_id=str(first["run_id"]))

        self.assertEqual("blocked", stopped["status"])
        self.assertEqual(before, sum(
            event.get("action") == "plan.attempt_started"
            for event in _runner_events(run_root)
        ))
        self.assertEqual("resume.stopped_unchanged_blocker", _runner_events(run_root)[-1]["action"])

        with mock.patch("cpe_runtime.runner.observe_loopback_bind", return_value=available):
            resumed = runner.resume(run_id=str(first["run_id"]))

        self.assertEqual("blocked", resumed["status"])
        self.assertEqual(before + 1, sum(
            event.get("action") == "plan.attempt_started"
            for event in _runner_events(run_root)
        ))


class EnvelopeRepairTests(_RecoveryRunnerFixture):
    def _failed_result(
        self,
        run_id: str,
        *,
        mutate: object | None = None,
        expected_error: str = "unsafe_workflow_artifact",
        plans: list[Path] | None = None,
    ) -> tuple[SequentialRunner, Path, Path, Path, bytes]:
        runner = self.runner(run_id)

        def launch(request: StructuredLaunchRequest, _lock_fd: int) -> LaunchResult:
            kwargs = structured_launch_kwargs(request)
            worktree = Path(kwargs["worktree"])
            result_path = Path(kwargs["result_path"])
            log_path = Path(kwargs["log_path"])
            head = str(kwargs["current_commit"])
            evidence = worktree / ".superpowers" / "sdd"
            if evidence.exists():
                shutil.rmtree(evidence)
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / ".gitignore").write_text("*\n", encoding="utf-8")
            (evidence / "final-review.md").write_text(
                "Verdict: approved\nFindings: none\n", encoding="utf-8",
            )
            receipts = evidence / "receipts"
            receipts.mkdir()
            (receipts / "review.txt").write_text(
                "review: accepted\n", encoding="utf-8",
            )
            (receipts / "verification.txt").write_text(
                "verification: pass\n", encoding="utf-8",
            )
            append_execution_event(evidence / "execution-ledger.jsonl", {
                "event_id": "review-1",
                "source": "child_attested",
                "plan_id": str(kwargs["plan_id"]),
                "category": "review",
                "action": "approved",
                "result": "accepted",
                "evidence_refs": ["receipts/review.txt"],
                "review_id": "review-01",
                "artifact_digest": "c" * 64,
                "duration_ms": 1,
            })
            append_execution_event(evidence / "execution-ledger.jsonl", {
                "event_id": "verification-1",
                "source": "child_attested",
                "plan_id": str(kwargs["plan_id"]),
                "category": "verification",
                "action": "verified",
                "result": "pass",
                "evidence_refs": ["receipts/verification.txt"],
                "command_id": "focused",
                "argv_digest": "a" * 64,
                "evidence_key": "b" * 64,
                "duration_ms": 1,
                "requested_phase": "branch_final",
                "executed_phase": "branch_final",
                "avoided_executions": 0,
            })
            payload: dict[str, object] = {
                "plan_id": kwargs["plan_id"],
                "status": "completed",
                "head_commit": head,
                "summary": "mechanically repairable result envelope",
                "verification": [{
                    "command_id": "focused",
                    "argv_digest": "a" * 64,
                    "phase": "branch_final",
                    "evidence_key": "b" * 64,
                    "exit_code": 0,
                    "receipt_path": None,
                }],
                "checkpoint": None,
                "blocker": None,
                "workflow_receipt": {
                    "ledger_path": ".superpowers/sdd/execution-ledger.jsonl",
                    "final_review_path": (
                        str((evidence / "final-review.md").resolve())
                        if kwargs["plan_id"] == "plan-01"
                        else ".superpowers/sdd/final-review.md"
                    ),
                    "final_review_head": head,
                    "open_finding_ids": [],
                    "open_obligation_ids": [],
                },
            }
            if mutate is not None:
                mutate(payload, worktree, self.root)  # type: ignore[operator]
            original = json.dumps(
                payload, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            result_path.write_bytes(original)
            log_path.write_text("unsafe envelope fixture\n", encoding="utf-8")
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
                launcher_prompt_bytes=0,
            )

        runner.launcher._launch_structured = mock.Mock(
            side_effect=controller_side_effect(runner.launcher, launch),
        )
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=plans or [self.plan("completed")],
            run_id=run_id,
        )
        self.assertEqual("failed", result["status"])
        self.assertEqual(expected_error, result["error"])
        run_root = self.home / "orchestrator" / run_id
        store = StateStore.open(run_root)
        worktree = Path(store.state["worktree"])
        original_path = Path(store.state["plans"][0]["result_path"])
        return runner, run_root, worktree, original_path, original_path.read_bytes()

    def test_repaired_nonfinal_plan_advances_to_next_ordered_plan(self) -> None:
        runner, run_root, worktree, original_path, _ = self._failed_result(
            "repair-continues-to-next",
            plans=[
                self.plan("completed", number=1),
                self.plan("completed", number=2),
            ],
        )
        repair = self._repair(run_root, worktree, original_path)
        self.assertIsNotNone(repair)

        result = runner.resume(
            run_id="repair-continues-to-next", retry_failed=True,
        )

        self.assertEqual("completed", result["status"])
        state = StateStore.open(run_root).state
        self.assertEqual(2, state["current_plan_index"])
        self.assertEqual(
            ["completed", "completed"],
            [plan["status"] for plan in state["plans"]],
        )

    def _repair(self, run_root: Path, worktree: Path, result_path: Path):
        return evidence_module.repair_result_envelope(
            run_root=run_root,
            worktree=worktree,
            original_result_path=result_path,
        )

    def test_absolute_final_review_path_repairs_to_relative_and_preserves_original(self) -> None:
        _, run_root, worktree, original_path, original_bytes = self._failed_result(
            "repair-absolute",
        )

        repair = self._repair(run_root, worktree, original_path)

        self.assertIsNotNone(repair)
        assert repair is not None
        repaired = json.loads(repair.repaired_path.read_text(encoding="utf-8"))
        self.assertEqual(
            ".superpowers/sdd/final-review.md",
            repaired["workflow_receipt"]["final_review_path"],
        )
        self.assertEqual(
            ("/workflow_receipt/final_review_path",), repair.changed_fields,
        )
        self.assertEqual(original_bytes, original_path.read_bytes())
        self.assertEqual(0o400, original_path.stat().st_mode & 0o777)
        self.assertEqual(0o400, repair.repaired_path.stat().st_mode & 0o777)
        self.assertEqual(
            (run_root / "results" / "repaired").resolve(),
            repair.repaired_path.parent.resolve(),
        )
        self.assertEqual(
            hashlib.sha256(original_bytes).hexdigest(), repair.original_digest,
        )
        self.assertEqual(
            hashlib.sha256(repair.repaired_path.read_bytes()).hexdigest(),
            repair.repaired_digest,
        )

    def test_absolute_path_with_dot_dot_repairs_to_canonical_relative_path(self) -> None:
        def add_dot_dot(payload: dict[str, object], worktree: Path, _root: Path) -> None:
            nested = worktree / ".superpowers" / "sdd" / "nested"
            nested.mkdir()
            receipt = payload["workflow_receipt"]
            assert isinstance(receipt, dict)
            receipt["final_review_path"] = str(
                nested / ".." / "final-review.md"
            )

        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-dot-dot", mutate=add_dot_dot,
        )

        repair = self._repair(run_root, worktree, original_path)

        self.assertIsNotNone(repair)
        assert repair is not None
        payload = json.loads(repair.repaired_path.read_text(encoding="utf-8"))
        self.assertEqual(
            ".superpowers/sdd/final-review.md",
            payload["workflow_receipt"]["final_review_path"],
        )

    def test_symlink_escape_and_missing_artifact_fail_closed(self) -> None:
        def symlink_escape(payload: dict[str, object], worktree: Path, root: Path) -> None:
            outside = root / "outside-review.md"
            outside.write_text("not owned\n", encoding="utf-8")
            link = worktree / ".superpowers" / "sdd" / "review-link.md"
            link.symlink_to(outside)
            receipt = payload["workflow_receipt"]
            assert isinstance(receipt, dict)
            receipt["final_review_path"] = str(link)

        def missing(payload: dict[str, object], worktree: Path, _root: Path) -> None:
            receipt = payload["workflow_receipt"]
            assert isinstance(receipt, dict)
            receipt["final_review_path"] = str(
                worktree / ".superpowers" / "sdd" / "missing-review.md"
            )

        for index, mutate in enumerate((symlink_escape, missing), 1):
            with self.subTest(case=index):
                _, run_root, worktree, original_path, _ = self._failed_result(
                    f"repair-unsafe-artifact-{index}", mutate=mutate,
                )
                self.assertIsNone(
                    self._repair(run_root, worktree, original_path)
                )

    def test_unknown_key_status_and_summary_errors_are_not_repaired(self) -> None:
        mutations = (
            lambda payload, _worktree, _root: payload.__setitem__("unknown", True),
            lambda payload, _worktree, _root: payload.__setitem__("status", "failed"),
            lambda payload, _worktree, _root: payload.__setitem__("summary", ""),
        )
        for index, mutate in enumerate(mutations, 1):
            with self.subTest(case=index):
                _, run_root, worktree, original_path, _ = self._failed_result(
                    f"repair-semantic-error-{index}",
                    mutate=mutate,
                    expected_error="invalid_result",
                )
                self.assertIsNone(
                    self._repair(run_root, worktree, original_path)
                )

    def test_dirty_head_and_verification_drift_fail_closed(self) -> None:
        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-dirty",
        )
        (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        self.assertIsNone(self._repair(run_root, worktree, original_path))

        def wrong_head(payload: dict[str, object], _worktree: Path, _root: Path) -> None:
            payload["head_commit"] = "0" * 40

        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-wrong-head",
            mutate=wrong_head,
            expected_error="wrong_head",
        )
        self.assertIsNone(self._repair(run_root, worktree, original_path))

        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-verification-drift",
        )
        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        ledger_events = [
            json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
        ]
        verification_event = next(
            event for event in ledger_events
            if event.get("category") == "verification"
        )
        verification_event["evidence_key"] = "d" * 64
        ledger.write_text(
            "".join(
                json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                for event in ledger_events
            ),
            encoding="utf-8",
        )
        self.assertIsNone(self._repair(run_root, worktree, original_path))

    def test_review_finding_and_obligation_events_are_advisory_for_repair(self) -> None:
        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-advisory-workflow-events",
        )
        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        append_execution_event(ledger, {
            "event_id": "review-rejected",
            "source": "child_attested",
            "plan_id": "plan-01",
            "category": "review",
            "action": "rejected",
            "result": "fail",
            "evidence_refs": [],
            "review_id": "review-advisory",
            "artifact_digest": "d" * 64,
            "duration_ms": 1,
        })
        append_execution_event(ledger, {
            "event_id": "finding-unclosed",
            "source": "child_attested",
            "plan_id": "plan-01",
            "category": "finding_fix",
            "action": "started",
            "result": "fail",
            "evidence_refs": [],
            "finding_ids": ["F-advisory"],
            "fix_digest": "e" * 64,
            "duration_ms": 1,
        })
        append_execution_event(ledger, {
            "event_id": "obligation-unprojected",
            "source": "child_attested",
            "plan_id": "plan-01",
            "category": "obligation",
            "action": "started",
            "result": "fail",
            "evidence_refs": [],
            "obligation_id": "O-advisory",
            "obligation_digest": "f" * 64,
        })

        self.assertIsNotNone(self._repair(run_root, worktree, original_path))

        valid_receipt = {
            "ledger_path": ".superpowers/sdd/execution-ledger.jsonl",
            "final_review_path": ".superpowers/sdd/final-review.md",
            "final_review_head": git(worktree, "rev-parse", "HEAD"),
            "open_finding_ids": [],
            "open_obligation_ids": [],
        }
        self.assertIsNone(runner_module._workflow_receipt_error(
            worktree, valid_receipt,
        ))
        for field in ("open_finding_ids", "open_obligation_ids"):
            invalid = json.loads(json.dumps(valid_receipt))
            invalid[field] = ["still-open"]
            with self.subTest(preserved_gate=field):
                self.assertEqual(
                    "invalid_workflow_receipt",
                    runner_module._workflow_receipt_error(worktree, invalid),
                )

    def test_other_original_integrity_error_is_not_repaired(self) -> None:
        def relative_missing(
            payload: dict[str, object], _worktree: Path, _root: Path,
        ) -> None:
            receipt = payload["workflow_receipt"]
            assert isinstance(receipt, dict)
            receipt["final_review_path"] = "missing-review.md"

        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-other-error", mutate=relative_missing,
        )
        events = _runner_events(run_root)
        events[-1]["reason"] = "verification_failed"
        (run_root / "events.jsonl").write_text(
            "".join(
                json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )
        self.assertIsNone(self._repair(run_root, worktree, original_path))

    def test_unsafe_failure_provenance_binds_attempt_path_and_digest(self) -> None:
        _, run_root, _, original_path, original_bytes = self._failed_result(
            "repair-bound-provenance",
        )
        failure = next(
            event for event in reversed(_runner_events(run_root))
            if event.get("action") == "plan.integrity_failed"
        )
        self.assertEqual(1, failure["attempt"])
        self.assertEqual(str(original_path), failure["original_result_path"])
        self.assertEqual(
            hashlib.sha256(original_bytes).hexdigest(),
            failure["original_result_sha256"],
        )

    def test_later_terminal_and_bound_provenance_mismatch_reject_repair(self) -> None:
        cases = (
            "later-evidence", "later-plan-failed", "later-integrity",
            "digest-mismatch", "path-mismatch",
        )
        for case in cases:
            with self.subTest(case=case):
                _, run_root, worktree, original_path, _ = self._failed_result(
                    f"repair-provenance-{case}",
                )
                if case == "later-evidence":
                    StateStore.open(run_root).append_event(
                        "plan.evidence_failed",
                        plan_id="plan-01",
                        reason="later terminal failure",
                    )
                elif case == "later-plan-failed":
                    StateStore.open(run_root).append_event(
                        "plan.failed", plan_id="plan-01", reason="later failure",
                    )
                elif case == "later-integrity":
                    StateStore.open(run_root).append_event(
                        "plan.integrity_failed",
                        plan_id="plan-01",
                        reason="verification_failed",
                    )
                else:
                    events = _runner_events(run_root)
                    failure = next(
                        event for event in reversed(events)
                        if event.get("action") == "plan.integrity_failed"
                    )
                    if case == "digest-mismatch":
                        failure["original_result_sha256"] = "0" * 64
                    else:
                        failure["original_result_path"] = str(
                            run_root / "results" / "different.json"
                        )
                    (run_root / "events.jsonl").write_text(
                        "".join(
                            json.dumps(event, sort_keys=True, separators=(",", ":"))
                            + "\n"
                            for event in events
                        ),
                        encoding="utf-8",
                    )
                self.assertIsNone(
                    self._repair(run_root, worktree, original_path)
                )

    def test_intervening_attempt_rejects_prior_unsafe_result(self) -> None:
        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-intervening-attempt",
        )
        store = StateStore.open(run_root)
        plan = store.state["plans"][0]
        later_result = run_root / "results" / "plan-01-attempt-2.json"
        later_result.write_text("{}", encoding="utf-8")
        plan["attempt_count"] = 2
        plan["controller_launch_count"] = 2
        plan["result_path"] = str(later_result.resolve())
        store.save()
        store.append_event(
            "plan.attempt_started",
            plan_id="plan-01",
            attempt=2,
            controller_launch_count=2,
            head=plan["last_known_head"],
            timeout_seconds=3600,
        )
        self.assertIsNone(self._repair(run_root, worktree, original_path))

    def test_non_null_verification_receipt_is_preserved_on_zero_launch_resume(self) -> None:
        def add_receipt_path(
            payload: dict[str, object], _worktree: Path, _root: Path,
        ) -> None:
            verification = payload["verification"]
            assert isinstance(verification, list)
            assert isinstance(verification[0], dict)
            verification[0]["receipt_path"] = (
                ".superpowers/sdd/receipts/verification.txt"
            )

        runner, run_root, _, _, _ = self._failed_result(
            "repair-verification-receipt", mutate=add_receipt_path,
        )
        before = StateStore.open(run_root).state["plans"][0]
        attempts = before["attempt_count"]
        controller_launches = before["controller_launch_count"]

        completed = runner.resume(
            run_id="repair-verification-receipt", retry_failed=True,
        )

        self.assertEqual("completed", completed["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        plan = StateStore.open(run_root).state["plans"][0]
        self.assertEqual(attempts, plan["attempt_count"])
        self.assertEqual(controller_launches, plan["controller_launch_count"])
        repaired = json.loads(Path(plan["result_path"]).read_text(encoding="utf-8"))
        self.assertEqual(
            ".superpowers/sdd/receipts/verification.txt",
            repaired["verification"][0]["receipt_path"],
        )

    def test_empty_verification_receipt_preserves_normal_handoff_and_repair_contract(self) -> None:
        def add_empty_receipt(
            payload: dict[str, object], _worktree: Path, _root: Path,
        ) -> None:
            verification = payload["verification"]
            assert isinstance(verification, list)
            assert isinstance(verification[0], dict)
            verification[0]["receipt_path"] = ""

        runner, run_root, _, _, _ = self._failed_result(
            "repair-empty-verification-receipt",
            mutate=add_empty_receipt,
            expected_error="unsafe_workflow_artifact",
        )
        completed = runner.resume(
            run_id="repair-empty-verification-receipt", retry_failed=True,
        )

        self.assertEqual("completed", completed["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        plan = StateStore.open(run_root).state["plans"][0]
        repaired = json.loads(Path(plan["result_path"]).read_text(encoding="utf-8"))
        self.assertEqual("", repaired["verification"][0]["receipt_path"])

    def test_repaired_result_swap_before_handoff_parse_fails_closed(self) -> None:
        runner, run_root, _, original_path, original_bytes = self._failed_result(
            "repair-result-swap-before-parse",
        )
        before = StateStore.open(run_root).state["plans"][0]
        attempts = before["attempt_count"]
        controller_launches = before["controller_launch_count"]
        original_repair = runner_module.repair_result_envelope
        captured: dict[str, object] = {}

        def swap_after_repair(**kwargs: object):
            repair = original_repair(**kwargs)
            assert repair is not None
            captured["repair_path"] = str(repair.repaired_path)
            replacement = json.loads(repair.repaired_path.read_text(encoding="utf-8"))
            replacement["summary"] = "attacker replacement must not be accepted"
            temporary = repair.repaired_path.with_suffix(".replacement")
            temporary.write_text(
                json.dumps(replacement, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, repair.repaired_path)
            captured["replacement_bytes"] = repair.repaired_path.read_bytes()
            return repair

        with mock.patch.object(
            runner_module, "repair_result_envelope", new=swap_after_repair,
        ):
            rejected = runner.resume(
                run_id="repair-result-swap-before-parse", retry_failed=True,
            )

        self.assertEqual("failed", rejected["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertEqual(original_bytes, original_path.read_bytes())
        plan = StateStore.open(run_root).state["plans"][0]
        self.assertEqual(attempts, plan["attempt_count"])
        self.assertEqual(controller_launches, plan["controller_launch_count"])
        self.assertEqual(captured["repair_path"], plan["result_path"])
        self.assertEqual(str(original_path), plan["original_result_path"])
        repaired_path = Path(str(plan["result_path"]))
        self.assertEqual(captured["replacement_bytes"], repaired_path.read_bytes())
        repair_events = [
            event for event in _runner_events(run_root)
            if event.get("action") == "result.envelope_repaired"
        ]
        self.assertEqual(1, len(repair_events))
        self.assertFalse(any(
            event.get("action") == "plan.completed"
            for event in _runner_events(run_root)
        ))

    def test_repaired_result_mode_drift_before_handoff_parse_fails_closed(self) -> None:
        runner, run_root, _, original_path, original_bytes = self._failed_result(
            "repair-result-mode-before-parse",
        )
        before = StateStore.open(run_root).state["plans"][0]
        attempts = before["attempt_count"]
        controller_launches = before["controller_launch_count"]
        original_repair = runner_module.repair_result_envelope
        captured: dict[str, object] = {}

        def chmod_after_repair(**kwargs: object):
            repair = original_repair(**kwargs)
            assert repair is not None
            repair.repaired_path.chmod(0o600)
            metadata = repair.repaired_path.stat()
            captured.update({
                "path": str(repair.repaired_path),
                "inode": metadata.st_ino,
                "bytes": repair.repaired_path.read_bytes(),
            })
            return repair

        with mock.patch.object(
            runner_module, "repair_result_envelope", new=chmod_after_repair,
        ):
            rejected = runner.resume(
                run_id="repair-result-mode-before-parse", retry_failed=True,
            )

        self.assertEqual("failed", rejected["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertEqual(original_bytes, original_path.read_bytes())
        plan = StateStore.open(run_root).state["plans"][0]
        self.assertEqual(attempts, plan["attempt_count"])
        self.assertEqual(controller_launches, plan["controller_launch_count"])
        repaired_path = Path(str(captured["path"]))
        self.assertEqual(captured["inode"], repaired_path.stat().st_ino)
        self.assertEqual(captured["bytes"], repaired_path.read_bytes())
        self.assertEqual(0o600, repaired_path.stat().st_mode & 0o777)
        self.assertFalse(any(
            event.get("action") == "plan.completed"
            for event in _runner_events(run_root)
        ))

    def test_repaired_result_swap_immediately_before_final_seal_fails_closed(self) -> None:
        runner, run_root, _, original_path, original_bytes = self._failed_result(
            "repair-result-swap-before-seal",
        )
        before = StateStore.open(run_root).state["plans"][0]
        attempts = before["attempt_count"]
        controller_launches = before["controller_launch_count"]
        original_seal = runner._seal_result
        captured: dict[str, bytes] = {}

        def swap_before_seal(path: Path, *args: object, **kwargs: object) -> None:
            replacement = json.loads(path.read_text(encoding="utf-8"))
            replacement["summary"] = "late attacker replacement must not be accepted"
            temporary = path.with_suffix(".replacement")
            temporary.write_text(
                json.dumps(replacement, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, path)
            captured["replacement_bytes"] = path.read_bytes()
            captured["replacement_mode"] = (path.stat().st_mode & 0o777).to_bytes(2)
            original_seal(path, *args, **kwargs)

        with mock.patch.object(runner, "_seal_result", new=swap_before_seal):
            rejected = runner.resume(
                run_id="repair-result-swap-before-seal", retry_failed=True,
            )

        self.assertEqual("failed", rejected["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertEqual(original_bytes, original_path.read_bytes())
        plan = StateStore.open(run_root).state["plans"][0]
        self.assertEqual(attempts, plan["attempt_count"])
        self.assertEqual(controller_launches, plan["controller_launch_count"])
        repaired_path = Path(str(plan["result_path"]))
        self.assertEqual(captured["replacement_bytes"], repaired_path.read_bytes())
        self.assertEqual(
            int.from_bytes(captured["replacement_mode"]),
            repaired_path.stat().st_mode & 0o777,
        )
        repair_events = [
            event for event in _runner_events(run_root)
            if event.get("action") == "result.envelope_repaired"
        ]
        self.assertEqual(1, len(repair_events))
        self.assertFalse(any(
            event.get("action") == "plan.completed"
            for event in _runner_events(run_root)
        ))

    def test_repaired_result_mode_drift_immediately_before_seal_fails_closed(self) -> None:
        runner, run_root, _, original_path, original_bytes = self._failed_result(
            "repair-result-mode-before-seal",
        )
        before = StateStore.open(run_root).state["plans"][0]
        attempts = before["attempt_count"]
        controller_launches = before["controller_launch_count"]
        original_seal = runner._seal_result
        captured: dict[str, object] = {}

        def chmod_before_seal(
            path: Path, *args: object, **kwargs: object,
        ) -> None:
            path.chmod(0o600)
            metadata = path.stat()
            captured.update({
                "inode": metadata.st_ino,
                "bytes": path.read_bytes(),
            })
            original_seal(path, *args, **kwargs)

        with mock.patch.object(runner, "_seal_result", new=chmod_before_seal):
            rejected = runner.resume(
                run_id="repair-result-mode-before-seal", retry_failed=True,
            )

        self.assertEqual("failed", rejected["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertEqual(original_bytes, original_path.read_bytes())
        plan = StateStore.open(run_root).state["plans"][0]
        self.assertEqual(attempts, plan["attempt_count"])
        self.assertEqual(controller_launches, plan["controller_launch_count"])
        repaired_path = Path(str(plan["result_path"]))
        self.assertEqual(captured["inode"], repaired_path.stat().st_ino)
        self.assertEqual(captured["bytes"], repaired_path.read_bytes())
        self.assertEqual(0o600, repaired_path.stat().st_mode & 0o777)
        self.assertFalse(any(
            event.get("action") == "plan.completed"
            for event in _runner_events(run_root)
        ))

    def test_recorded_repair_digest_mismatch_rejects_before_reconstruction(self) -> None:
        runner, run_root, _, _, _ = self._failed_result(
            "repair-recorded-digest-mismatch",
        )
        original_save = StateStore.save
        injected = False

        def crash_after_repaired_state(store: StateStore) -> None:
            nonlocal injected
            original_save(store)
            plan = store.state["plans"][0]
            if (
                plan.get("original_result_path") is not None
                and store.state.get("status") == "running"
                and not injected
            ):
                injected = True
                raise RuntimeError("injected recorded repair window")

        with (
            mock.patch.object(StateStore, "save", new=crash_after_repaired_state),
            self.assertRaisesRegex(RuntimeError, "injected recorded repair window"),
        ):
            runner.resume(
                run_id="repair-recorded-digest-mismatch", retry_failed=True,
            )

        store = StateStore.open(run_root)
        repaired_path = Path(store.state["plans"][0]["result_path"])
        replacement = json.loads(repaired_path.read_text(encoding="utf-8"))
        replacement["summary"] = "recorded mismatch must not be reconstructed"
        temporary = repaired_path.with_suffix(".replacement")
        temporary.write_text(
            json.dumps(replacement, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, repaired_path)
        replacement_bytes = repaired_path.read_bytes()
        replacement_mode = repaired_path.stat().st_mode & 0o777

        with (
            mock.patch.object(
                runner_module,
                "repair_result_envelope",
                side_effect=AssertionError("must reject before reconstruction"),
            ),
            self.assertRaisesRegex(ValueError, "recorded digest"),
        ):
            runner.resume(run_id="repair-recorded-digest-mismatch")

        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertEqual(replacement_bytes, repaired_path.read_bytes())
        self.assertEqual(replacement_mode, repaired_path.stat().st_mode & 0o777)
        self.assertEqual(1, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "result.envelope_repaired"
        ]))

    def test_duplicate_execution_ledger_key_fails_closed(self) -> None:
        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-duplicate-ledger-key",
        )
        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        text = ledger.read_text(encoding="utf-8")
        text = text.replace(
            '"event_id":"review-1"',
            '"event_id":"review-1","event_id":"review-1"',
            1,
        )
        ledger.write_text(text, encoding="utf-8")
        self.assertIsNone(self._repair(run_root, worktree, original_path))

    def test_parent_component_replacement_after_proof_fails_closed(self) -> None:
        _, run_root, worktree, original_path, _ = self._failed_result(
            "repair-parent-swap",
        )
        original_validate = evidence_module._validate_execution_ledger_payload
        swapped = False

        def replace_parent(payload: bytes, *, expected_plan_id: str):
            nonlocal swapped
            events = original_validate(
                payload, expected_plan_id=expected_plan_id,
            )
            if not swapped:
                swapped = True
                current = worktree / ".superpowers" / "sdd"
                moved = worktree / ".superpowers" / "sdd-replaced"
                current.rename(moved)
                shutil.copytree(moved, current)
            return events

        with mock.patch.object(
            evidence_module,
            "_validate_execution_ledger_payload",
            new=replace_parent,
        ):
            self.assertIsNone(self._repair(run_root, worktree, original_path))

    def test_same_path_inode_swap_fails_resume_with_zero_launch(self) -> None:
        runner, run_root, worktree, _, _ = self._failed_result(
            "repair-inode-swap",
        )
        original_validate = evidence_module._validate_execution_ledger_payload
        swapped = False

        def replace_review(payload: bytes, *, expected_plan_id: str):
            nonlocal swapped
            events = original_validate(
                payload, expected_plan_id=expected_plan_id,
            )
            if not swapped:
                swapped = True
                review = worktree / ".superpowers" / "sdd" / "final-review.md"
                replacement = review.with_name("replacement-review.md")
                replacement.write_bytes(review.read_bytes())
                os.replace(replacement, review)
            return events

        with mock.patch.object(
            evidence_module,
            "_validate_execution_ledger_payload",
            new=replace_review,
        ):
            rejected = runner.resume(
                run_id="repair-inode-swap", retry_failed=True,
            )
        self.assertEqual("failed", rejected["status"])
        self.assertEqual("unsafe_workflow_artifact", rejected["error"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertFalse(any(
            event.get("action") == "result.envelope_repaired"
            for event in _runner_events(run_root)
        ))

    def test_repair_only_resume_accepts_receipt_with_zero_new_launches(self) -> None:
        runner, run_root, _, original_path, original_bytes = self._failed_result(
            "repair-resume",
        )
        original_plan = StateStore.open(run_root).state["plans"][0]
        original_attempts = original_plan["attempt_count"]
        original_controller_launches = original_plan["controller_launch_count"]

        completed = runner.resume(run_id="repair-resume", retry_failed=True)

        self.assertEqual("completed", completed["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        state = StateStore.open(run_root).state
        plan = state["plans"][0]
        self.assertEqual(original_attempts, plan["attempt_count"])
        self.assertEqual(
            original_controller_launches, plan["controller_launch_count"],
        )
        self.assertEqual(str(original_path), plan["original_result_path"])
        self.assertNotEqual(plan["original_result_path"], plan["result_path"])
        self.assertEqual(original_bytes, original_path.read_bytes())
        self.assertTrue((run_root / "evidence" / "plan-01").is_dir())
        repaired_event = next(
            event for event in _runner_events(run_root)
            if event.get("action") == "result.envelope_repaired"
        )
        self.assertEqual(hashlib.sha256(original_bytes).hexdigest(), repaired_event["original_digest"])
        self.assertEqual(
            ["/workflow_receipt/final_review_path"],
            repaired_event["changed_fields"],
        )

    def test_repair_event_wal_reconciles_after_event_before_state_crash(self) -> None:
        runner, run_root, _, _, _ = self._failed_result("repair-event-crash")
        original_append = StateStore._append_event_bytes
        injected = False

        def crash(store: StateStore, encoded: bytes) -> None:
            nonlocal injected
            original_append(store, encoded)
            if b'"action":"result.envelope_repaired"' in encoded and not injected:
                injected = True
                raise RuntimeError("injected envelope event crash")

        with (
            mock.patch.object(StateStore, "_append_event_bytes", new=crash),
            self.assertRaisesRegex(RuntimeError, "injected envelope event crash"),
        ):
            runner.resume(run_id="repair-event-crash", retry_failed=True)

        self.assertEqual("failed", StateStore.open(run_root).state["status"])
        completed = runner.resume(
            run_id="repair-event-crash", retry_failed=True,
        )
        self.assertEqual("completed", completed["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertEqual(1, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "result.envelope_repaired"
        ]))

    def test_repair_state_reconciles_without_launch_after_state_save_crash(self) -> None:
        runner, run_root, _, _, _ = self._failed_result("repair-state-crash")
        original_save = StateStore.save
        injected = False

        def crash(store: StateStore) -> None:
            nonlocal injected
            original_save(store)
            plans = store.state.get("plans", [])
            plan = plans[0] if plans else {}
            if (
                isinstance(plan, dict)
                and plan.get("original_result_path") is not None
                and store.state.get("status") == "running"
                and not injected
            ):
                injected = True
                raise RuntimeError("injected envelope state crash")

        with (
            mock.patch.object(StateStore, "save", new=crash),
            self.assertRaisesRegex(RuntimeError, "injected envelope state crash"),
        ):
            runner.resume(run_id="repair-state-crash", retry_failed=True)

        self.assertEqual("running", StateStore.open(run_root).state["status"])
        completed = runner.resume(run_id="repair-state-crash")
        self.assertEqual("completed", completed["status"])
        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertEqual(1, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "result.envelope_repaired"
        ]))

    def test_repair_state_crash_rejects_later_evidence_drift_without_launch(self) -> None:
        runner, run_root, worktree, _, _ = self._failed_result(
            "repair-state-drift",
        )
        original_save = StateStore.save
        injected = False

        def crash(store: StateStore) -> None:
            nonlocal injected
            original_save(store)
            plan = store.state["plans"][0]
            if (
                plan.get("original_result_path") is not None
                and store.state.get("status") == "running"
                and not injected
            ):
                injected = True
                raise RuntimeError("injected envelope drift window")

        with (
            mock.patch.object(StateStore, "save", new=crash),
            self.assertRaisesRegex(RuntimeError, "injected envelope drift window"),
        ):
            runner.resume(run_id="repair-state-drift", retry_failed=True)

        ledger = worktree / ".superpowers" / "sdd" / "execution-ledger.jsonl"
        events = [
            json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
        ]
        next(
            event for event in events if event.get("category") == "verification"
        )["evidence_key"] = "f" * 64
        ledger.write_text(
            "".join(
                json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError, "recorded result envelope repair no longer validates",
        ):
            runner.resume(run_id="repair-state-drift")
        self.assertEqual(0, fake_codex_launch_count(run_root))
        self.assertEqual("running", StateStore.open(run_root).state["status"])

    def test_state_and_metrics_derive_repair_without_mutable_counter(self) -> None:
        _, run_root, _, _, _ = self._failed_result("repair-state-default")
        state = StateStore.open(run_root).state
        self.assertIsNone(state["plans"][0]["original_result_path"])
        self.assertNotIn("envelope_repairs", state)
        self.assertEqual(
            {
                "launches_avoided": 1,
                "envelope_repairs": 1,
                "productive_timeouts": 0,
                "no_progress_slices": 0,
                "budget_stops": 0,
                "continuation_reason_counts": {},
            },
            reporting_module.derive_recovery_metrics([{
                "action": "result.envelope_repaired",
            }]),
        )




class ProgressRecoveryIntegrationTests(_RecoveryRunnerFixture):
    def test_recovery_metrics_are_derived_once_from_decision_events(self) -> None:
        metrics = reporting_module.derive_recovery_metrics([
            {
                "action": "resume.stopped_unchanged_blocker",
                "reason": "unchanged_environment_blocker",
            },
            {
                "action": "plan.checkpoint_decided",
                "decision": "continue",
                "reason": "productive_timeout",
            },
        ])
        self.assertEqual(
            {
                "launches_avoided": 1,
                "envelope_repairs": 0,
                "productive_timeouts": 1,
                "no_progress_slices": 0,
                "budget_stops": 0,
                "continuation_reason_counts": {"productive_timeout": 1},
            },
            metrics,
        )

    def test_recovery_metrics_materialize_in_optimization_reports(self) -> None:
        run_id = "report-recovery-metrics"
        runner = self.runner(run_id)
        completed = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("completed")],
            run_id=run_id,
        )
        self.assertEqual("completed", completed["status"])
        run_root = self.home / "orchestrator" / run_id
        store = StateStore.open(run_root)
        for action, details in (
            ("resume.stopped_unchanged_blocker", {"reason": "unchanged_environment_blocker"}),
            ("result.envelope_repaired", {"plan_id": "plan-01"}),
            ("plan.checkpoint_decided", {"decision": "continue", "reason": "productive_timeout"}),
            ("plan.checkpoint_decided", {"decision": "stop_stalled", "reason": "no_progress_timeout"}),
            ("plan.pre_spawn_stopped", {"decision": "stop_budget", "reason": "launch_budget_exhausted"}),
        ):
            store.append_event(action, **details)

        self.assertIsNone(runner._update_reports(store))
        report = json.loads(
            (run_root / "reports" / "optimization-report.json").read_text()
        )
        self.assertEqual(
            {
                "launches_avoided": 2,
                "envelope_repairs": 1,
                "productive_timeouts": 1,
                "no_progress_slices": 1,
                "budget_stops": 1,
                "continuation_reason_counts": {"productive_timeout": 1},
            },
            report["recovery_metrics"],
        )
        markdown = (run_root / "reports" / "optimization-report.md").read_text()
        self.assertIn("## Recovery Metrics", markdown)
        self.assertIn("- Launches avoided: 2", markdown)
        self.assertIn("- Continuation reasons: productive_timeout=1", markdown)

    def test_stop_and_finish_decisions_are_not_continuation_reasons(self) -> None:
        metrics = reporting_module.derive_recovery_metrics([
            {
                "action": "plan.checkpoint_decided",
                "decision": "continue",
                "reason": "productive_timeout",
            },
            {
                "action": "plan.checkpoint_decided",
                "decision": "stop_stalled",
                "reason": "no_progress_timeout",
            },
            {
                "action": "plan.checkpoint_decided",
                "decision": "finish",
                "reason": "child_completed",
            },
        ])
        self.assertEqual(
            {"productive_timeout": 1},
            metrics["continuation_reason_counts"],
        )

    def test_pre_spawn_budget_stops_are_counted_from_events(self) -> None:
        reasons = (
            "launch_budget_exhausted",
            "wall_budget_exhausted",
        )
        metrics = reporting_module.derive_recovery_metrics([
            {
                "action": "plan.pre_spawn_stopped",
                "decision": "stop_budget",
                "reason": reason,
            }
            for reason in reasons
        ])
        self.assertEqual(2, metrics["budget_stops"])
        self.assertEqual({}, metrics["continuation_reason_counts"])

    def test_productive_timeout_continues_once_and_completes(self) -> None:
        run_id = "productive-timeout"
        runner = self.runner(run_id)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("timeout_with_progress")],
            run_id=run_id,
        )
        run_root = self.home / "orchestrator" / run_id
        self.assertEqual("completed", result["status"])
        self.assertEqual(2, fake_codex_launch_count(run_root))
        self.assertEqual([3600.0, 3600.0], self.captured_timeouts)
        state = StateStore.open(run_root).state["plans"][0]
        self.assertEqual(2, state["controller_launch_count"])
        self.assertEqual(0, state["checkpoint_count"])
        events = _runner_events(run_root)
        self.assertTrue(any(
            event.get("action") == "plan.checkpoint_decided"
            and event.get("reason") == "productive_timeout"
            for event in events
        ))

    def test_first_no_progress_timeout_stops_without_confirmation_launch(self) -> None:
        run_id = "stalled-timeout"
        runner = self.runner(run_id)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("timeout_without_progress")],
            run_id=run_id,
        )
        run_root = self.home / "orchestrator" / run_id
        self.assertEqual("blocked", result["status"])
        self.assertEqual("no_progress_timeout", result["last_decision_reason"])
        self.assertEqual(1, fake_codex_launch_count(run_root))
        self.assertEqual([1200.0], self.captured_timeouts)
        state = StateStore.open(run_root).state["plans"][0]
        self.assertEqual(1, state["controller_launch_count"])
        self.assertEqual(0, state["checkpoint_count"])
        blocker = json.loads(Path(state["result_path"]).read_text(encoding="utf-8"))
        self.assertEqual("operator_owned", blocker["blocker"]["kind"])
        self.assertEqual("no_progress_timeout", blocker["blocker"]["code"])

    def test_historical_direct_cpe_timeouts_split_without_comparative_inflation(self) -> None:
        fixtures = ROOT / "evals" / "fixtures"
        direct = json.loads(
            (fixtures / "canvas-direct-run-format2.json").read_text(encoding="utf-8")
        )
        timeout = next(
            item for item in direct["observations"] if item["signal"] == "slice_timeout"
        )
        advanced = next(
            item for item in direct["observations"]
            if item["signal"] == "head_advanced_between_timeouts"
        )
        self.assertEqual(5, timeout["occurrences"])
        self.assertEqual(3600, timeout["duration_seconds_each"])
        self.assertEqual(2, len(advanced["plans"]))

        productive_id = "fixture-productive"
        productive_runner = self.runner(productive_id)
        productive = productive_runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("timeout_with_progress")],
            run_id=productive_id,
        )
        productive_root = self.home / "orchestrator" / productive_id
        self.assertEqual("completed", productive["status"])
        self.assertEqual(2, fake_codex_launch_count(productive_root))
        self.assertEqual([3600.0, 3600.0], self.captured_timeouts)
        productive_events = _runner_events(productive_root)
        self.assertTrue(any(
            event.get("action") == "plan.checkpoint_decided"
            and event.get("decision") == "continue"
            and event.get("reason") == "productive_timeout"
            for event in productive_events
        ))

        self.captured_timeouts.clear()
        self.invocations.write_text("", encoding="utf-8")
        blocker_id = "fixture-unchanged-blocker"
        blocker_runner = self.runner(blocker_id)
        unavailable = CapabilityObservation(
            "loopback_bind", "workspace", "unavailable", "permission_denied",
            "parent_observed", {"host": "127.0.0.1"},
        )
        with mock.patch(
            "cpe_runtime.runner._observe_capabilities",
            return_value=[unavailable],
        ):
            first = blocker_runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("resume_completed", loopback=True)],
                run_id=blocker_id,
            )
            stopped = blocker_runner.resume(run_id=blocker_id)
        blocker_root = self.home / "orchestrator" / blocker_id
        self.assertEqual("blocked", first["status"])
        self.assertEqual("blocked", stopped["status"])
        self.assertEqual(0, fake_codex_launch_count(blocker_root))
        self.assertEqual([3600.0], self.captured_timeouts)
        self.assertEqual(
            "resume.stopped_unchanged_blocker",
            _runner_events(blocker_root)[-1]["action"],
        )

        for name in ("readmates-comparative.json", "gasstation-comparative.json"):
            payload = json.loads((fixtures / name).read_text(encoding="utf-8"))
            self.assertFalse(payload["count_as_cpe_metrics"])


class PreSpawnBudgetTests(_RecoveryRunnerFixture):
    def test_resume_stops_before_launch_for_every_hard_plan_budget(self) -> None:
        cases = (
            ("launch", "controller_launch_count", 6, "launch_budget_exhausted"),
            ("wall", "plan_elapsed_seconds", 7_200, "wall_budget_exhausted"),
        )
        for label, field, value, reason in cases:
            with self.subTest(label=label):
                run_id = f"pre-spawn-{label}"
                runner = self.runner(run_id)
                initial = runner.run(
                    workspace=self.repo,
                    specs=[],
                    plans=[self.plan("blocked")],
                    run_id=run_id,
                )
                self.assertEqual("blocked", initial["status"])
                run_root = self.home / "orchestrator" / run_id
                store = StateStore.open(run_root)
                plan = store.state["plans"][0]
                plan[field] = value
                plan["status"] = "checkpointed"
                store.state["status"] = "checkpointed"
                store.save()

                resumed = runner.resume(run_id=run_id)

                self.assertEqual("blocked", resumed["status"])
                self.assertEqual(reason, resumed["last_decision_reason"])
                self.assertEqual(0, fake_codex_launch_count(run_root))
                events = _runner_events(run_root)
                self.assertTrue(any(
                    event.get("action") == "plan.pre_spawn_stopped"
                    and event.get("reason") == reason
                    for event in events
                ))


class CheckpointTrustAndLedgerTests(_RecoveryRunnerFixture):
    def test_wrong_head_completion_does_not_create_parent_checkpoint(self) -> None:
        run_id = "wrong-head-trust"
        runner = self.runner(run_id)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("wrong_commit")],
            run_id=run_id,
        )
        run_root = self.home / "orchestrator" / run_id
        self.assertEqual("failed", result["status"])
        self.assertEqual("wrong_head", result["error"])
        self.assertEqual(0, StateStore.open(run_root).state["plans"][0]["checkpoint_count"])
        self.assertFalse(any(
            event.get("action") == "plan.checkpoint_decided"
            for event in _runner_events(run_root)
        ))

    def test_completed_payload_killed_by_timeout_fails_typed_before_finish(self) -> None:
        run_id = "timed-out-completion"
        runner = self.runner(run_id)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("timeout_with_completed_result")],
            run_id=run_id,
        )
        run_root = self.home / "orchestrator" / run_id
        self.assertEqual("failed", result["status"])
        self.assertEqual("timed_out", result["error"])
        self.assertEqual(0, StateStore.open(run_root).state["plans"][0]["checkpoint_count"])

    def test_non_timeout_failed_and_checkpointed_results_preserve_terminal_status(self) -> None:
        cases = (
            ("failed", "failed", "child_failed"),
            ("interrupted", "checkpointed", "child_checkpointed"),
        )
        for scenario, status, reason in cases:
            with self.subTest(scenario=scenario):
                run_id = f"canonical-stop-{scenario}"
                runner = self.runner(run_id)
                result = runner.run(
                    workspace=self.repo,
                    specs=[],
                    plans=[self.plan(scenario)],
                    run_id=run_id,
                )
                self.assertEqual(status, result["status"])
                self.assertEqual(reason, result["last_decision_reason"])
                self.assertEqual(1, fake_codex_launch_count(
                    self.home / "orchestrator" / run_id
                ))

    def test_malformed_ledger_fails_typed_without_uncaught_exception(self) -> None:
        run_id = "malformed-ledger"
        runner = self.runner(run_id)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("timeout_with_malformed_ledger")],
            run_id=run_id,
        )
        self.assertEqual("failed", result["status"])
        self.assertEqual("execution_ledger_invalid", result["error"])

    def test_populated_ledger_deletion_is_regression_not_progress(self) -> None:
        run_id = "ledger-regression"
        runner = self.runner(run_id)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("timeout_with_ledger_deletion")],
            run_id=run_id,
        )
        run_root = self.home / "orchestrator" / run_id
        self.assertEqual("failed", result["status"])
        self.assertEqual("execution_ledger_regressed", result["error"])
        self.assertEqual(2, fake_codex_launch_count(run_root))
        decisions = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.checkpoint_decided"
        ]
        self.assertEqual(1, len(decisions))

    def test_rewriting_event_content_with_same_id_is_ledger_regression(self) -> None:
        run_id = "ledger-content-regression"
        runner = self.runner(run_id)
        result = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("timeout_with_ledger_rewrite")],
            run_id=run_id,
        )
        run_root = self.home / "orchestrator" / run_id
        self.assertEqual("failed", result["status"])
        self.assertEqual("execution_ledger_regressed", result["error"])
        self.assertEqual(2, fake_codex_launch_count(run_root))
        self.assertEqual(1, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.checkpoint_decided"
        ]))


class CheckpointCrashReconciliationTests(_RecoveryRunnerFixture):
    def _assert_reconciled_after_crash(self, patcher: object, run_id: str) -> None:
        runner = self.runner(run_id)
        with patcher, self.assertRaisesRegex(RuntimeError, "injected checkpoint crash"):
            runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("timeout_with_progress")],
                run_id=run_id,
            )
        run_root = self.home / "orchestrator" / run_id
        crashed = StateStore.open(run_root).state["plans"][0]
        self.assertIsNotNone(crashed["pending_checkpoint_decision"])

        completed = runner.resume(run_id=run_id)

        self.assertEqual("completed", completed["status"])
        plan = StateStore.open(run_root).state["plans"][0]
        self.assertIsNone(plan["pending_checkpoint_decision"])
        self.assertEqual(2, plan["checkpoint_count"])
        decisions = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.checkpoint_decided"
        ]
        self.assertEqual([1, 2], [event["attempt"] for event in decisions])
        self.assertEqual(2, len({event["decision_id"] for event in decisions}))

    def test_crash_after_journal_before_event_reconciles_once(self) -> None:
        original = StateStore.append_event
        injected = False

        def crash_before_event(store: StateStore, action: str, **details: object) -> None:
            nonlocal injected
            if action == "plan.checkpoint_decided" and not injected:
                injected = True
                raise RuntimeError("injected checkpoint crash before event")
            original(store, action, **details)

        self._assert_reconciled_after_crash(
            mock.patch.object(StateStore, "append_event", new=crash_before_event),
            "crash-before-decision-event",
        )

    def test_crash_after_event_before_state_apply_reconciles_once(self) -> None:
        original = StateStore._append_event_bytes
        injected = False

        def crash_after_event(store: StateStore, encoded: bytes) -> None:
            nonlocal injected
            original(store, encoded)
            if b'"action":"plan.checkpoint_decided"' in encoded and not injected:
                injected = True
                raise RuntimeError("injected checkpoint crash after event")

        self._assert_reconciled_after_crash(
            mock.patch.object(StateStore, "_append_event_bytes", new=crash_after_event),
            "crash-after-decision-event",
        )


class Format3StateValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cpe-format-three-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_legacy_state(self, version: int) -> Path:
        run_root = self.root / f"format-{version}"
        run_root.mkdir(mode=0o700)
        state_path = run_root / "state.json"
        state_path.write_text(
            json.dumps({"format_version": version}), encoding="utf-8"
        )
        return state_path

    def test_format_one_and_two_are_rejected_without_mutation(self) -> None:
        for version in (1, 2):
            with self.subTest(version=version):
                state_path = self.write_legacy_state(version)
                before = state_path.read_bytes()
                with self.assertRaisesRegex(ValueError, "unsupported_legacy_run"):
                    StateStore.open(state_path.parent)
                self.assertEqual(before, state_path.read_bytes())


class Format2RecoveryStateValidationTests(_RecoveryRunnerFixture):
    def _active_store(self, run_id: str) -> StateStore:
        source_head = git(self.repo, "rev-parse", "HEAD")
        store = StateStore.create(
            run_root=self.home / "orchestrator" / run_id,
            run_id=run_id,
            source_repository=self.repo,
            source_commit=source_head,
            worktree=self.root / f"{run_id}-worktree",
            branch=f"codex/{run_id}",
            specs=[],
            plans=[self.plan("completed")],
            initial_status="running",
        )
        result = store.root / "results" / "plan-01-attempt-1.json"
        result.write_text("{}", encoding="utf-8")
        plan = store.state["plans"][0]
        plan.update({
            "status": "running",
            "starting_commit": source_head,
            "attempt_count": 1,
            "controller_launch_count": 1,
            "progress_fingerprint": "a" * 64,
            "last_known_head": source_head,
            "result_path": str(result.resolve()),
        })
        store.save()
        return store

    @staticmethod
    def _pending(plan: dict[str, object], **changes: object) -> dict[str, object]:
        pending: dict[str, object] = {
            "decision_id": "b" * 32,
            "plan_id": plan["plan_id"],
            "attempt": 1,
            "decision": "continue",
            "reason": "productive_timeout",
            "progress_fingerprint": "c" * 64,
            "previous_progress_fingerprint": "a" * 64,
            "timed_out": True,
            "head": plan["last_known_head"],
            "evidence_manifest_sha256": None,
        }
        pending.update(changes)
        return pending

    def test_format2_ledger_progress_uses_only_canonical_content_digests(self) -> None:
        store = self._active_store("state-ledger-digests")
        plan = store.state["plans"][0]
        plan["execution_ledger_event_digests"] = ["d" * 64]

        store.save()

        persisted = StateStore.open(store.root).state["plans"][0]
        self.assertEqual(["d" * 64], persisted["execution_ledger_event_digests"])
        self.assertNotIn("execution_ledger_event_ids", persisted)

        before = store.state_path.read_bytes()
        plan["execution_ledger_event_digests"] = ["event-1"]
        with self.assertRaisesRegex(ValueError, "ledger event digests"):
            store.save()
        self.assertEqual(before, store.state_path.read_bytes())

    def test_pending_reason_action_and_active_state_are_strictly_correlated(self) -> None:
        store = self._active_store("state-pending-semantics")
        plan = store.state["plans"][0]
        plan["pending_checkpoint_decision"] = self._pending(plan)

        store.save()

        valid_bytes = store.state_path.read_bytes()
        invalid_cases = (
            {"decision": "finish", "reason": "productive_timeout"},
            {"decision": "checkpoint", "reason": "child_checkpointed", "timed_out": True},
            {"decision": "stop_budget", "reason": "no_progress_timeout"},
            {"previous_progress_fingerprint": "d" * 64},
            {"head": "e" * 40},
            {"progress_fingerprint": "a" * 64},
            {
                "decision": "stop_stalled",
                "reason": "no_progress_timeout",
                "progress_fingerprint": "a" * 64,
            },
            {
                "decision": "stop_budget",
                "reason": "launch_budget_exhausted",
            },
            {
                "decision": "stop_budget",
                "reason": "wall_budget_exhausted",
            },
        )
        for index, changes in enumerate(invalid_cases):
            with self.subTest(index=index):
                candidate = StateStore.open(store.root)
                active = candidate.state["plans"][0]
                active["pending_checkpoint_decision"] = self._pending(active, **changes)
                with self.assertRaisesRegex(ValueError, "pending checkpoint decision"):
                    candidate.save()
                self.assertEqual(valid_bytes, candidate.state_path.read_bytes())

        candidate = StateStore.open(store.root)
        candidate.state["status"] = "checkpointed"
        candidate.state["plans"][0]["status"] = "checkpointed"
        with self.assertRaisesRegex(ValueError, "pending checkpoint decision"):
            candidate.save()
        self.assertEqual(valid_bytes, candidate.state_path.read_bytes())

    def test_every_valid_pending_decision_row_persists(self) -> None:
        cases = (
            ("continue", "productive_timeout", {}, {}),
            (
                "checkpoint", "child_checkpointed",
                {"timed_out": False}, {},
            ),
            ("block", "child_blocked", {"timed_out": False}, {}),
            ("fail", "child_failed", {"timed_out": False}, {}),
            (
                "stop_stalled", "no_progress_timeout",
                {"progress_fingerprint": "a" * 64},
                {},
            ),
            ("stop_stalled", "child_stopped_without_completion", {"timed_out": False}, {}),
            (
                "stop_budget", "launch_budget_exhausted", {},
                {"controller_launch_count": 6},
            ),
            (
                "stop_budget", "wall_budget_exhausted", {},
                {"plan_elapsed_seconds": 7_200},
            ),
            (
                "finish", "child_completed",
                {
                    "timed_out": False,
                    "evidence_manifest_sha256": "d" * 64,
                },
                {},
            ),
        )
        for index, (decision, reason, pending_changes, plan_changes) in enumerate(cases):
            with self.subTest(decision=decision, reason=reason):
                store = self._active_store(f"valid-pending-row-{index}")
                plan = store.state["plans"][0]
                plan.update(plan_changes)
                plan["pending_checkpoint_decision"] = self._pending(
                    plan,
                    decision=decision,
                    reason=reason,
                    **pending_changes,
                )

                store.save()

                persisted = StateStore.open(store.root).state["plans"][0]
                self.assertEqual(
                    (decision, reason),
                    (
                        persisted["pending_checkpoint_decision"]["decision"],
                        persisted["pending_checkpoint_decision"]["reason"],
                    ),
                )

    def test_non_timeout_stalled_decision_rejects_the_wrong_reason(self) -> None:
        store = self._active_store("invalid-nontimeout-stalled-reason")
        valid_bytes = store.state_path.read_bytes()
        plan = store.state["plans"][0]
        plan["pending_checkpoint_decision"] = self._pending(
            plan,
            decision="stop_stalled",
            reason="no_progress_timeout",
            progress_fingerprint="a" * 64,
            timed_out=False,
        )

        with self.assertRaisesRegex(ValueError, "pending checkpoint decision"):
            store.save()
        self.assertEqual(valid_bytes, store.state_path.read_bytes())


class FullActionWalReconciliationTests(_RecoveryRunnerFixture):
    def _crash_after_decision_event(self, expected_decision: str) -> object:
        original = StateStore._append_event_bytes
        injected = False

        def crash(store: StateStore, encoded: bytes) -> None:
            nonlocal injected
            original(store, encoded)
            marker = f'"decision":"{expected_decision}"'.encode()
            if (
                b'"action":"plan.checkpoint_decided"' in encoded
                and marker in encoded
                and not injected
            ):
                injected = True
                raise RuntimeError("injected action WAL crash")

        return mock.patch.object(StateStore, "_append_event_bytes", new=crash)

    def _assert_terminal_action_reconciles(
        self,
        *,
        scenario: str,
        decision: str,
        expected_status: str,
        run_id: str,
        checkpoint_budget: CheckpointBudget | None = None,
    ) -> None:
        runner = self.runner(run_id)
        budget_patch = (
            mock.patch.object(
                runner,
                "_checkpoint_budget",
                return_value=checkpoint_budget,
            )
            if checkpoint_budget is not None
            else contextlib.nullcontext()
        )
        original_persist = runner_module._persist_checkpoint_decision

        def persist_with_actual_budget(
            store: StateStore, checkpoint_decision: object, **kwargs: object,
        ) -> None:
            plan = store.state["plans"][store.state["current_plan_index"]]
            if getattr(checkpoint_decision, "reason_code", None) == "launch_budget_exhausted":
                plan["controller_launch_count"] = plan["budget"]["max_controller_launches"]
            original_persist(store, checkpoint_decision, **kwargs)  # type: ignore[arg-type]

        persist_patch = (
            mock.patch.object(
                runner_module,
                "_persist_checkpoint_decision",
                new=persist_with_actual_budget,
            )
            if checkpoint_budget is not None
            else contextlib.nullcontext()
        )
        with budget_patch, persist_patch, self._crash_after_decision_event(decision), self.assertRaisesRegex(
            RuntimeError, "injected action WAL crash",
        ):
            runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan(scenario)],
                run_id=run_id,
            )
        run_root = self.home / "orchestrator" / run_id
        self.assertIsNotNone(
            StateStore.open(run_root).state["plans"][0]["pending_checkpoint_decision"]
        )
        attempts_before = len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.attempt_started"
        ])

        expected_error = (
            "failed run requires --retry-failed"
            if decision == "fail"
            else "retry-failed requires a failed run"
        )
        with self.assertRaisesRegex(ValueError, expected_error):
            runner.resume(run_id=run_id, retry_failed=decision != "fail")

        reconciled_store = StateStore.open(run_root)
        self.assertEqual(expected_status, reconciled_store.state["status"])
        self.assertEqual(attempts_before, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.attempt_started"
        ]))
        plan = reconciled_store.state["plans"][0]
        self.assertIsNone(plan["pending_checkpoint_decision"])
        self.assertEqual(1, plan["checkpoint_count"])
        decisions = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.checkpoint_decided"
        ]
        self.assertEqual(1, len(decisions))
        self.assertEqual(decision, decisions[0]["decision"])
        secondary_action = {
            "checkpoint": "plan.checkpointed",
            "fail": "plan.failed",
            "block": "plan.blocked",
            "stop_budget": "plan.recovery_stopped",
        }[decision]
        secondary = [
            event for event in _runner_events(run_root)
            if event.get("action") == secondary_action
        ]
        self.assertEqual(1, len(secondary))
        self.assertEqual(decisions[0]["decision_id"], secondary[0]["decision_id"])

    def test_checkpoint_fail_block_and_budget_stop_apply_before_retry_validation(self) -> None:
        cases = (
            ("interrupted", "checkpoint", "checkpointed", "wal-checkpoint", None),
            ("failed", "fail", "failed", "wal-fail", None),
            ("blocked", "block", "blocked", "wal-block", None),
            (
                "interrupted",
                "stop_budget",
                "blocked",
                "wal-stop-budget",
                CheckpointBudget(1, 7_200),
            ),
        )
        for scenario, decision, status, run_id, budget in cases:
            with self.subTest(decision=decision):
                self._assert_terminal_action_reconciles(
                    scenario=scenario,
                    decision=decision,
                    expected_status=status,
                    run_id=run_id,
                    checkpoint_budget=budget,
                )

    def test_continue_action_applies_once_then_launches_only_next_slice(self) -> None:
        run_id = "wal-continue"
        runner = self.runner(run_id)
        with self._crash_after_decision_event("continue"), self.assertRaisesRegex(
            RuntimeError, "injected action WAL crash",
        ):
            runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("timeout_with_progress")],
                run_id=run_id,
            )
        run_root = self.home / "orchestrator" / run_id

        reconciled = runner.resume(run_id=run_id)

        self.assertEqual("completed", reconciled["status"])
        plan = StateStore.open(run_root).state["plans"][0]
        self.assertEqual(2, plan["attempt_count"])
        self.assertEqual(0, plan["checkpoint_count"])
        decisions = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.checkpoint_decided"
        ]
        self.assertEqual([1, 2], [event["attempt"] for event in decisions])
        self.assertEqual(2, len({event["decision_id"] for event in decisions}))
        continuations = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.continuation_scheduled"
        ]
        self.assertEqual(1, len(continuations))
        self.assertEqual(decisions[0]["decision_id"], continuations[0]["decision_id"])

    def test_stalled_stop_applies_before_retry_validation_without_third_launch(self) -> None:
        run_id = "wal-stop-stalled"
        runner = self.runner(run_id)
        with self._crash_after_decision_event("stop_stalled"), self.assertRaisesRegex(
            RuntimeError, "injected action WAL crash",
        ):
            runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("timeout_without_progress")],
                run_id=run_id,
            )
        run_root = self.home / "orchestrator" / run_id

        attempts_before = len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.attempt_started"
        ])
        with self.assertRaisesRegex(ValueError, "retry-failed requires a failed run"):
            runner.resume(run_id=run_id, retry_failed=True)

        stalled_store = StateStore.open(run_root)
        self.assertEqual("blocked", stalled_store.state["status"])
        self.assertEqual(attempts_before, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.attempt_started"
        ]))
        plan = stalled_store.state["plans"][0]
        self.assertEqual(1, plan["attempt_count"])
        self.assertEqual(0, plan["checkpoint_count"])
        self.assertEqual(1, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.checkpoint_decided"
            and event.get("decision") == "stop_stalled"
        ]))
        recovery_events = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.recovery_stopped"
            and event.get("reason") == "no_progress_timeout"
        ]
        self.assertEqual(1, len(recovery_events))

    def test_block_reuses_durable_probe_event_after_secondary_event_crash(self) -> None:
        run_id = "wal-block-secondary-event"
        runner = self.runner(run_id)
        unavailable = CapabilityObservation(
            "loopback_bind", "workspace", "unavailable", "permission_denied",
            "parent_observed", {"host": "127.0.0.1"},
        )
        available = CapabilityObservation(
            "loopback_bind", "workspace", "available", "bound",
            "parent_observed", {"host": "127.0.0.1"},
        )
        original = StateStore._append_event_bytes
        injected = False

        def crash(store: StateStore, encoded: bytes) -> None:
            nonlocal injected
            original(store, encoded)
            if b'"action":"plan.blocked"' in encoded and not injected:
                injected = True
                raise RuntimeError("injected block secondary event crash")

        with (
            mock.patch(
                "cpe_runtime.runner._observe_capabilities",
                return_value=[unavailable],
            ),
            mock.patch.object(StateStore, "_append_event_bytes", new=crash),
            self.assertRaisesRegex(RuntimeError, "injected block secondary event crash"),
        ):
            runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("blocked", loopback=True)],
                run_id=run_id,
            )
        run_root = self.home / "orchestrator" / run_id

        with mock.patch(
            "cpe_runtime.runner._observe_capabilities",
            return_value=[available],
        ):
            with self.assertRaisesRegex(
                ValueError, "retry-failed requires a failed run",
            ):
                runner.resume(run_id=run_id, retry_failed=True)

        self.assertEqual("blocked", StateStore.open(run_root).state["status"])
        self.assertEqual(1, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.attempt_started"
        ]))
        plan = StateStore.open(run_root).state["plans"][0]
        self.assertIsNotNone(plan["environment_fingerprint"])
        events = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.blocked"
        ]
        self.assertEqual(1, len(events))
        self.assertIs(events[0]["parent_confirmed"], True)


class BranchHandoffTests(_RecoveryRunnerFixture):
    def runner(self, run_id: str) -> SequentialRunner:
        return super().runner(run_id, accelerated_timeout=1.0)

    def test_completion_persists_truthful_immutable_handoff_before_state(self) -> None:
        run_id = "branch-handoff-complete"
        runner = self.runner(run_id)
        original_save = StateStore.save
        observed_completed_save = False

        def assert_handoff_precedes_completed_state(store: StateStore) -> None:
            nonlocal observed_completed_save
            if store.state.get("status") == "completed":
                handoff = store.root / "results" / "branch-handoff.json"
                self.assertTrue(handoff.is_file())
                self.assertEqual(0o400, stat.S_IMODE(handoff.stat().st_mode))
                observed_completed_save = True
            original_save(store)

        with mock.patch.object(
            StateStore, "save", new=assert_handoff_precedes_completed_state,
        ):
            completed = runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("completed")],
                run_id=run_id,
            )

        self.assertEqual("completed", completed["status"])
        self.assertTrue(observed_completed_save)
        run_root = self.home / "orchestrator" / run_id
        state = StateStore.open(run_root).state
        handoff_path = run_root / "results" / "branch-handoff.json"
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        plan = state["plans"][0]

        self.assertEqual({
            "format_version", "run_id", "branch", "saved_worktree",
            "observed_head", "last_known_head", "base_commit", "plan_results",
            "open_finding_ids", "open_obligation_ids", "integration",
        }, set(handoff))
        self.assertEqual(2, handoff["format_version"])
        self.assertEqual(run_id, handoff["run_id"])
        self.assertEqual(state["branch"], handoff["branch"])
        self.assertEqual(state["worktree"], handoff["saved_worktree"])
        self.assertEqual(plan["accepted_commit"], handoff["observed_head"])
        self.assertEqual(plan["last_known_head"], handoff["last_known_head"])
        self.assertEqual(state["source_commit"], handoff["base_commit"])
        self.assertEqual([], handoff["open_finding_ids"])
        self.assertEqual([], handoff["open_obligation_ids"])
        self.assertEqual(
            {"status": "not_observed", "receipt": None},
            handoff["integration"],
        )
        self.assertEqual(1, len(handoff["plan_results"]))
        plan_handoff = handoff["plan_results"][0]
        self.assertEqual({
            "plan_id", "result_ref", "accepted_commit", "final_review_ref",
            "final_review_head", "acceptance_evidence_ref",
            "verification_receipt_refs", "open_finding_ids",
            "open_obligation_ids",
        }, set(plan_handoff))
        self.assertEqual("plan-01", plan_handoff["plan_id"])
        self.assertEqual(
            Path(plan["result_path"]).resolve().relative_to(
                run_root.resolve()
            ).as_posix(),
            plan_handoff["result_ref"],
        )
        self.assertEqual(plan["accepted_commit"], plan_handoff["accepted_commit"])
        self.assertEqual(
            ".superpowers/sdd/final-review.md",
            plan_handoff["final_review_ref"],
        )
        self.assertEqual(plan["accepted_commit"], plan_handoff["final_review_head"])
        self.assertEqual(
            "evidence/plan-01/evidence-manifest.json",
            plan_handoff["acceptance_evidence_ref"],
        )
        self.assertEqual([], plan_handoff["verification_receipt_refs"])
        self.assertEqual([], plan_handoff["open_finding_ids"])
        self.assertEqual([], plan_handoff["open_obligation_ids"])
        self.assertNotIn("summary", handoff_path.read_text(encoding="utf-8"))

    def test_missing_worktree_never_substitutes_base_or_last_known_head(self) -> None:
        run_id = "branch-handoff-missing-worktree"
        runner = self.runner(run_id)
        completed = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("completed")],
            run_id=run_id,
        )
        self.assertEqual("completed", completed["status"])
        store = StateStore.open(self.home / "orchestrator" / run_id)
        worktree = Path(store.state["worktree"])
        shutil.rmtree(worktree)

        handoff = runner._branch_handoff_payload(store)

        self.assertIsNone(handoff["observed_head"])
        self.assertEqual(
            store.state["plans"][-1]["last_known_head"],
            handoff["last_known_head"],
        )
        self.assertEqual(store.state["source_commit"], handoff["base_commit"])

    def test_existing_handoff_is_reused_only_when_exact_and_immutable(self) -> None:
        run_id = "branch-handoff-reuse"
        runner = self.runner(run_id)
        completed = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("completed")],
            run_id=run_id,
        )
        self.assertEqual("completed", completed["status"])
        store = StateStore.open(self.home / "orchestrator" / run_id)
        handoff_path = store.root / "results" / "branch-handoff.json"

        self.assertEqual(handoff_path.resolve(), runner._materialize_branch_handoff(store))
        handoff_path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "branch handoff"):
            runner._materialize_branch_handoff(store)


class ReconciledResumeDispatchTests(_RecoveryRunnerFixture):
    @staticmethod
    def _crash_after_decision(expected_decision: str) -> object:
        original = StateStore._append_event_bytes
        injected = False

        def crash(store: StateStore, encoded: bytes) -> None:
            nonlocal injected
            original(store, encoded)
            if (
                b'"action":"plan.checkpoint_decided"' in encoded
                and f'"decision":"{expected_decision}"'.encode() in encoded
                and not injected
            ):
                injected = True
                raise RuntimeError("injected resume dispatch crash")

        return mock.patch.object(StateStore, "_append_event_bytes", new=crash)

    def test_reconciled_finish_continues_the_next_plan_in_same_resume(self) -> None:
        run_id = "resume-finish-next-plan"
        runner = self.runner(run_id)
        with self._crash_after_decision("finish"), self.assertRaisesRegex(
            RuntimeError, "injected resume dispatch crash",
        ):
            runner.run(
                workspace=self.repo,
                specs=[],
                plans=[
                    self.plan("completed", number=1),
                    self.plan("completed", number=2),
                ],
                run_id=run_id,
            )

        completed = runner.resume(run_id=run_id)

        run_root = self.home / "orchestrator" / run_id
        self.assertEqual("completed", completed["status"])
        self.assertEqual([1, 1], [
            plan["attempt_count"] for plan in StateStore.open(run_root).state["plans"]
        ])
        self.assertEqual(2, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.attempt_started"
        ]))
        self.assertEqual(1, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "run.completed"
        ]))
        self.assertTrue((run_root / "reports" / "optimization-report.json").is_file())
        self.assertTrue((run_root / "reports" / "optimization-report.md").is_file())

    def test_reconciled_fail_consumes_only_explicit_retry(self) -> None:
        retry_id = "resume-pending-fail-retry"
        retry_runner = self.runner(retry_id)
        with self._crash_after_decision("fail"), self.assertRaisesRegex(
            RuntimeError, "injected resume dispatch crash",
        ):
            retry_runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("retryable_then_completed")],
                run_id=retry_id,
            )

        completed = retry_runner.resume(run_id=retry_id, retry_failed=True)

        retry_root = self.home / "orchestrator" / retry_id
        self.assertEqual("completed", completed["status"])
        self.assertEqual(1, fake_codex_launch_count(retry_root))
        self.assertEqual(2, StateStore.open(retry_root).state["plans"][0]["attempt_count"])
        self.invocations.unlink()

        no_retry_id = "resume-pending-fail-no-retry"
        no_retry_runner = self.runner(no_retry_id)
        with self._crash_after_decision("fail"), self.assertRaisesRegex(
            RuntimeError, "injected resume dispatch crash",
        ):
            no_retry_runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("retryable_then_completed", number=2)],
                run_id=no_retry_id,
            )
        with self.assertRaisesRegex(ValueError, "requires --retry-failed"):
            no_retry_runner.resume(run_id=no_retry_id)
        no_retry_root = self.home / "orchestrator" / no_retry_id
        self.assertEqual("failed", StateStore.open(no_retry_root).state["status"])
        self.assertEqual(1, len([
            event for event in _runner_events(no_retry_root)
            if event.get("action") == "plan.attempt_started"
        ]))

    def test_retry_failed_is_rejected_for_reconciled_nonfailed_actions(self) -> None:
        cases = (
            ("interrupted", "checkpoint", 1),
            ("blocked", "block", 1),
            ("timeout_without_progress", "stop_stalled", 2),
        )
        for scenario, decision, attempts in cases:
            with self.subTest(decision=decision):
                run_id = f"invalid-retry-{decision}"
                runner = self.runner(run_id)
                with self._crash_after_decision(decision), self.assertRaisesRegex(
                    RuntimeError, "injected resume dispatch crash",
                ):
                    runner.run(
                        workspace=self.repo,
                        specs=[],
                        plans=[self.plan(scenario)],
                        run_id=run_id,
                    )
                with self.assertRaisesRegex(
                    ValueError, "retry-failed requires a failed run",
                ):
                    runner.resume(run_id=run_id, retry_failed=True)
                run_root = self.home / "orchestrator" / run_id
                self.assertEqual(attempts, len([
                    event for event in _runner_events(run_root)
                    if event.get("action") == "plan.attempt_started"
                ]))

    def test_mismatched_run_completion_event_fails_closed(self) -> None:
        run_id = "mismatched-run-completion"
        runner = self.runner(run_id)
        completed = runner.run(
            workspace=self.repo,
            specs=[],
            plans=[self.plan("completed")],
            run_id=run_id,
        )
        self.assertEqual("completed", completed["status"])
        run_root = self.home / "orchestrator" / run_id
        store = StateStore.open(run_root)
        state_before = store.state_path.read_bytes()
        events = _runner_events(run_root)
        completion = next(
            event for event in events if event.get("action") == "run.completed"
        )
        completion["head"] = "0" * 40
        store.events_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "run.completed"):
            runner.resume(run_id=run_id)

        self.assertEqual(state_before, store.state_path.read_bytes())

    def test_run_completion_envelope_mutations_fail_closed(self) -> None:
        mutations = (
            ("missing-event-id", lambda event: event.pop("event_id")),
            ("malformed-at", lambda event: event.__setitem__("at", "not-a-time")),
            ("extra-field", lambda event: event.__setitem__("extra", True)),
            ("malformed-event-id", lambda event: event.__setitem__("event_id", "bad-id")),
        )
        for index, (label, mutate) in enumerate(mutations, 1):
            with self.subTest(mutation=label):
                run_id = f"run-completion-envelope-{index}"
                runner = self.runner(run_id)
                completed = runner.run(
                    workspace=self.repo,
                    specs=[],
                    plans=[self.plan("completed", number=index)],
                    run_id=run_id,
                )
                self.assertEqual("completed", completed["status"])
                run_root = self.home / "orchestrator" / run_id
                store = StateStore.open(run_root)
                events = _runner_events(run_root)
                completion = next(
                    event for event in events
                    if event.get("action") == "run.completed"
                )
                mutate(completion)
                store.events_path.write_text(
                    "".join(
                        json.dumps(event, sort_keys=True) + "\n"
                        for event in events
                    ),
                    encoding="utf-8",
                )
                state_before = store.state_path.read_bytes()
                events_before = store.events_path.read_bytes()

                with self.assertRaisesRegex(ValueError, "run.completed"):
                    runner.resume(run_id=run_id)

                self.assertEqual(state_before, store.state_path.read_bytes())
                self.assertEqual(events_before, store.events_path.read_bytes())


class FinishWalAndEvidenceTests(_RecoveryRunnerFixture):
    def _assert_finish_crash_converges(self, patcher: object, run_id: str) -> None:
        runner = self.runner(run_id)
        with patcher, self.assertRaisesRegex(RuntimeError, "injected finish crash"):
            runner.run(
                workspace=self.repo,
                specs=[],
                plans=[self.plan("completed")],
                run_id=run_id,
            )
        run_root = self.home / "orchestrator" / run_id

        completed = runner.resume(run_id=run_id)

        self.assertEqual("completed", completed["status"])
        self.assertEqual(1, len([
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.attempt_started"
        ]))
        state = StateStore.open(run_root).state
        plan = state["plans"][0]
        self.assertIsNone(plan["pending_checkpoint_decision"])
        self.assertEqual(1, plan["attempt_count"])
        self.assertEqual(1, plan["checkpoint_count"])
        decisions = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.checkpoint_decided"
        ]
        completed_events = [
            event for event in _runner_events(run_root)
            if event.get("action") == "plan.completed"
        ]
        self.assertEqual(1, len(decisions))
        self.assertEqual(1, len(completed_events))
        self.assertEqual(decisions[0]["decision_id"], completed_events[0]["decision_id"])
        run_completed = [
            event for event in _runner_events(run_root)
            if event.get("action") == "run.completed"
        ]
        self.assertEqual(1, len(run_completed))
        self.assertEqual(plan["accepted_commit"], run_completed[0]["head"])
        report_json = run_root / "reports" / "optimization-report.json"
        report_markdown = run_root / "reports" / "optimization-report.md"
        self.assertTrue(report_json.is_file())
        self.assertTrue(report_markdown.is_file())
        self.assertEqual(run_id, json.loads(report_json.read_text())["run_id"])
        evidence = run_root / "evidence" / "plan-01"
        self.assertTrue((evidence / "evidence-manifest.json").is_file())
        self.assertEqual(1, len([
            path for path in (run_root / "evidence").iterdir()
            if path.name == "plan-01"
        ]))

    def test_finish_crash_after_journal_save_converges(self) -> None:
        original = StateStore.save
        injected = False

        def crash(store: StateStore) -> None:
            nonlocal injected
            original(store)
            plans = store.state.get("plans", [])
            pending = plans[0].get("pending_checkpoint_decision") if plans else None
            if isinstance(pending, dict) and pending.get("decision") == "finish" and not injected:
                injected = True
                self.assertFalse((store.root / "evidence" / "plan-01").exists())
                raise RuntimeError("injected finish crash after journal save")

        self._assert_finish_crash_converges(
            mock.patch.object(StateStore, "save", new=crash),
            "finish-crash-journal",
        )

    def test_finish_crash_after_decision_event_converges(self) -> None:
        original = StateStore._append_event_bytes
        injected = False

        def crash(store: StateStore, encoded: bytes) -> None:
            nonlocal injected
            original(store, encoded)
            if (
                b'"action":"plan.checkpoint_decided"' in encoded
                and b'"decision":"finish"' in encoded
                and not injected
            ):
                injected = True
                self.assertFalse((store.root / "evidence" / "plan-01").exists())
                raise RuntimeError("injected finish crash after decision event")

        self._assert_finish_crash_converges(
            mock.patch.object(StateStore, "_append_event_bytes", new=crash),
            "finish-crash-event",
        )

    def test_finish_crash_after_evidence_publish_converges(self) -> None:
        original = runner_module.ingest_plan_evidence
        injected = False

        def crash(**kwargs: object) -> dict[str, object]:
            nonlocal injected
            manifest = original(**kwargs)  # type: ignore[arg-type]
            if not injected:
                injected = True
                raise RuntimeError("injected finish crash after evidence publish")
            return manifest

        self._assert_finish_crash_converges(
            mock.patch.object(runner_module, "ingest_plan_evidence", new=crash),
            "finish-crash-evidence",
        )

    def test_finish_crash_after_state_commit_converges(self) -> None:
        original = StateStore.save
        injected = False

        def crash(store: StateStore) -> None:
            nonlocal injected
            original(store)
            if store.state.get("status") == "completed" and not injected:
                injected = True
                raise RuntimeError("injected finish crash after state commit")

        self._assert_finish_crash_converges(
            mock.patch.object(StateStore, "save", new=crash),
            "finish-crash-state",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
