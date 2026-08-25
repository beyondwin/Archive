#!/usr/bin/env python3
"""Regression tests for accumulate_cost.accumulate / CLI.

Writes to a tmp state.json fixture; never touches a real orchestrator state.
Run a single test: python3 scripts/test_accumulate_cost.py -k combined
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accumulate_cost  # noqa: E402


def _make_state(tmpdir: Path) -> Path:
    state_path = tmpdir / "state.json"
    state_path.write_text(
        json.dumps({"active_plan": "plan1", "cost_ledger": {}}),
        encoding="utf-8",
    )
    return state_path


USAGE = {
    "input_tokens": 1000,
    "output_tokens": 200,
    "cached_read_tokens": 0,
    "cached_write_tokens": 0,
}


class AccumulateBasicTests(unittest.TestCase):
    def test_single_role_dispatch_records_by_task_entry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = _make_state(Path(td))
            entry = accumulate_cost.accumulate(
                state_path, "task_3", "implementer", "opus", dict(USAGE)
            )
            self.assertEqual(entry["role"], "implementer")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            key = "plan1::task_3::implementer"
            self.assertIn(key, state["cost_ledger"]["by_task"])
            self.assertNotIn("combined_roles", state["cost_ledger"]["by_task"][key])

    def test_aggregates_increment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = _make_state(Path(td))
            accumulate_cost.accumulate(
                state_path, "task_3", "implementer", "opus", dict(USAGE)
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                state["cost_ledger"]["totals"]["input_tokens"], USAGE["input_tokens"]
            )
            self.assertEqual(state["cost_ledger"]["by_role"]["implementer"]["dispatches"], 1)


CACHE_USAGE = {
    "input_tokens": 1_000_000,
    "output_tokens": 1_000_000,
    "cache_read_tokens": 1_000_000,
    "cache_creation_tokens": 1_000_000,
}


class CacheTokenTests(unittest.TestCase):
    def test_cache_tokens_preserved_on_by_task_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = _make_state(Path(td))
            entry = accumulate_cost.accumulate(
                state_path, "task_5", "implementer", "opus", dict(CACHE_USAGE)
            )
            self.assertEqual(entry["cache_read_tokens"], 1_000_000)
            self.assertEqual(entry["cache_creation_tokens"], 1_000_000)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            row = state["cost_ledger"]["by_task"]["plan1::task_5::implementer"]
            self.assertEqual(row["cache_read_tokens"], 1_000_000)
            self.assertEqual(row["cache_creation_tokens"], 1_000_000)

    def test_cache_tokens_totals_increment_across_two_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = _make_state(Path(td))
            accumulate_cost.accumulate(
                state_path, "task_5", "implementer", "opus", dict(CACHE_USAGE)
            )
            accumulate_cost.accumulate(
                state_path, "task_6", "reviewer", "opus", dict(CACHE_USAGE)
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            totals = state["cost_ledger"]["totals"]
            self.assertEqual(totals["cache_read_tokens"], 2_000_000)
            self.assertEqual(totals["cache_creation_tokens"], 2_000_000)

    def test_cache_tokens_reflected_in_cost(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = _make_state(Path(td))
            entry = accumulate_cost.accumulate(
                state_path, "task_5", "implementer", "opus", dict(CACHE_USAGE)
            )
            # opus: 1M input*$15 + 1M output*$75 + 1M cache_read*$1.50
            #       + 1M cache_creation*$18.75 = 110.25
            self.assertAlmostEqual(entry["cost_usd"], 110.25, places=3)

    def test_cache_tokens_fixture_totals_field_exists(self) -> None:
        fixture = (
            Path(__file__).resolve().parent.parent
            / "tests" / "fixtures" / "cost_ledger_post_v22.json"
        )
        data = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertGreater(data["totals"]["cache_read_tokens"], 0)
        self.assertGreater(data["totals"]["cache_creation_tokens"], 0)


class CombinedRoleTests(unittest.TestCase):
    def test_combined_roles_tag_recorded_on_ledger_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = _make_state(Path(td))
            entry = accumulate_cost.accumulate(
                state_path,
                "transition_0::combined",
                "verifier",
                "opus",
                dict(USAGE),
                combined_roles=["verify", "docs"],
            )
            self.assertEqual(entry["combined_roles"], ["verify", "docs"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            key = "plan1::transition_0::combined::verifier"
            self.assertEqual(
                state["cost_ledger"]["by_task"][key]["combined_roles"],
                ["verify", "docs"],
            )

    def test_combined_roles_cli_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = _make_state(Path(td))
            rc = accumulate_cost.main([
                "--state", str(state_path),
                "--task-id", "transition_0::combined",
                "--role", "verifier",
                "--model", "opus",
                "--combined-roles", "verify,docs",
                "--usage-json", json.dumps(USAGE),
            ])
            self.assertEqual(rc, 0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            key = "plan1::transition_0::combined::verifier"
            self.assertEqual(
                state["cost_ledger"]["by_task"][key]["combined_roles"],
                ["verify", "docs"],
            )


if __name__ == "__main__":
    unittest.main()
