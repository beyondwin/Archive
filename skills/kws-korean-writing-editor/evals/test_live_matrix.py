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
