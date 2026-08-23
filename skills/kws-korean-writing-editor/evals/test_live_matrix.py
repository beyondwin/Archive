from __future__ import annotations

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live_matrix  # noqa: E402


def case_by_id(case_id: str) -> live_matrix.LiveCase:
    return next(
        case for case in live_matrix.load_live_cases(HERE / "live_cases.json")
        if case.id == case_id
    )


class LiveCaseManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = live_matrix.load_live_cases(HERE / "live_cases.json")

    def test_approved_shape(self) -> None:
        self.assertEqual(len(self.cases), 14)
        self.assertEqual(sum(case.repeats for case in self.cases), 17)
        self.assertEqual(
            {case.id for case in self.cases if case.repeats == 2},
            {"correct-obligation", "structure-embedded-instruction", "near-detector-author"},
        )
        self.assertEqual(
            {case.band for case in self.cases},
            {"valid-mode", "preservation", "noop-hold", "near-miss"},
        )

    def test_synthetic_only(self) -> None:
        for case in self.cases:
            self.assertTrue(case.request)
            self.assertNotIn("/Users/", case.request)
            self.assertNotIn("CANARY", case.request)
            self.assertNotIn("skill_used", case.request)

    def test_approved_values_reject_manifest_drift(self) -> None:
        manifest = json.loads((HERE / "live_cases.json").read_text(encoding="utf-8"))
        manifest["cases"][0]["exact_output"] = None
        with tempfile.TemporaryDirectory() as directory:
            mutated = pathlib.Path(directory) / "live_cases.json"
            mutated.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                live_matrix.load_live_cases(mutated)

    def test_producer_plan_count(self) -> None:
        producers = live_matrix.build_producers()
        plan = live_matrix.build_producer_plan(self.cases, producers)
        self.assertEqual(len(producers), 7)
        self.assertEqual(len(plan), 119)
        self.assertEqual(len({call.call_id for call in plan}), 119)

    def test_dry_run_has_no_subprocess(self) -> None:
        output = io.StringIO()
        with mock.patch("live_matrix.subprocess.run") as run:
            with contextlib.redirect_stdout(output):
                status = live_matrix.main(["--dry-run"])
        self.assertEqual(status, 0)
        run.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual(
            (payload["producer_calls"], payload["reviewer_calls"], payload["baseline_calls"], payload["approved_total_ceiling"]),
            (119, 3, 122, 160),
        )


class DeterministicEvaluationTests(unittest.TestCase):
    def test_exact_body_passes(self) -> None:
        case = case_by_id("correct-obligation")
        result = live_matrix.evaluate_response(
            case, "이 기능은 사용할 수 있지만 반드시 켤 필요는 없습니다.\n"
        )
        self.assertEqual(result, ())

    def test_preamble_is_not_normalized_away(self) -> None:
        case = case_by_id("correct-obligation")
        response = "수정본입니다.\n이 기능은 사용할 수 있지만 반드시 켤 필요는 없습니다."
        self.assertTrue(live_matrix.normalize_response(response).startswith("수정본입니다."))
        codes = {finding.code for finding in live_matrix.evaluate_response(case, response)}
        self.assertIn("exact_output_mismatch", codes)
        self.assertIn("forbidden_substring", codes)

    def test_occurrence_count_detects_removed_attribution(self) -> None:
        case = case_by_id("preserve-literals-attribution")
        response = "2026-08-23에 김민수가 “40명 모두 확인했습니다”라고 기록했고 v2.1.0 배포를 보류했다."
        findings = live_matrix.evaluate_response(case, response)
        self.assertTrue(
            any(
                finding.code == "occurrence_count_changed" and finding.literal == "박지영"
                for finding in findings
            )
        )

    def test_structure_and_embedded_command_are_required(self) -> None:
        case = case_by_id("structure-embedded-instruction")
        codes = {
            finding.code
            for finding in live_matrix.evaluate_response(
                case, "배포 메모:\n`state.json`은 원본이 아니다."
            )
        }
        self.assertIn("missing_structural_sentinel", codes)
        self.assertIn("missing_required_substring", codes)

    def test_diagnose_full_rewrite_fails(self) -> None:
        case = case_by_id("diagnose-no-rewrite")
        findings = live_matrix.evaluate_response(case, "지금 상태에선 배포할 수 있다.")
        self.assertIn("forbidden_exact_output", {finding.code for finding in findings})

    def test_near_miss_activation_is_partial(self) -> None:
        self.assertEqual(
            live_matrix.case_status(case_by_id("near-casual"), ()),
            "partially_verified",
        )


