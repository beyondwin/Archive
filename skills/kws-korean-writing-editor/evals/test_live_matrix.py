from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live_matrix  # noqa: E402


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