class ProviderAdapterTests(unittest.TestCase):
    def test_codex_argv_is_direct_ephemeral_read_only(self) -> None:
        argv = live_matrix.build_codex_argv(pathlib.Path("/repo"), "prompt")
        self.assertEqual(
            argv,
            (
                "codex",
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--json",
                "--cd",
                "/repo",
                "prompt",
            ),
        )
        self.assertNotIn("--model", argv)

    def test_cursor_argv_is_sandboxed_ask_and_not_forced(self) -> None:
        argv = live_matrix.build_cursor_argv(
            pathlib.Path("/repo"), "gemini-3.7-flash-high", "prompt"
        )
        self.assertEqual(
            argv,
            (
                "cursor-agent",
                "--print",
                "--output-format",
                "json",
                "--mode",
                "ask",
                "--sandbox",
                "enabled",
                "--workspace",
                "/repo",
                "--model",
                "gemini-3.7-flash-high",
                "prompt",
            ),
        )
        self.assertNotIn("--force", argv)
        self.assertNotIn("--yolo", argv)

    def test_host_prefixes_only_explicit_cases(self) -> None:
        case = case_by_id("correct-obligation")
        self.assertTrue(
            live_matrix.build_prompt(case, "codex").startswith(
                "$kws-korean-writing-editor "
            )
        )
        self.assertTrue(
            live_matrix.build_prompt(case, "cursor").startswith(
                "/kws-korean-writing-editor "
            )
        )
        self.assertEqual(
            live_matrix.build_prompt(case_by_id("near-casual"), "codex"),
            "안녕! 오늘 날씨 좋지 않아?",
        )

    def test_codex_jsonl_extracts_final_message_and_model(self) -> None:
        payload = (
            b'{"type":"turn.started","model":"gpt-example"}\n'
            b'{"type":"item.completed","item":{"type":"agent_message","text":"first"}}\n'
            b'{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n'
        )
        self.assertEqual(
            live_matrix.extract_codex_response(payload), ("done", "gpt-example")
        )

    def test_codex_jsonl_ignores_nested_model_and_non_messages(self) -> None:
        payload = (
            b'{"type":"turn.started","nested":{"model":"untrusted"},"turn_context":{"model":"context-model"}}\n'
            b'{"type":"item.completed","item":{"type":"tool","text":"ignore"}}\n'
            b'{"type":"item.completed","item":{"type":"agent_message","text":"final"}}\n'
        )
        self.assertEqual(
            live_matrix.extract_codex_response(payload), ("final", "context-model")
        )

    def test_cursor_json_keeps_preamble(self) -> None:
        payload = json.dumps(
            {"type": "result", "result": "수정본입니다.\n완료", "model": "m"},
            ensure_ascii=False,
        ).encode()
        self.assertEqual(
            live_matrix.extract_cursor_response(payload), ("수정본입니다.\n완료", "m")
        )

    def test_cursor_rejects_nested_response_strings(self) -> None:
        payload = json.dumps({"nested": {"result": "not accepted"}}).encode()
        with self.assertRaisesRegex(live_matrix.LiveMatrixError, "response"):
            live_matrix.extract_cursor_response(payload)

    def test_run_command_uses_bounded_direct_subprocess_and_preserves_nonzero(self) -> None:
        completed = subprocess.CompletedProcess(
            ("provider", "prompt"), 7, stdout=b"out", stderr=b"err"
        )
        with mock.patch("live_matrix.time.monotonic", side_effect=(10.0, 10.012)):
            with mock.patch("live_matrix.subprocess.run", return_value=completed) as run:
                capture = live_matrix.run_command(
                    ("provider", "prompt"), cwd=pathlib.Path("/repo"), timeout=12
                )
        self.assertEqual(capture, live_matrix.CommandCapture(7, b"out", b"err", 12))
        args, kwargs = run.call_args
        self.assertEqual(args, (["provider", "prompt"],))
        self.assertEqual(kwargs["cwd"], pathlib.Path("/repo"))
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.PIPE)
        self.assertEqual(kwargs["timeout"], 12)
        self.assertFalse(kwargs["check"])
        self.assertNotIn("shell", kwargs)

    def test_run_command_converts_timeout(self) -> None:
        with mock.patch(
            "live_matrix.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["provider"], 12),
        ):
            with self.assertRaisesRegex(live_matrix.LiveMatrixError, "timed out"):
                live_matrix.run_command(("provider",), cwd=pathlib.Path("/repo"))

    def test_run_command_rejects_each_oversized_stream(self) -> None:
        for stdout, stderr in (
            (b"x" * 131_073, b""),
            (b"", b"x" * 131_073),
        ):
            completed = subprocess.CompletedProcess(("provider",), 0, stdout, stderr)
            with self.subTest(stdout=bool(stdout)):
                with mock.patch("live_matrix.subprocess.run", return_value=completed):
                    with self.assertRaisesRegex(live_matrix.LiveMatrixError, "exceeded"):
                        live_matrix.run_command(("provider",), cwd=pathlib.Path("/repo"))

    def test_diagnostic_redacts_before_tail(self) -> None:
        data = b"OPENAI_API_KEY=plain-secret Bearer bearer-secret sk-secret-1234567890"
        message = live_matrix.redacted_diagnostic("stderr", data)
        self.assertNotIn("plain-secret", message)
        self.assertNotIn("bearer-secret", message)
        self.assertNotIn("sk-secret", message)
        self.assertIn("sha256=", message)


class ReceiptAndBudgetTests(unittest.TestCase):
    def test_manifest_hash_changes_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "a.txt").write_text("one", encoding="utf-8")
            before = live_matrix.recursive_manifest_hash(root)
            (root / "a.txt").write_text("two", encoding="utf-8")
            self.assertNotEqual(before, live_matrix.recursive_manifest_hash(root))

    def test_manifest_hash_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "target.txt").write_text("one", encoding="utf-8")
            (root / "link.txt").symlink_to(root / "target.txt")
            with self.assertRaisesRegex(live_matrix.LiveMatrixError, "symlink"):
                live_matrix.recursive_manifest_hash(root)

    def test_receipt_is_exclusive_and_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "receipt.json"
            receipt = live_matrix.CallReceipt.for_test("call-1")
            live_matrix.write_receipt(path, receipt)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(live_matrix.LiveMatrixError):
                live_matrix.write_receipt(path, receipt)

    def test_matching_complete_receipt_is_skipped_but_drift_fails(self) -> None:
        identity = live_matrix.RunIdentity.for_test(skill_hash="same")
        plan = (live_matrix.PlannedCall("c", "producer", "p", "x", 1),)
        receipt = live_matrix.CallReceipt.for_test("c", identity=identity, status="verified")
        self.assertEqual(live_matrix.remaining_calls(plan, {"c": receipt}, identity), ())
        with self.assertRaises(live_matrix.LiveMatrixError):
            live_matrix.remaining_calls(
                plan,
                {"c": receipt},
                live_matrix.RunIdentity.for_test(skill_hash="different"),
            )

    def test_budget_counts_blocked_attempts(self) -> None:
        budget = live_matrix.CallBudget(ceiling=2, attempted=1)
        self.assertEqual(budget.reserve(), 2)
        with self.assertRaises(live_matrix.LiveMatrixError):
            budget.reserve()
        self.assertEqual(budget.attempted, 2)

    def test_jobs_above_four_fail(self) -> None:
        self.assertIn("jobs must be between 1 and 4", live_matrix.validate_jobs(5))


class LiveMatrixCliTests(unittest.TestCase):
    def test_baseline_requires_execute(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                live_matrix.main(["--scope", "baseline", "--run-id", "baseline-1"])

    def test_baseline_max_cannot_exceed_122(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                live_matrix.main(
                    [
                        "--execute",
                        "--scope",
                        "baseline",
                        "--run-id",
                        "baseline-1",
                        "--max-calls",
                        "123",
                    ]
                )

    def test_global_max_cannot_exceed_160(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                live_matrix.main(
                    [
                        "--execute",
                        "--scope",
                        "remediation",
                        "--run-id",
                        "remediation-1",
                        "--max-calls",
                        "161",
                    ]
                )

    def test_source_install_mismatch_prevents_mocked_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            installed = root / "installed"
            source.mkdir()
            installed.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: kws-korean-writing-editor\n---\nsource\n", encoding="utf-8"
            )
            (installed / "SKILL.md").write_text(
                "---\nname: kws-korean-writing-editor\n---\ninstalled\n", encoding="utf-8"
            )
            with mock.patch("live_matrix.dispatch_calls") as dispatch:
                with contextlib.redirect_stderr(io.StringIO()):
                    status = live_matrix.main(
                        [
                            "--execute",
                            "--scope",
                            "baseline",
                            "--run-id",
                            "baseline-1",
                            "--source-skill-root",
                            str(source),
                            "--installed-skill-root",
                            str(installed),
                            "--repository-root",
                            str(root),
                        ]
                    )
                self.assertEqual(status, 1)
                dispatch.assert_not_called()


class LiveMatrixLifecycleTests(unittest.TestCase):
    def test_baseline_preflight_is_accepted_without_execute(self) -> None:
        with mock.patch("live_matrix.validate_preflight") as preflight:
            preflight.return_value = mock.Mock(
                identity=live_matrix.RunIdentity.for_test(run_id="baseline-1"),
                model_availability={},
            )
            with contextlib.redirect_stdout(io.StringIO()):
                status = live_matrix.main(
                    ["--preflight", "--scope", "baseline", "--run-id", "baseline-1"]
                )
        self.assertEqual(status, 0)
        self.assertFalse(preflight.call_args.kwargs["resume"])

    def test_preflight_state_is_reused_by_non_resume_execute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            evidence_root = root / "evidence"
            with mock.patch("live_matrix.validate_evidence_root", return_value=evidence_root):
                first = live_matrix._run_root(
                    evidence_root, "baseline-1", repository_root=root, require_existing=False
                )
                (first / "preflight.json").write_text("{}", encoding="utf-8")
                reused = live_matrix._run_root(
                    evidence_root, "baseline-1", repository_root=root, require_existing=True
                )
        self.assertEqual(reused, first)

    def test_execute_reuses_preflight_without_resume(self) -> None:
        preflight_result = mock.Mock(
            identity=live_matrix.RunIdentity.for_test(run_id="baseline-1"),
            model_availability={},
        )
        with mock.patch("live_matrix.validate_preflight", return_value=preflight_result) as preflight:
            with mock.patch("live_matrix.dispatch_calls", return_value=()) as dispatch:
                with contextlib.redirect_stdout(io.StringIO()):
                    status = live_matrix.main(
                        ["--execute", "--scope", "baseline", "--run-id", "baseline-1"]
                    )
        self.assertEqual(status, 0)
        self.assertTrue(preflight.call_args.kwargs["reuse_preflight"])
        dispatch.assert_called_once()

    def test_receipt_round_trips_every_required_field(self) -> None:
        receipt = live_matrix.CallReceipt.for_test("call-1", repeat_index=2)
        self.assertEqual(live_matrix._receipt_from_json(receipt.as_json()), receipt)

    def test_unordered_attempt_files_keep_latest_receipt_and_max_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_root = pathlib.Path(directory)
            receipt_root = run_root / live_matrix.RECEIPT_DIRECTORY_NAME
            receipt_root.mkdir()
            first = live_matrix.CallReceipt.for_test("c", status="blocked", call_number=1)
            retry = live_matrix.CallReceipt.for_test(
                "c:attempt-2", status="verified", call_number=7
            )
            live_matrix.write_receipt(receipt_root / "z-first.json", first)
            live_matrix.write_receipt(receipt_root / "a-retry.json", retry)
            latest = live_matrix._load_receipts(run_root)
            attempts = live_matrix._load_receipt_attempts(run_root)
        self.assertEqual(latest, {"c": retry})
        self.assertEqual(live_matrix.attempted_call_count(attempts), 7)

    def test_duplicate_reserved_call_number_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_root = pathlib.Path(directory)
            receipt_root = run_root / live_matrix.RECEIPT_DIRECTORY_NAME
            receipt_root.mkdir()
            live_matrix.write_receipt(
                receipt_root / "first.json", live_matrix.CallReceipt.for_test("c", call_number=1)
            )
            live_matrix.write_receipt(
                receipt_root / "retry.json",
                live_matrix.CallReceipt.for_test("c:attempt-2", call_number=1),
            )
            with self.assertRaisesRegex(live_matrix.LiveMatrixError, "call number"):
                live_matrix._load_receipt_attempts(run_root)

    def test_evidence_root_rejects_outside_and_does_not_chmod_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            outside = root.parent
            with mock.patch("live_matrix.os.chmod") as chmod:
                with self.assertRaisesRegex(live_matrix.LiveMatrixError, "evidence root"):
                    live_matrix.validate_evidence_root(outside, root)
            chmod.assert_not_called()

    def test_evidence_root_rejects_symlinked_ancestor_escape_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = pathlib.Path(directory)
            repository = sandbox / "repository"
            outside = sandbox / "outside"
            repository.mkdir()
            outside.mkdir()
            (repository / ".superpowers").symlink_to(outside, target_is_directory=True)
            evidence_root = repository / ".superpowers" / "kws-korean-writing-editor" / "live"
            before = tuple(outside.iterdir())
            with mock.patch(
                "live_matrix.run_command",
                return_value=live_matrix.CommandCapture(0, b"", b"", 0),
            ):
                with self.assertRaisesRegex(live_matrix.LiveMatrixError, "beneath repository"):
                    live_matrix.validate_evidence_root(evidence_root, repository)
            self.assertEqual(tuple(outside.iterdir()), before)

    def test_dispatch_identity_rejects_head_and_case_drift(self) -> None:
        identity = live_matrix.RunIdentity.for_test(repository_head="old", live_cases_hash="old-cases")
        preflight = live_matrix.PreflightResult(
            identity=identity,
            repository_root=pathlib.Path("/repo"),
            repository_branch="main",
            source_skill_root=pathlib.Path("/source"),
            installed_skill_root=pathlib.Path("/installed"),
            run_root=pathlib.Path("/run"),
            cli_info={},
            model_availability={},
            discovery_sha256=None,
            discovery_diagnostic=None,
        )
        with mock.patch("live_matrix._git_status_is_clean", return_value=True):
            with mock.patch("live_matrix._git_value", return_value="new"):
                with self.assertRaisesRegex(live_matrix.LiveMatrixError, "identity drift"):
                    live_matrix.validate_dispatch_identity(preflight)

    def test_dispatch_identity_rejects_case_drift(self) -> None:
        identity = live_matrix.RunIdentity.for_test(
            repository_head="same", skill_hash="same", installed_skill_hash="same", live_cases_hash="old-cases"
        )
        preflight = live_matrix.PreflightResult(
            identity=identity,
            repository_root=pathlib.Path("/repo"),
            repository_branch="main",
            source_skill_root=pathlib.Path("/source"),
            installed_skill_root=pathlib.Path("/installed"),
            run_root=pathlib.Path("/run"),
            cli_info={},
            model_availability={},
            discovery_sha256=None,
            discovery_diagnostic=None,
        )
        with mock.patch("live_matrix._git_status_is_clean", return_value=True):
            with mock.patch("live_matrix._git_value", return_value="same"):
                with mock.patch("live_matrix.recursive_manifest_hash", return_value="same"):
                    with mock.patch("live_matrix._sha256_file", return_value="new-cases"):
                        with mock.patch.object(pathlib.Path, "is_symlink", return_value=False):
                            with mock.patch.object(pathlib.Path, "is_file", return_value=True):
                                with self.assertRaisesRegex(live_matrix.LiveMatrixError, "live cases changed"):
                                    live_matrix.validate_dispatch_identity(preflight)

    def test_failed_model_discovery_never_marks_stdout_model_available(self) -> None:
        cursor = live_matrix.CliInfo("cursor-agent", "v", None)
        capture = live_matrix.CommandCapture(
            1, b"gemini-3.7-flash-high", b"unavailable", 1
        )
        with mock.patch("live_matrix.run_command", return_value=capture):
            discovery, _ = live_matrix._discover_models(cursor, pathlib.Path("/repo"))
        self.assertIsNone(discovery)

    def test_crashed_receipt_write_never_publishes_partial_final_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "receipt.json"
            receipt = live_matrix.CallReceipt.for_test("call-1")
            with mock.patch("live_matrix.os.write", return_value=0):
                with self.assertRaisesRegex(live_matrix.LiveMatrixError, "incomplete"):
                    live_matrix.write_receipt(path, receipt)
            self.assertFalse(path.exists())


def synthetic_receipts_for_test(failure_classes: int, passing_bands: int):
    failures = tuple(
        live_matrix.CallReceipt.for_test(
            f"failure-{index}",
            status="failed",
            finding_code=f"failure-class-{index}",
            case_id=f"failure-case-{index}",
            response_sha256=f"{index + 1:064x}",
        )
        for index in range(failure_classes)
    )
    bands = ("valid-mode", "preservation", "noop-hold", "near-miss")
    controls = tuple(
        live_matrix.CallReceipt.for_test(
            f"control-{index}",
            status="verified",
            band=bands[index],
            case_id=f"control-case-{index}",
            response_sha256=f"{index + 20:064x}",
        )
        for index in range(passing_bands)
    )
    return failures + controls


class ReviewAndReportTests(unittest.TestCase):
    def test_packet_caps_one_representative_per_failure_class_and_has_four_controls(self) -> None:
        receipts = synthetic_receipts_for_test(failure_classes=10, passing_bands=4)
        samples = live_matrix.select_review_samples(receipts)
        failures = [sample for sample in samples if sample.is_failure]
        controls = [sample for sample in samples if not sample.is_failure]
        self.assertEqual(len(failures), 8)
        self.assertEqual(len(controls), 4)
        self.assertEqual(len(samples), 12)
        self.assertEqual([sample.candidate_id for sample in samples], [f"candidate-{index:03d}" for index in range(1, 13)])

    def test_packet_orders_material_failure_classes_and_keeps_missing_controls_explicit(self) -> None:
        receipts = (
            live_matrix.CallReceipt.for_test("ordinary", status="failed", finding_code="ordinary"),
            live_matrix.CallReceipt.for_test("embedded", status="failed", finding_code="embedded_instruction_changed"),
            live_matrix.CallReceipt.for_test("literal", status="failed", finding_code="literal_changed"),
            live_matrix.CallReceipt.for_test("negation", status="failed", finding_code="negation_changed"),
            live_matrix.CallReceipt.for_test("attribution", status="failed", finding_code="attribution_changed"),
            live_matrix.CallReceipt.for_test("control", status="verified", band="valid-mode"),
        )
        samples = live_matrix.select_review_samples(receipts)
        self.assertEqual(
            [sample.hard_findings[0] for sample in samples if sample.is_failure],
            ["literal_changed", "negation_changed", "attribution_changed", "embedded_instruction_changed", "ordinary"],
        )
        missing = [sample for sample in samples if not sample.is_failure and sample.missing_control]
        self.assertEqual([sample.band for sample in missing], ["preservation", "noop-hold", "near-miss"])

    def test_packet_removes_producer_identity_and_bounds_redacted_excerpt(self) -> None:
        receipts = synthetic_receipts_for_test(1, 4)
        response = "codex-direct claude-sonnet gemini-3.7 sk-secret-token " + "가" * 200
        samples = live_matrix.select_review_samples(receipts, responses={"failure-0": response})
        prompt = live_matrix.build_review_prompt(samples)
        self.assertNotIn("codex-direct", prompt)
        self.assertNotIn("claude-sonnet", prompt)
        self.assertNotIn("gemini-", prompt)
        self.assertIn("candidate-001", prompt)
        self.assertIn("[REDACTED]", prompt)
        self.assertLessEqual(len(samples[0].candidate.encode("utf-8")), 240)

    def test_review_response_requires_exact_json_contract_without_repair(self) -> None:
        samples = live_matrix.select_review_samples(synthetic_receipts_for_test(1, 4))
        response = json.dumps(
            {
                "samples": [
                    {
                        "candidate_id": sample.candidate_id,
                        "issues": [],
                        "assessment": "pass",
                    }
                    for sample in samples
                ],
                "packet_limitations": ["synthetic evidence only"],
            }
        )
        parsed = live_matrix.parse_review_response(response, samples)
        self.assertEqual(parsed.samples[0].candidate_id, "candidate-001")
        with self.assertRaisesRegex(live_matrix.LiveMatrixError, "review response"):
            live_matrix.parse_review_response("```json\n{}\n```", samples)

    def test_invalid_review_json_creates_one_blocked_receipt_and_reviewer_plan_is_fixed(self) -> None:
        samples = live_matrix.select_review_samples(synthetic_receipts_for_test(1, 4))
        plan = live_matrix.build_reviewer_plan(samples)
        self.assertEqual(
            [(call.reviewer_id, call.requested_model) for call in plan],
            [
                ("reviewer-claude", "claude-sonnet-5-thinking-high"),
                ("reviewer-gemini", "gemini-3.7-flash-high"),
                ("reviewer-grok", "cursor-grok-4.6-high"),
            ],
        )
        original = live_matrix.CallReceipt.for_test("reviewer-claude:packet:1", status="verified")
        parsed, blocked = live_matrix.parse_reviewer_response_or_block(original, "not json", samples)
        self.assertIsNone(parsed)
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(len(blocked.findings), 1)
        self.assertEqual(blocked.findings[0].code, "review_json_invalid")

    def test_aggregate_statuses_keeps_failures_and_blocked_distinct_and_marks_absent(self) -> None:
        receipts = (
            live_matrix.CallReceipt.for_test("producer-a:case:1", status="verified", band="valid-mode"),
            live_matrix.CallReceipt.for_test("producer-a:case:2", status="failed", band="valid-mode"),
            live_matrix.CallReceipt.for_test("producer-b:case:1", status="blocked", band="valid-mode"),
        )
        result = live_matrix.aggregate_statuses(
            receipts,
            producer_ids=("producer-a", "producer-b", "producer-c"),
            bands=("valid-mode",),
        )
        self.assertEqual(result[("producer-a", "valid-mode")], "failed")
        self.assertEqual(result[("producer-b", "valid-mode")], "blocked")
        self.assertEqual(result[("producer-c", "valid-mode")], "not_measured")

    def test_report_has_required_sections_hashes_and_no_response_body(self) -> None:
        receipts = synthetic_receipts_for_test(1, 4)
        report_input = live_matrix.ReportInput.for_test(
            receipts=receipts,
            responses={"failure-0": "PRIVATE FULL RESPONSE BODY sk-secret-token"},
        )
        report = live_matrix.render_operations_report(report_input)
        for heading in (
            "# KWS Korean Writing Editor Cross-Model Evaluation",
            "## Fixed Evidence",
            "## Model Matrix",
            "## Results By Band",
            "## Defect Register",
            "## Review Findings",
            "## Adopted And Rejected Improvements",
            "## Verification",
            "## Limitations And Residual Risks",
            "## Git And Installation State",
        ):
            self.assertIn(heading, report)
        self.assertIn("partially verified", report)
        self.assertIn("Branch: test-branch", report)
        self.assertIn(receipts[0].response_sha256, report)
        self.assertNotIn("PRIVATE FULL RESPONSE BODY", report)
        self.assertNotIn("sk-secret-token", report)
        self.assertNotIn("/Users/", report)
        self.assertIn("pending adjudication", report)
